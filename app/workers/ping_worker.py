import asyncio
import httpx
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.workers.celery_app import celery
from app.database import async_session
from app.models.endpoint import Endpoint
from app.models.check import EndpointCheck
from app.models.incident import Incident


async def _ping_endpoint(endpoint: Endpoint, db: AsyncSession) -> dict:
    """Ping a single endpoint and store the result."""
    start = datetime.now(timezone.utc)
    status_code = None
    response_time_ms = None
    is_up = False
    error_message = None
    status_indicator = None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if endpoint.monitor_type == "status":
                resp = await client.get(endpoint.url, headers={
                    "User-Agent": "PingMonitor/1.0",
                    "Accept": "application/json",
                })
                status_code = resp.status_code
                response_time_ms = int(resp.elapsed.total_seconds() * 1000)

                try:
                    data = resp.json()
                    # Atlassian Statuspage format
                    if isinstance(data, dict) and "status" in data:
                        indicator = data["status"].get("indicator", "unknown")
                        status_indicator = indicator
                        is_up = indicator in ("none", "operational")
                        if not is_up:
                            error_message = data["status"].get("description", indicator)
                    # Google Cloud format (array of incidents)
                    elif isinstance(data, list):
                        is_up = len(data) == 0
                        status_indicator = "none" if is_up else "major"
                    else:
                        is_up = resp.status_code < 400
                except Exception:
                    is_up = resp.status_code < 400
            else:
                resp = await client.request(
                    endpoint.method or "GET",
                    endpoint.url,
                    headers={"User-Agent": "PingMonitor/1.0"},
                )
                status_code = resp.status_code
                response_time_ms = int(resp.elapsed.total_seconds() * 1000)
                is_up = 200 <= resp.status_code < 400

    except httpx.TimeoutException:
        response_time_ms = 15000
        error_message = "Timeout after 15 seconds"
    except Exception as e:
        error_message = str(e)[:500]

    # Store check
    check = EndpointCheck(
        endpoint_id=endpoint.id,
        status_code=status_code,
        response_time_ms=response_time_ms,
        is_up=is_up,
        error_message=error_message,
        status_indicator=status_indicator,
    )
    db.add(check)

    # Incident detection
    if not is_up:
        result = await db.execute(
            select(Incident).where(
                Incident.endpoint_id == endpoint.id,
                Incident.is_resolved == False,
            ).order_by(Incident.started_at.desc()).limit(1)
        )
        open_incident = result.scalar_one_or_none()

        if open_incident:
            open_incident.consecutive_failures += 1
        else:
            incident = Incident(
                endpoint_id=endpoint.id,
                user_id=endpoint.user_id,
                cause=error_message or f"HTTP {status_code}",
                consecutive_failures=1,
            )
            db.add(incident)
    else:
        result = await db.execute(
            select(Incident).where(
                Incident.endpoint_id == endpoint.id,
                Incident.is_resolved == False,
            )
        )
        open_incident = result.scalar_one_or_none()
        if open_incident:
            now = datetime.now(timezone.utc)
            open_incident.is_resolved = True
            open_incident.resolved_at = now
            open_incident.duration_seconds = int(
                (now - open_incident.started_at).total_seconds()
            )

    await db.commit()

    return {
        "endpoint_id": str(endpoint.id),
        "is_up": is_up,
        "response_time_ms": response_time_ms,
    }


async def _ping_all():
    """Ping all active endpoints."""
    async with async_session() as db:
        result = await db.execute(
            select(Endpoint).where(Endpoint.is_active == True)
        )
        endpoints = result.scalars().all()

        if not endpoints:
            return {"checked": 0, "total": 0}

        results = []
        for endpoint in endpoints:
            try:
                r = await _ping_endpoint(endpoint, db)
                results.append(r)
            except Exception:
                pass

        return {"checked": len(results), "total": len(endpoints)}


@celery.task(name="app.workers.ping_worker.ping_all_endpoints")
def ping_all_endpoints():
    """Celery task to ping all active endpoints."""
    return asyncio.run(_ping_all())


@celery.task(name="app.workers.ping_worker.ping_single_endpoint")
def ping_single_endpoint(endpoint_id: str):
    """Celery task to ping a single endpoint."""
    async def _ping_single():
        async with async_session() as db:
            result = await db.execute(
                select(Endpoint).where(Endpoint.id == endpoint_id)
            )
            endpoint = result.scalar_one_or_none()
            if endpoint:
                return await _ping_endpoint(endpoint, db)
            return None

    return asyncio.run(_ping_single())
