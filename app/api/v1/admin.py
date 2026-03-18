from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.user import User
from app.models.endpoint import Endpoint
from app.models.check import EndpointCheck
from app.dependencies import get_admin_user

router = APIRouter(prefix="/admin", tags=["Admin"])


class AdminStatsResponse(BaseModel):
    total_users: int
    total_endpoints: int
    active_endpoints: int
    total_checks_today: int
    avg_response_time: float
    uptime_percentage: float


@router.get("/stats", response_model=AdminStatsResponse)
async def get_stats(
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    total_users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    total_endpoints = (await db.execute(select(func.count()).select_from(Endpoint))).scalar() or 0
    active_endpoints = (await db.execute(
        select(func.count()).where(Endpoint.is_active == True)
    )).scalar() or 0

    checks_today = (await db.execute(
        select(func.count()).where(EndpointCheck.checked_at >= today)
    )).scalar() or 0

    avg_response = (await db.execute(
        select(func.avg(EndpointCheck.response_time_ms)).where(
            EndpointCheck.checked_at >= today,
            EndpointCheck.response_time_ms.isnot(None),
        )
    )).scalar() or 0

    total_up = (await db.execute(
        select(func.count()).where(
            EndpointCheck.checked_at >= today,
            EndpointCheck.is_up == True,
        )
    )).scalar() or 0

    uptime_pct = (total_up / checks_today * 100) if checks_today > 0 else 0

    return AdminStatsResponse(
        total_users=total_users,
        total_endpoints=total_endpoints,
        active_endpoints=active_endpoints,
        total_checks_today=checks_today,
        avg_response_time=round(avg_response, 1),
        uptime_percentage=round(uptime_pct, 1),
    )


class UserListItem(BaseModel):
    id: str
    email: str
    name: str | None
    role: str
    credits: int
    max_endpoints: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/users", response_model=list[UserListItem])
async def list_users(
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    return [
        UserListItem(
            id=str(u.id),
            email=u.email,
            name=u.name,
            role=u.role,
            credits=u.credits,
            max_endpoints=u.max_endpoints,
            is_active=u.is_active,
            created_at=u.created_at,
        )
        for u in users
    ]
