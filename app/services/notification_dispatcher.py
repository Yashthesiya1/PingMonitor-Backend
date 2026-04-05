"""
Notification dispatcher — sends alerts through all user-configured channels
when incidents are created or resolved.
"""
import json
import httpx
import resend
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.user import User
from app.models.endpoint import Endpoint
from app.models.incident import Incident
from app.models.notification import NotificationChannel, NotificationLog


# Configure Resend
if settings.RESEND_API_KEY:
    resend.api_key = settings.RESEND_API_KEY


def _down_email_html(endpoint_name: str, endpoint_url: str, cause: str, started_at: str) -> str:
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <div style="max-width:560px;margin:40px auto;background:#fff;border-radius:12px;border:1px solid #e4e4e7;overflow:hidden;">
    <div style="background:linear-gradient(135deg,#6c5ce7,#4a3db0);padding:24px 32px;">
      <h1 style="margin:0;color:#fff;font-size:20px;font-weight:700;">PingMonitor</h1>
    </div>
    <div style="background:#fef2f2;border-bottom:1px solid #fecaca;padding:14px 32px;text-align:center;">
      <span style="display:inline-block;background:#ef4444;color:#fff;font-size:11px;font-weight:700;padding:4px 12px;border-radius:20px;text-transform:uppercase;letter-spacing:0.5px;">🔴 Endpoint Down</span>
    </div>
    <div style="padding:28px 32px;">
      <h2 style="margin:0 0 8px;font-size:18px;color:#18181b;">{endpoint_name} is not responding</h2>
      <p style="margin:0 0 20px;color:#71717a;font-size:14px;">We detected that your endpoint is currently down.</p>
      <table style="width:100%;border-collapse:collapse;background:#f4f4f5;border-radius:8px;padding:12px;">
        <tr><td style="padding:8px 12px;color:#71717a;font-size:13px;">URL</td><td style="padding:8px 12px;color:#18181b;font-size:13px;text-align:right;font-family:monospace;word-break:break-all;">{endpoint_url}</td></tr>
        <tr><td style="padding:8px 12px;color:#71717a;font-size:13px;">Cause</td><td style="padding:8px 12px;color:#ef4444;font-size:13px;text-align:right;">{cause}</td></tr>
        <tr><td style="padding:8px 12px;color:#71717a;font-size:13px;">Detected at</td><td style="padding:8px 12px;color:#18181b;font-size:13px;text-align:right;">{started_at}</td></tr>
      </table>
      <a href="{settings.APP_URL}/dashboard/endpoints" style="display:inline-block;margin-top:20px;background:#6c5ce7;color:#fff;text-decoration:none;padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600;">View Dashboard</a>
    </div>
    <div style="border-top:1px solid #e4e4e7;padding:16px 32px;text-align:center;">
      <p style="margin:0;color:#a1a1aa;font-size:11px;">You're receiving this because you enabled email notifications.</p>
    </div>
  </div>
