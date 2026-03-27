from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.user import User
from app.models.endpoint import Endpoint
from app.models.check import EndpointCheck
from app.models.incident import Incident
from app.models.notification import NotificationChannel, NotificationLog
from app.dependencies import get_admin_user

router = APIRouter(prefix="/admin", tags=["Admin"])


# ========================
# OVERVIEW / STATS
# ========================

class AdminStatsResponse(BaseModel):
    total_users: int
    total_endpoints: int
    active_endpoints: int
    total_checks_today: int
    avg_response_time: float
    uptime_percentage: float
    total_incidents: int
    open_incidents: int
    total_notifications_sent: int


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

    total_incidents = (await db.execute(select(func.count()).select_from(Incident))).scalar() or 0
    open_incidents = (await db.execute(
        select(func.count()).where(Incident.is_resolved == False)
    )).scalar() or 0
    total_notifications = (await db.execute(select(func.count()).select_from(NotificationLog))).scalar() or 0

    return AdminStatsResponse(
        total_users=total_users,
        total_endpoints=total_endpoints,
        active_endpoints=active_endpoints,
        total_checks_today=checks_today,
        avg_response_time=round(float(avg_response), 1),
        uptime_percentage=round(uptime_pct, 1),
        total_incidents=total_incidents,
        open_incidents=open_incidents,
        total_notifications_sent=total_notifications,
    )


class ActivityItem(BaseModel):
    type: str
    description: str
    timestamp: datetime


