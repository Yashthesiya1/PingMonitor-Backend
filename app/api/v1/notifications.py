import json as json_lib
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime

from app.database import get_db
from app.models.user import User
from app.models.notification import NotificationChannel, NotificationLog
from app.models.incident import Incident
from app.dependencies import get_current_user

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# --- Helpers ---

def parse_config(config_val) -> dict:
    """Parse config from DB (could be str or dict)."""
    if isinstance(config_val, dict):
        return config_val
    if isinstance(config_val, str):
        try:
            return json_lib.loads(config_val)
        except Exception:
            return {}
    return {}


def channel_to_dict(channel) -> dict:
    """Convert a NotificationChannel model to a dict for the API response."""
    return {
        "id": str(channel.id),
        "channel_type": channel.channel_type,
        "name": channel.name,
        "config": parse_config(channel.config),
        "is_active": channel.is_active,
        "created_at": channel.created_at.isoformat() if channel.created_at else None,
    }


# --- Schemas ---

class ChannelCreate(BaseModel):
    channel_type: str
    name: str
    config: dict = {}


class ChannelUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    is_active: bool | None = None


# --- Channels CRUD ---

@router.get("/channels")
async def list_channels(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(NotificationChannel)
        .where(NotificationChannel.user_id == user.id)
        .order_by(NotificationChannel.created_at.desc())
    )
    return [channel_to_dict(c) for c in result.scalars().all()]


@router.post("/channels", status_code=201)
async def create_channel(
    body: ChannelCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    channel = NotificationChannel(
        user_id=user.id,
        channel_type=body.channel_type,
        name=body.name,
        config=json_lib.dumps(body.config),
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel_to_dict(channel)


@router.patch("/channels/{channel_id}")
async def update_channel(
    channel_id: str,
    body: ChannelUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.user_id == user.id,
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    if body.name is not None:
        channel.name = body.name
    if body.config is not None:
        channel.config = json_lib.dumps(body.config)
    if body.is_active is not None:
        channel.is_active = body.is_active

    await db.commit()
    await db.refresh(channel)
    return channel_to_dict(channel)


@router.delete("/channels/{channel_id}")
async def delete_channel(
    channel_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.user_id == user.id,
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    await db.delete(channel)
    await db.commit()
    return {"message": "Channel deleted"}


# --- Test Notification ---

@router.post("/channels/{channel_id}/test")
async def test_channel(
    channel_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.user_id == user.id,
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    config = parse_config(channel.config)

    try:
        test_msg = f"[TEST] PingMonitor — Your {channel.channel_type} channel '{channel.name}' is working!"

        if channel.channel_type == "email":
            return {"success": True, "message": "Email test sent"}

        elif channel.channel_type in ("slack", "teams"):
            url = config.get("webhook_url")
            if not url:
                raise HTTPException(status_code=400, detail="Webhook URL required")
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json={"text": test_msg})
            if resp.status_code >= 400:
                raise HTTPException(status_code=400, detail=f"Webhook returned {resp.status_code}")

        elif channel.channel_type == "discord":
            url = config.get("webhook_url")
            if not url:
                raise HTTPException(status_code=400, detail="Webhook URL required")
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json={"content": test_msg})
            if resp.status_code >= 400:
                raise HTTPException(status_code=400, detail=f"Webhook returned {resp.status_code}")

        elif channel.channel_type == "telegram":
            bot_token = config.get("bot_token")
            chat_id = config.get("chat_id")
            if not bot_token or not chat_id:
                raise HTTPException(status_code=400, detail="Bot token and chat ID required")
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": test_msg},
                )
            if resp.status_code >= 400:
                raise HTTPException(status_code=400, detail="Telegram API error")

        elif channel.channel_type == "webhook":
            url = config.get("webhook_url")
            if not url:
                raise HTTPException(status_code=400, detail="Webhook URL required")
            headers = {"Content-Type": "application/json"}
            extra_headers = config.get("headers")
            if extra_headers:
                if isinstance(extra_headers, str):
                    try:
                        headers.update(json_lib.loads(extra_headers))
                    except Exception:
                        pass
                elif isinstance(extra_headers, dict):
                    headers.update(extra_headers)
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json={"event": "test", "message": test_msg}, headers=headers)
            if resp.status_code >= 400:
                raise HTTPException(status_code=400, detail=f"Webhook returned {resp.status_code}")

        elif channel.channel_type == "sms":
            return {"success": True, "message": "SMS provider not configured yet"}

        else:
            raise HTTPException(status_code=400, detail="Unsupported channel type")

        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Notification History ---

@router.get("/history")
async def notification_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(NotificationLog)
        .where(NotificationLog.user_id == user.id)
        .order_by(NotificationLog.sent_at.desc())
        .limit(100)
    )
    logs = result.scalars().all()
    return [
        {
            "id": str(n.id),
            "endpoint_id": str(n.endpoint_id),
            "incident_id": str(n.incident_id) if n.incident_id else None,
            "channel_type": n.channel_type,
            "event_type": n.event_type,
            "status": n.status,
            "error_message": n.error_message,
            "sent_at": n.sent_at.isoformat() if n.sent_at else None,
        }
        for n in logs
    ]


# --- Global Incidents ---

@router.get("/incidents")
async def list_all_incidents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Incident)
        .where(Incident.user_id == user.id)
        .order_by(Incident.started_at.desc())
        .limit(100)
    )
    incidents = result.scalars().all()
    return [
        {
            "id": str(i.id),
            "endpoint_id": str(i.endpoint_id),
            "user_id": str(i.user_id),
            "started_at": i.started_at.isoformat() if i.started_at else None,
            "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
            "is_resolved": i.is_resolved,
            "cause": i.cause,
            "duration_seconds": i.duration_seconds,
            "consecutive_failures": i.consecutive_failures,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in incidents
    ]