</body>
</html>"""


def _recovery_email_html(endpoint_name: str, endpoint_url: str, duration: str, resolved_at: str) -> str:
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <div style="max-width:560px;margin:40px auto;background:#fff;border-radius:12px;border:1px solid #e4e4e7;overflow:hidden;">
    <div style="background:linear-gradient(135deg,#6c5ce7,#4a3db0);padding:24px 32px;">
      <h1 style="margin:0;color:#fff;font-size:20px;font-weight:700;">PingMonitor</h1>
    </div>
    <div style="background:#f0fdf4;border-bottom:1px solid #bbf7d0;padding:14px 32px;text-align:center;">
      <span style="display:inline-block;background:#22c55e;color:#fff;font-size:11px;font-weight:700;padding:4px 12px;border-radius:20px;text-transform:uppercase;letter-spacing:0.5px;">🟢 Recovered</span>
    </div>
    <div style="padding:28px 32px;">
      <h2 style="margin:0 0 8px;font-size:18px;color:#18181b;">{endpoint_name} is back up</h2>
      <p style="margin:0 0 20px;color:#71717a;font-size:14px;">Your endpoint has recovered and is responding normally.</p>
      <table style="width:100%;border-collapse:collapse;background:#f4f4f5;border-radius:8px;padding:12px;">
        <tr><td style="padding:8px 12px;color:#71717a;font-size:13px;">URL</td><td style="padding:8px 12px;color:#18181b;font-size:13px;text-align:right;font-family:monospace;word-break:break-all;">{endpoint_url}</td></tr>
        <tr><td style="padding:8px 12px;color:#71717a;font-size:13px;">Downtime</td><td style="padding:8px 12px;color:#18181b;font-size:13px;text-align:right;">{duration}</td></tr>
        <tr><td style="padding:8px 12px;color:#71717a;font-size:13px;">Recovered at</td><td style="padding:8px 12px;color:#18181b;font-size:13px;text-align:right;">{resolved_at}</td></tr>
      </table>
      <a href="{settings.APP_URL}/dashboard/endpoints" style="display:inline-block;margin-top:20px;background:#6c5ce7;color:#fff;text-decoration:none;padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600;">View Dashboard</a>
    </div>
    <div style="border-top:1px solid #e4e4e7;padding:16px 32px;text-align:center;">
      <p style="margin:0;color:#a1a1aa;font-size:11px;">You're receiving this because you enabled email notifications.</p>
    </div>
  </div>
</body>
</html>"""


def _get_config(channel: NotificationChannel) -> dict:
    cfg = channel.config
    if isinstance(cfg, str):
        try:
            return json.loads(cfg)
        except Exception:
            return {}
    return cfg or {}


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} seconds"
    if seconds < 3600:
        return f"{seconds // 60} minutes"
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    return f"{hours}h {mins}m"


async def _send_email(user: User, subject: str, html: str) -> tuple[bool, str | None]:
    """Send email via Resend."""
    if not settings.RESEND_API_KEY:
        return False, "Resend API key not configured"
    try:
        resend.Emails.send({
            "from": settings.EMAIL_FROM,
            "to": [user.email],
            "subject": subject,
            "html": html,
        })
        return True, None
    except Exception as e:
        return False, str(e)[:500]


async def _send_slack(webhook_url: str, endpoint_name: str, endpoint_url: str, is_down: bool, extra: str) -> tuple[bool, str | None]:
    emoji = ":red_circle:" if is_down else ":large_green_circle:"
    action = "is DOWN" if is_down else "is back UP"
    text = f"{emoji} *{endpoint_name}* {action}\nURL: {endpoint_url}\n{extra}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(webhook_url, json={"text": text})
        if r.status_code >= 400:
            return False, f"Slack returned {r.status_code}"
        return True, None
    except Exception as e:
        return False, str(e)[:500]


async def _send_discord(webhook_url: str, endpoint_name: str, endpoint_url: str, is_down: bool, extra: str) -> tuple[bool, str | None]:
    emoji = "🔴" if is_down else "🟢"
    action = "is DOWN" if is_down else "is back UP"
    content = f"{emoji} **{endpoint_name}** {action}\nURL: {endpoint_url}\n{extra}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(webhook_url, json={"content": content})
        if r.status_code >= 400:
            return False, f"Discord returned {r.status_code}"
        return True, None
    except Exception as e:
        return False, str(e)[:500]


async def _send_telegram(bot_token: str, chat_id: str, endpoint_name: str, endpoint_url: str, is_down: bool, extra: str) -> tuple[bool, str | None]:
    emoji = "🔴" if is_down else "🟢"
    action = "is DOWN" if is_down else "is back UP"
    text = f"{emoji} {endpoint_name} {action}\nURL: {endpoint_url}\n{extra}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
        if r.status_code >= 400:
            return False, f"Telegram returned {r.status_code}"
        return True, None
    except Exception as e:
        return False, str(e)[:500]


