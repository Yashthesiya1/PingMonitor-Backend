from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from app.database import get_db
from app.models.user import User
from app.models.notification import NotificationChannel, NotificationLog
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
    id: UUID
    channel_type: str
    name: str
    config: dict
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationLogResponse(BaseModel):
    id: UUID
    endpoint_id: UUID
    incident_id: UUID | None
    channel_type: str
    event_type: str
    status: str
    error_message: str | None
    sent_at: datetime

    model_config = {"from_attributes": True}


# --- Channels ---

@router.get("/channels", response_model=list[ChannelResponse])
async def list_channels(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(NotificationChannel)
        .where(NotificationChannel.user_id == user.id)
        .order_by(NotificationChannel.created_at.desc())
    )
    return result.scalars().all()


@router.post("/channels", response_model=ChannelResponse, status_code=201)
async def create_channel(
    body: ChannelCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    channel = NotificationChannel(
        user_id=user.id,
        channel_type=body.channel_type,
        name=body.name,
        config=body.config,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.patch("/channels/{channel_id}", response_model=ChannelResponse)
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
        channel.config = body.config
    if body.is_active is not None:
        channel.is_active = body.is_active

    await db.commit()
    await db.refresh(channel)
    return channel


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
