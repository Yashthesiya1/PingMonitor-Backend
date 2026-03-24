from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.user import User
from app.models.endpoint import Endpoint
from app.models.check import EndpointCheck
from app.models.incident import Incident
from app.schemas.endpoint import (
    EndpointCreate,
    EndpointUpdate,
    EndpointResponse,
    CheckResponse,
    IncidentResponse,
)
from app.dependencies import get_current_user

router = APIRouter(prefix="/endpoints", tags=["Endpoints"])


@router.get("", response_model=list[EndpointResponse])
async def list_endpoints(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Endpoint)
        .where(Endpoint.user_id == user.id)
        .order_by(Endpoint.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=EndpointResponse, status_code=201)
async def create_endpoint(
    body: EndpointCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Check limit
    result = await db.execute(
        select(func.count()).where(Endpoint.user_id == user.id)
    )
    count = result.scalar()
    if count >= user.max_endpoints:
        raise HTTPException(
            status_code=403,
            detail=f"Maximum {user.max_endpoints} endpoints allowed",
        )

    endpoint = Endpoint(
        user_id=user.id,
        name=body.name,
        url=body.url,
        method=body.method,
        monitor_type=body.monitor_type,
        check_interval=body.check_interval,
        monitor_region=body.monitor_region,
    )
    db.add(endpoint)
    await db.commit()
    await db.refresh(endpoint)
    return endpoint


@router.get("/{endpoint_id}", response_model=EndpointResponse)
async def get_endpoint(
    endpoint_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Endpoint).where(Endpoint.id == endpoint_id, Endpoint.user_id == user.id)
    )
    endpoint = result.scalar_one_or_none()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return endpoint


@router.patch("/{endpoint_id}", response_model=EndpointResponse)
async def update_endpoint(
    endpoint_id: str,
    body: EndpointUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Endpoint).where(Endpoint.id == endpoint_id, Endpoint.user_id == user.id)
    )
    endpoint = result.scalar_one_or_none()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    if body.name is not None:
        endpoint.name = body.name
    if body.is_active is not None:
        endpoint.is_active = body.is_active
    if body.check_interval is not None:
        endpoint.check_interval = body.check_interval
    if body.monitor_region is not None:
        endpoint.monitor_region = body.monitor_region

    await db.commit()
    await db.refresh(endpoint)
    return endpoint


@router.delete("/{endpoint_id}")
async def delete_endpoint(
    endpoint_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Endpoint).where(Endpoint.id == endpoint_id, Endpoint.user_id == user.id)
    )
    endpoint = result.scalar_one_or_none()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    await db.delete(endpoint)
    await db.commit()
    return {"message": "Endpoint deleted"}


@router.get("/{endpoint_id}/checks", response_model=list[CheckResponse])
async def get_checks(
    endpoint_id: str,
    hours: int = Query(default=24, ge=1, le=168),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify ownership
    ep_result = await db.execute(
        select(Endpoint.id).where(Endpoint.id == endpoint_id, Endpoint.user_id == user.id)
    )
    if not ep_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Endpoint not found")

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await db.execute(
        select(EndpointCheck)
        .where(EndpointCheck.endpoint_id == endpoint_id, EndpointCheck.checked_at >= since)
        .order_by(EndpointCheck.checked_at.asc())
    )
    return result.scalars().all()


@router.get("/{endpoint_id}/incidents", response_model=list[IncidentResponse])
async def get_incidents(
    endpoint_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify ownership
    ep_result = await db.execute(
        select(Endpoint.id).where(Endpoint.id == endpoint_id, Endpoint.user_id == user.id)
    )
    if not ep_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Endpoint not found")

    result = await db.execute(
        select(Incident)
        .where(Incident.endpoint_id == endpoint_id)
        .order_by(Incident.started_at.desc())
    )
    return result.scalars().all()


# --- User Metrics ---

class UserMetrics(BaseModel):
    total_endpoints: int
    active_endpoints: int
    total_checks: int
    total_up: int
    total_down: int
    uptime_percentage: float
    avg_response_ms: float
    total_incidents: int
    open_incidents: int


@router.get("/stats/overview", response_model=UserMetrics)
async def get_user_metrics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    # Endpoint counts
    total_ep = (await db.execute(
        select(func.count()).where(Endpoint.user_id == user.id)
    )).scalar() or 0

    active_ep = (await db.execute(
        select(func.count()).where(Endpoint.user_id == user.id, Endpoint.is_active == True)
    )).scalar() or 0

    # Get user's endpoint IDs
    ep_ids_result = await db.execute(
        select(Endpoint.id).where(Endpoint.user_id == user.id)
    )
    ep_ids = [str(r) for r in ep_ids_result.scalars().all()]

    if not ep_ids:
        return UserMetrics(
            total_endpoints=0, active_endpoints=0, total_checks=0,
            total_up=0, total_down=0, uptime_percentage=0,
            avg_response_ms=0, total_incidents=0, open_incidents=0,
        )

    # Check counts
    total_checks = (await db.execute(
        select(func.count()).where(
            EndpointCheck.endpoint_id.in_(ep_ids),
            EndpointCheck.checked_at >= since,
        )
    )).scalar() or 0

    total_up = (await db.execute(
        select(func.count()).where(
            EndpointCheck.endpoint_id.in_(ep_ids),
            EndpointCheck.checked_at >= since,
            EndpointCheck.is_up == True,
        )
    )).scalar() or 0

    total_down = total_checks - total_up

    uptime_pct = (total_up / total_checks * 100) if total_checks > 0 else 0

    avg_resp = (await db.execute(
        select(func.avg(EndpointCheck.response_time_ms)).where(
            EndpointCheck.endpoint_id.in_(ep_ids),
            EndpointCheck.checked_at >= since,
            EndpointCheck.response_time_ms.isnot(None),
        )
    )).scalar() or 0

    # Incidents
    total_incidents = (await db.execute(
        select(func.count()).where(Incident.user_id == user.id)
    )).scalar() or 0

    open_incidents = (await db.execute(
        select(func.count()).where(
            Incident.user_id == user.id,
            Incident.is_resolved == False,
        )
    )).scalar() or 0

    return UserMetrics(
        total_endpoints=total_ep,
        active_endpoints=active_ep,
        total_checks=total_checks,
        total_up=total_up,
        total_down=total_down,
        uptime_percentage=round(uptime_pct, 1),
        avg_response_ms=round(float(avg_resp), 1),
        total_incidents=total_incidents,
        open_incidents=open_incidents,
    )
