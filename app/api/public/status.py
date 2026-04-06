"""Public status page — no auth required."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.endpoint import Endpoint
from app.models.check import EndpointCheck
from app.models.incident import Incident
from app.models.status_page import StatusPage, StatusPageEndpoint

router = APIRouter(prefix="/public/status", tags=["Public Status"])


class PublicEndpointItem(BaseModel):
    name: str
    is_up: bool | None
    uptime_24h: float
    uptime_90d: float
    avg_response_ms: int | None
    bars: list[bool]  # True = up, False = down, for sparkline


class PublicStatusPageResponse(BaseModel):
    name: str
    description: str | None
    logo_url: str | None
    primary_color: str
    overall_status: str  # "operational", "degraded", "major_outage"
    overall_uptime: float
    endpoints: list[PublicEndpointItem]
    last_updated: datetime


@router.get("/{slug}", response_model=PublicStatusPageResponse)
async def get_public_status(slug: str, db: AsyncSession = Depends(get_db)):
    """Get public status page by slug (no auth needed)."""
    # Find status page
    result = await db.execute(
        select(StatusPage).where(StatusPage.slug == slug, StatusPage.is_public == True)
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Status page not found")

    # Get all endpoints for this page
    ep_links_result = await db.execute(
        select(StatusPageEndpoint)
        .where(StatusPageEndpoint.status_page_id == page.id)
        .order_by(StatusPageEndpoint.display_order)
    )
    ep_links = ep_links_result.scalars().all()

    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    since_90d = now - timedelta(days=90)

    items: list[PublicEndpointItem] = []
    total_up = 0
    total_checks = 0
    any_down = False

    for link in ep_links:
        ep_result = await db.execute(select(Endpoint).where(Endpoint.id == link.endpoint_id))
        endpoint = ep_result.scalar_one_or_none()
        if not endpoint:
            continue

        display_name = link.display_name or endpoint.name

        # Get latest check
        latest_result = await db.execute(
            select(EndpointCheck)
            .where(EndpointCheck.endpoint_id == endpoint.id)
            .order_by(desc(EndpointCheck.checked_at))
            .limit(1)
        )
        latest = latest_result.scalar_one_or_none()
        is_up = latest.is_up if latest else None
        if is_up is False:
            any_down = True

        # 24h uptime
        checks_24h_result = await db.execute(
            select(EndpointCheck).where(
                EndpointCheck.endpoint_id == endpoint.id,
                EndpointCheck.checked_at >= since_24h,
            )
        )
        checks_24h = checks_24h_result.scalars().all()
        up_24h = sum(1 for c in checks_24h if c.is_up)
        uptime_24h = (up_24h / len(checks_24h) * 100) if checks_24h else 100.0

        # 90d uptime (could be 0 if user just added endpoint)
        checks_90d_result = await db.execute(
            select(EndpointCheck).where(
                EndpointCheck.endpoint_id == endpoint.id,
                EndpointCheck.checked_at >= since_90d,
            )
        )
        checks_90d = checks_90d_result.scalars().all()
        up_90d = sum(1 for c in checks_90d if c.is_up)
        uptime_90d = (up_90d / len(checks_90d) * 100) if checks_90d else 100.0

        # Avg response last 24h
        resp_times = [c.response_time_ms for c in checks_24h if c.response_time_ms is not None]
        avg_response = int(sum(resp_times) / len(resp_times)) if resp_times else None

        # Sparkline — last 30 checks
        recent_result = await db.execute(
            select(EndpointCheck)
            .where(EndpointCheck.endpoint_id == endpoint.id)
            .order_by(desc(EndpointCheck.checked_at))
            .limit(30)
        )
        recent = list(reversed(recent_result.scalars().all()))
        bars = [c.is_up for c in recent]

        total_up += up_24h
        total_checks += len(checks_24h)

        items.append(PublicEndpointItem(
            name=display_name,
            is_up=is_up,
            uptime_24h=round(uptime_24h, 2),
            uptime_90d=round(uptime_90d, 2),
            avg_response_ms=avg_response,
            bars=bars,
        ))

    # Overall status
    overall_uptime = (total_up / total_checks * 100) if total_checks else 100.0
    if any_down:
        overall_status = "major_outage" if overall_uptime < 90 else "degraded"
    else:
        overall_status = "operational"

    return PublicStatusPageResponse(
        name=page.name,
        description=page.description,
        logo_url=page.logo_url,
        primary_color=page.primary_color,
        overall_status=overall_status,
        overall_uptime=round(overall_uptime, 2),
        endpoints=items,
        last_updated=now,
    )