async def _send_webhook(url: str, headers_str: str, payload: dict) -> tuple[bool, str | None]:
    headers = {"Content-Type": "application/json"}
    if headers_str:
        try:
            headers.update(json.loads(headers_str))
        except Exception:
            pass
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload, headers=headers)
        if r.status_code >= 400:
            return False, f"Webhook returned {r.status_code}"
        return True, None
    except Exception as e:
        return False, str(e)[:500]


async def dispatch_incident_notifications(
    db: AsyncSession,
    user_id: str,
    endpoint_id: str,
    incident_id: str,
    event_type: str,  # "endpoint_down" or "endpoint_recovered"
    cause: str | None = None,
    duration_seconds: int | None = None,
) -> None:
    """Send alerts to all active notification channels for the user."""
    # Get user, endpoint
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        return

    ep_result = await db.execute(select(Endpoint).where(Endpoint.id == endpoint_id))
    endpoint = ep_result.scalar_one_or_none()
    if not endpoint:
        return

    # Get all active channels
    channels_result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.user_id == user_id,
            NotificationChannel.is_active == True,
        )
    )
    channels = channels_result.scalars().all()

    if not channels:
        return  # No channels configured — don't send anything

    is_down = event_type == "endpoint_down"
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    duration = _format_duration(duration_seconds) if duration_seconds else "< 1 minute"

    for channel in channels:
        config = _get_config(channel)
        success = False
        error_msg = None

        try:
            if channel.channel_type == "email":
                subject = (
                    f"🔴 [DOWN] {endpoint.name} is not responding"
                    if is_down
                    else f"🟢 [RECOVERED] {endpoint.name} is back up"
                )
                html = (
                    _down_email_html(endpoint.name, endpoint.url, cause or "Unreachable", now_str)
                    if is_down
                    else _recovery_email_html(endpoint.name, endpoint.url, duration, now_str)
                )
                success, error_msg = await _send_email(user, subject, html)

            elif channel.channel_type == "slack":
                url = config.get("webhook_url")
                if url:
                    extra = f"Cause: {cause or 'Unknown'}" if is_down else f"Downtime: {duration}"
                    success, error_msg = await _send_slack(url, endpoint.name, endpoint.url, is_down, extra)

            elif channel.channel_type == "discord":
                url = config.get("webhook_url")
                if url:
                    extra = f"Cause: {cause or 'Unknown'}" if is_down else f"Downtime: {duration}"
                    success, error_msg = await _send_discord(url, endpoint.name, endpoint.url, is_down, extra)

            elif channel.channel_type == "teams":
                url = config.get("webhook_url")
                if url:
                    extra = f"Cause: {cause or 'Unknown'}" if is_down else f"Downtime: {duration}"
                    success, error_msg = await _send_slack(url, endpoint.name, endpoint.url, is_down, extra)

            elif channel.channel_type == "telegram":
                bot_token = config.get("bot_token")
                chat_id = config.get("chat_id")
                if bot_token and chat_id:
                    extra = f"Cause: {cause or 'Unknown'}" if is_down else f"Downtime: {duration}"
                    success, error_msg = await _send_telegram(bot_token, chat_id, endpoint.name, endpoint.url, is_down, extra)

            elif channel.channel_type == "webhook":
                url = config.get("webhook_url")
                if url:
                    payload = {
                        "event": event_type,
                        "endpoint": {"id": str(endpoint.id), "name": endpoint.name, "url": endpoint.url},
                        "incident_id": incident_id,
                        "cause": cause,
                        "duration_seconds": duration_seconds,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    headers_str = config.get("headers", "")
                    success, error_msg = await _send_webhook(url, headers_str, payload)

        except Exception as e:
            error_msg = str(e)[:500]

        # Log the notification attempt
        log = NotificationLog(
            user_id=user_id,
            endpoint_id=endpoint_id,
            incident_id=incident_id,
            channel_id=channel.id,
            channel_type=channel.channel_type,
            event_type=event_type,
            status="sent" if success else "failed",
            error_message=error_msg,
        )
        db.add(log)
