import asyncio
import httpx
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.workers.celery_app import celery
from app.database import async_session
from app.models.user import User
from app.models.endpoint import Endpoint
from app.models.check import EndpointCheck
from app.models.incident import Incident
from app.models.notification import NotificationChannel, NotificationLog


async def _dispatch_notification(
    db: AsyncSession,
    user: User,
    endpoint: Endpoint,
    incident: Incident,
    event_type: str,
    duration: str | None = None,
):
    """Send notification to all active channels for a user."""
    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.user_id == user.id,
            NotificationChannel.is_active == True,
        )
    )
    channels = result.scalars().all()

    # Fallback to email if no channels configured
    if not channels:
        channels = [NotificationChannel(
            channel_type="email",
            name="Email",
            config={},
        )]

    for channel in channels:
        status = "sent"
        error_msg = None

        try:
            if channel.channel_type == "email":
                # TODO: Integrate with Resend
                pass

            elif channel.channel_type in ("slack", "teams"):
                url = channel.config.get("webhook_url")
                if url:
                    emoji = ":red_circle:" if event_type == "endpoint_down" else ":large_green_circle:"
                    action = "is DOWN" if event_type == "endpoint_down" else "is back UP"
                    text = f"{emoji} *{endpoint.name}* {action}\nURL: {endpoint.url}"
                    if duration:
                        text += f"\nDowntime: {duration}"

                    async with httpx.AsyncClient() as client:
                        await client.post(url, json={"text": text})

            elif channel.channel_type == "discord":
                url = channel.config.get("webhook_url")
                if url:
                    emoji = "🔴" if event_type == "endpoint_down" else "🟢"
                    action = "is DOWN" if event_type == "endpoint_down" else "is back UP"
                    content = f"{emoji} **{endpoint.name}** {action}\nURL: {endpoint.url}"
                    if duration:
                        content += f"\nDowntime: {duration}"

                    async with httpx.AsyncClient() as client:
                        await client.post(url, json={"content": content})

            elif channel.channel_type == "telegram":
                bot_token = channel.config.get("bot_token")
                chat_id = channel.config.get("chat_id")
                if bot_token and chat_id:
                    emoji = "🔴" if event_type == "endpoint_down" else "🟢"
                    action = "is DOWN" if event_type == "endpoint_down" else "is back UP"
                    text = f"{emoji} {endpoint.name} {action}\nURL: {endpoint.url}"

                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"https://api.telegram.org/bot{bot_token}/sendMessage",
                            json={"chat_id": chat_id, "text": text},
                        )

            elif channel.channel_type == "webhook":
                url = channel.config.get("webhook_url")
                if url:
                    payload = {
                        "event": event_type,
                        "endpoint": {"name": endpoint.name, "url": endpoint.url},
                        "incident_id": str(incident.id) if incident else None,
                        "duration": duration,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    headers = {"Content-Type": "application/json"}
                    if channel.config.get("headers"):
                        try:
                            import json
                            headers.update(json.loads(channel.config["headers"]))
                        except Exception:
                            pass

                    async with httpx.AsyncClient() as client:
                        await client.post(url, json=payload, headers=headers)

        except Exception as e:
            status = "failed"
            error_msg = str(e)[:500]

        # Log notification
        log = NotificationLog(
            user_id=user.id,
            endpoint_id=endpoint.id,
            incident_id=incident.id if incident else None,
            channel_id=channel.id if hasattr(channel, "id") and channel.id else None,
            channel_type=channel.channel_type,
            event_type=event_type,
            status=status,
            error_message=error_msg,
        )
        db.add(log)

    await db.commit()


@celery.task(name="app.workers.notification_worker.send_weekly_summaries")
def send_weekly_summaries():
    """Send weekly summary emails to all users."""
    async def _send():
        async with async_session() as db:
            result = await db.execute(select(User).where(User.is_active == True))
            users = result.scalars().all()

            sent = 0
            for user in users:
                # Get user's endpoint count
                ep_result = await db.execute(
                    select(func.count()).where(Endpoint.user_id == user.id)
                )
                ep_count = ep_result.scalar() or 0
                if ep_count == 0:
                    continue

                # TODO: Build and send weekly summary email via Resend
                sent += 1

            return {"sent": sent}

    return asyncio.run(_send())