@router.get("/activity", response_model=list[ActivityItem])
async def get_recent_activity(
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    activities: list[ActivityItem] = []

    # Recent signups
    result = await db.execute(
        select(User).order_by(desc(User.created_at)).limit(5)
    )
    for u in result.scalars().all():
        activities.append(ActivityItem(
            type="signup",
            description=f"{u.name or u.email} signed up",
            timestamp=u.created_at,
        ))

    # Recent endpoints
    result = await db.execute(
        select(Endpoint).order_by(desc(Endpoint.created_at)).limit(5)
    )
    for ep in result.scalars().all():
        activities.append(ActivityItem(
            type="endpoint",
            description=f"Monitor '{ep.name}' added ({ep.url})",
            timestamp=ep.created_at,
        ))

    # Recent incidents
    result = await db.execute(
        select(Incident).order_by(desc(Incident.created_at)).limit(5)
    )
    for inc in result.scalars().all():
        activities.append(ActivityItem(
            type="incident",
            description=f"Incident: {inc.cause or 'Unknown'}" + (" (resolved)" if inc.is_resolved else " (ongoing)"),
            timestamp=inc.created_at,
        ))

    activities.sort(key=lambda a: a.timestamp, reverse=True)
    return activities[:10]


# ========================
# USERS MANAGEMENT
# ========================

class UserListItem(BaseModel):
    id: str
    email: str
    name: str | None
    role: str
    credits: int
    max_endpoints: int
    is_active: bool
    is_verified: bool
    endpoints_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/users", response_model=list[UserListItem])
async def list_users(
    search: str = Query(default="", description="Search by name or email"),
    role: str = Query(default="", description="Filter by role"),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(User).order_by(User.created_at.desc())

    if search:
        query = query.where(
            User.email.ilike(f"%{search}%") | User.name.ilike(f"%{search}%")
        )
    if role:
        query = query.where(User.role == role)

    result = await db.execute(query)
    users = result.scalars().all()

    # Get endpoint counts per user
    items = []
    for u in users:
        ep_count = (await db.execute(
            select(func.count()).where(Endpoint.user_id == u.id)
        )).scalar() or 0

        items.append(UserListItem(
            id=str(u.id),
            email=u.email,
            name=u.name,
            role=u.role,
            credits=u.credits,
            max_endpoints=u.max_endpoints,
            is_active=u.is_active,
            is_verified=u.is_verified,
            endpoints_count=ep_count,
            created_at=u.created_at,
        ))

    return items


class UserDetailResponse(BaseModel):
    id: str
    email: str
    name: str | None
    role: str
    credits: int
    max_endpoints: int
    is_active: bool
    is_verified: bool
    created_at: datetime
    endpoints_count: int
    checks_count: int
    incidents_count: int
    channels_count: int


@router.get("/users/{user_id}", response_model=UserDetailResponse)
async def get_user_detail(
    user_id: str,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    ep_count = (await db.execute(select(func.count()).where(Endpoint.user_id == user_id))).scalar() or 0
    ep_ids_result = await db.execute(select(Endpoint.id).where(Endpoint.user_id == user_id))
    ep_ids = [str(r) for r in ep_ids_result.scalars().all()]

    checks_count = 0
    if ep_ids:
        checks_count = (await db.execute(
            select(func.count()).where(EndpointCheck.endpoint_id.in_(ep_ids))
        )).scalar() or 0

    incidents_count = (await db.execute(
        select(func.count()).where(Incident.user_id == user_id)
    )).scalar() or 0
    channels_count = (await db.execute(
        select(func.count()).where(NotificationChannel.user_id == user_id)
    )).scalar() or 0

    return UserDetailResponse(
        id=str(target.id),
        email=target.email,
        name=target.name,
        role=target.role,
        credits=target.credits,
        max_endpoints=target.max_endpoints,
        is_active=target.is_active,
        is_verified=target.is_verified,
        created_at=target.created_at,
        endpoints_count=ep_count,
        checks_count=checks_count,
        incidents_count=incidents_count,
        channels_count=channels_count,
    )


class UserUpdateRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    credits: int | None = None
    max_endpoints: int | None = None


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if body.role is not None:
        target.role = body.role
    if body.is_active is not None:
        target.is_active = body.is_active
    if body.credits is not None:
        target.credits = body.credits
    if body.max_endpoints is not None:
        target.max_endpoints = body.max_endpoints

    await db.commit()
    return {"message": "User updated"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if str(user.id) == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(target)
    await db.commit()
    return {"message": "User deleted"}


# ========================
# ALL ENDPOINTS (platform-wide)
# ========================

class AdminEndpointItem(BaseModel):
    id: str
    name: str
    url: str
    method: str
    monitor_type: str
    check_interval: int
    is_active: bool
    user_id: str
    user_email: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/endpoints", response_model=list[AdminEndpointItem])
async def list_all_endpoints(
    search: str = Query(default=""),
    status: str = Query(default=""),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Endpoint).order_by(Endpoint.created_at.desc())

    if search:
        query = query.where(
            Endpoint.name.ilike(f"%{search}%") | Endpoint.url.ilike(f"%{search}%")
        )
    if status == "active":
        query = query.where(Endpoint.is_active == True)
    elif status == "paused":
        query = query.where(Endpoint.is_active == False)

    result = await db.execute(query)
    endpoints = result.scalars().all()

    # Get user emails
    user_ids = list(set(ep.user_id for ep in endpoints))
    user_map = {}
    if user_ids:
        users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in users_result.scalars().all():
            user_map[str(u.id)] = u.email

    return [
        AdminEndpointItem(
            id=str(ep.id),
            name=ep.name,
            url=ep.url,
            method=ep.method,
            monitor_type=ep.monitor_type,
            check_interval=ep.check_interval,
            is_active=ep.is_active,
            user_id=str(ep.user_id),
            user_email=user_map.get(str(ep.user_id), ""),
            created_at=ep.created_at,
        )
        for ep in endpoints
    ]


# ========================
# ALL CHECKS (platform-wide)
# ========================

class AdminCheckItem(BaseModel):
    id: str
    endpoint_id: str
    endpoint_name: str = ""
    user_email: str = ""
    status_code: int | None
    response_time_ms: int | None
    is_up: bool
    error_message: str | None
    checked_at: datetime


@router.get("/checks", response_model=list[AdminCheckItem])
async def list_all_checks(
    status: str = Query(default=""),
    limit: int = Query(default=100, le=500),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(EndpointCheck).order_by(desc(EndpointCheck.checked_at)).limit(limit)

    if status == "up":
        query = query.where(EndpointCheck.is_up == True)
    elif status == "down":
        query = query.where(EndpointCheck.is_up == False)

    result = await db.execute(query)
    checks = result.scalars().all()

    # Get endpoint names and user emails
    ep_ids = list(set(str(c.endpoint_id) for c in checks))
    ep_map = {}
    user_map = {}
    if ep_ids:
        eps_result = await db.execute(select(Endpoint).where(Endpoint.id.in_(ep_ids)))
        for ep in eps_result.scalars().all():
            ep_map[str(ep.id)] = ep.name
            user_map[str(ep.id)] = str(ep.user_id)

        u_ids = list(set(user_map.values()))
        users_result = await db.execute(select(User).where(User.id.in_(u_ids)))
        email_map = {str(u.id): u.email for u in users_result.scalars().all()}

    return [
        AdminCheckItem(
            id=str(c.id),
            endpoint_id=str(c.endpoint_id),
            endpoint_name=ep_map.get(str(c.endpoint_id), ""),
            user_email=email_map.get(user_map.get(str(c.endpoint_id), ""), "") if ep_ids else "",
            status_code=c.status_code,
            response_time_ms=c.response_time_ms,
            is_up=c.is_up,
            error_message=c.error_message,
            checked_at=c.checked_at,
        )
        for c in checks
    ]


# ========================
# ALL INCIDENTS (platform-wide)
# ========================

class AdminIncidentItem(BaseModel):
    id: str
    endpoint_id: str
    endpoint_name: str = ""
    user_email: str = ""
    started_at: datetime
    resolved_at: datetime | None
    is_resolved: bool
    cause: str | None
    duration_seconds: int | None
    consecutive_failures: int


@router.get("/incidents", response_model=list[AdminIncidentItem])
async def list_all_incidents(
    status: str = Query(default=""),
    limit: int = Query(default=100, le=500),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Incident).order_by(desc(Incident.started_at)).limit(limit)

    if status == "open":
        query = query.where(Incident.is_resolved == False)
    elif status == "resolved":
        query = query.where(Incident.is_resolved == True)

    result = await db.execute(query)
    incidents = result.scalars().all()

    ep_ids = list(set(str(i.endpoint_id) for i in incidents))
    ep_map = {}
    email_map = {}
    if ep_ids:
        eps_result = await db.execute(select(Endpoint).where(Endpoint.id.in_(ep_ids)))
        user_ids = set()
        for ep in eps_result.scalars().all():
            ep_map[str(ep.id)] = {"name": ep.name, "user_id": str(ep.user_id)}
            user_ids.add(str(ep.user_id))

        users_result = await db.execute(select(User).where(User.id.in_(list(user_ids))))
        email_map = {str(u.id): u.email for u in users_result.scalars().all()}

    return [
        AdminIncidentItem(
            id=str(i.id),
            endpoint_id=str(i.endpoint_id),
            endpoint_name=ep_map.get(str(i.endpoint_id), {}).get("name", ""),
            user_email=email_map.get(ep_map.get(str(i.endpoint_id), {}).get("user_id", ""), ""),
            started_at=i.started_at,
            resolved_at=i.resolved_at,
            is_resolved=i.is_resolved,
            cause=i.cause,
            duration_seconds=i.duration_seconds,
            consecutive_failures=i.consecutive_failures,
        )
        for i in incidents
    ]


# ========================
# ALL NOTIFICATIONS (platform-wide)
# ========================

class AdminNotificationItem(BaseModel):
    id: str
    user_email: str = ""
    endpoint_name: str = ""
    channel_type: str
    event_type: str
    status: str
    error_message: str | None
    sent_at: datetime


@router.get("/notifications", response_model=list[AdminNotificationItem])
async def list_all_notifications(
    limit: int = Query(default=100, le=500),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(NotificationLog).order_by(desc(NotificationLog.sent_at)).limit(limit)
    )
    logs = result.scalars().all()

    # Get user emails and endpoint names
    user_ids = list(set(str(n.user_id) for n in logs))
    ep_ids = list(set(str(n.endpoint_id) for n in logs))

    email_map = {}
    if user_ids:
        users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
        email_map = {str(u.id): u.email for u in users_result.scalars().all()}

    ep_map = {}
    if ep_ids:
        eps_result = await db.execute(select(Endpoint).where(Endpoint.id.in_(ep_ids)))
        ep_map = {str(ep.id): ep.name for ep in eps_result.scalars().all()}

    return [
        AdminNotificationItem(
            id=str(n.id),
            user_email=email_map.get(str(n.user_id), ""),
            endpoint_name=ep_map.get(str(n.endpoint_id), ""),
            channel_type=n.channel_type,
            event_type=n.event_type,
            status=n.status,
            error_message=n.error_message,
            sent_at=n.sent_at,
        )
        for n in logs
    ]
