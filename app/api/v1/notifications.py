import json
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from app.database import get_db
from app.models.user import User
from app.models.notification import NotificationChannel, NotificationLog
from app.models.incident import Incident
from app.dependencies import get_current_user

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# --- Schemas ---

class ChannelCreate(BaseModel):
    channel_type: str
    name: str
    config: dict = {}


class ChannelUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    is_active: bool | None = None


class ChannelResponse(BaseModel):
    id: str
    channel_type: str
    name: str
    config: dict
    is_active: bool
    created_at: datetime

    @classmethod
    def from_model(cls, channel):
        config = channel.config
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except Exception:
                config = {}
        return cls(
            id=str(channel.id),
            channel_type=channel.channel_type,
            name=channel.name,
            config=config,
            is_active=channel.is_active,
            created_at=channel.created_at,
        )


class NotificationLogResponse(BaseModel):
    id: str
    endpoint_id: str
    incident_id: str | None
    channel_type: str
    event_type: str
    status: str
    error_message: str | None
    sent_at: datetime

    model_config = {"from_attributes": True}


# --- Channels ---

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
    return [ChannelResponse.from_model(c).model_dump() for c in result.scalars().all()]


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
        config=json.dumps(body.config),
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return ChannelResponse.from_model(channel).model_dump()


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
        channel.config = json.dumps(body.config)
    if body.is_active is not None:
        channel.is_active = body.is_active

    await db.commit()
    await db.refresh(channel)
    return ChannelResponse.from_model(channel).model_dump()


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

class TestNotificationRequest(BaseModel):
    channel_type: str
    config: dict = {}


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

    # Parse config from JSON string if needed
    config = channel.config
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except Exception:
            config = {}

    try:
        test_msg = f"[TEST] PingMonitor — Test notification for {channel.name}. Your {channel.channel_type} channel is working."

        if channel.channel_type == "email":
            # TODO: Integrate Resend
            return {"success": True, "message": "Email test (Resend not configured yet)"}

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
                data = resp.json()
                raise HTTPException(status_code=400, detail=data.get("description", "Telegram error"))

        elif channel.channel_type == "webhook":
            url = config.get("webhook_url")
            if not url:
                raise HTTPException(status_code=400, detail="Webhook URL required")
            headers = {"Content-Type": "application/json"}
            if config.get("headers"):
                try:
                    headers.update(json.loads(config["headers"]) if isinstance(config["headers"], str) else config["headers"])
                except Exception:
                    pass
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json={"event": "test", "message": test_msg}, headers=headers)
            if resp.status_code >= 400:
                raise HTTPException(status_code=400, detail=f"Webhook returned {resp.status_code}")

        elif channel.channel_type == "sms":
            return {"success": True, "message": "SMS test (provider not configured yet)"}

        else:
            raise HTTPException(status_code=400, detail="Unsupported channel type")

        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- History ---

@router.get("/history", response_model=list[NotificationLogResponse])
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
    return result.scalars().all()


# --- Global Incidents ---

class IncidentResponse(BaseModel):
    id: str
    endpoint_id: str
    user_id: str
    started_at: datetime
    resolved_at: datetime | None
    is_resolved: bool
    cause: str | None
    duration_seconds: int | None
    consecutive_failures: int
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/incidents", response_model=list[IncidentResponse])
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
    return result.scalars().all()
