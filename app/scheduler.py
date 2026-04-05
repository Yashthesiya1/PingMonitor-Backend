"""
Background scheduler that pings all active endpoints every minute.
Uses asyncio — no Redis or Celery required.
Runs as part of the FastAPI app lifespan.
"""
import asyncio
import httpx
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.endpoint import Endpoint
from app.models.check import EndpointCheck
from app.models.incident import Incident
from app.services.notification_dispatcher import dispatch_incident_notifications


async def _ping_endpoint(endpoint, db: AsyncSession) -> None:
    """Ping a single endpoint and store the result + handle incidents."""
    start = datetime.now(timezone.utc)
    status_code = None
    response_time_ms = None
    is_up = False
    error_message = None
    status_indicator = None

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            if endpoint.monitor_type == "status":
                resp = await client.get(
                    endpoint.url,
                    headers={
                        "User-Agent": "PingMonitor/1.0",
                        "Accept": "application/json",
                    },
                )
                status_code = resp.status_code
                response_time_ms = int(resp.elapsed.total_seconds() * 1000)

                try:
                    data = resp.json()
                    if isinstance(data, dict) and "status" in data:
                        indicator = data["status"].get("indicator", "unknown")
                        status_indicator = indicator
                        is_up = indicator in ("none", "operational")
                        if not is_up:
                            error_message = data["status"].get("description", indicator)
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

    # Store check result
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
            select(Incident)
            .where(Incident.endpoint_id == endpoint.id, Incident.is_resolved == False)
            .order_by(Incident.started_at.desc())
            .limit(1)
        )
        open_incident = result.scalar_one_or_none()

        if open_incident:
            open_incident.consecutive_failures += 1
        else:
            # New incident — create and dispatch notifications
            incident = Incident(
                endpoint_id=endpoint.id,
                user_id=endpoint.user_id,
                cause=error_message or f"HTTP {status_code}",
                consecutive_failures=1,
            )
            db.add(incident)
            await db.flush()  # Get the incident ID

            # Dispatch DOWN notifications to user's channels
            try:
                await dispatch_incident_notifications(
                    db=db,
                    user_id=str(endpoint.user_id),
                    endpoint_id=str(endpoint.id),
                    incident_id=str(incident.id),
                    event_type="endpoint_down",
                    cause=error_message or f"HTTP {status_code}",
                )
            except Exception as e:
                print(f"[Scheduler] Failed to dispatch DOWN notifications: {e}")
    else:
        # Endpoint is up — resolve any open incident
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

            # Dispatch RECOVERY notifications to user's channels
            try:
                await dispatch_incident_notifications(
                    db=db,
                    user_id=str(endpoint.user_id),
                    endpoint_id=str(endpoint.id),
                    incident_id=str(open_incident.id),
                    event_type="endpoint_recovered",
                    duration_seconds=open_incident.duration_seconds,
                )
            except Exception as e:
                print(f"[Scheduler] Failed to dispatch RECOVERY notifications: {e}")


async def ping_all_endpoints() -> dict:
    """Ping every active endpoint that is due for a check."""
    async with async_session() as db:
        now = datetime.now(timezone.utc)

        # Get all active endpoints
        result = await db.execute(select(Endpoint).where(Endpoint.is_active == True))
        endpoints = result.scalars().all()

        if not endpoints:
            return {"checked": 0, "skipped": 0}

        # Filter endpoints that are due (based on their check_interval)
        due_endpoints = []
        for ep in endpoints:
            # Check the last check time for this endpoint
            last_check_result = await db.execute(
                select(EndpointCheck)
                .where(EndpointCheck.endpoint_id == ep.id)
                .order_by(EndpointCheck.checked_at.desc())
                .limit(1)
            )
            last_check = last_check_result.scalar_one_or_none()

            if last_check is None:
                # Never checked — ping it now
                due_endpoints.append(ep)
            else:
                # Calculate time since last check
                elapsed = (now - last_check.checked_at).total_seconds()
                interval_seconds = ep.check_interval * 60
                # Allow 10 second buffer
                if elapsed >= (interval_seconds - 10):
                    due_endpoints.append(ep)

        if not due_endpoints:
            return {"checked": 0, "skipped": len(endpoints)}

        # Ping all due endpoints concurrently
        tasks = [_ping_endpoint(ep, db) for ep in due_endpoints]
        await asyncio.gather(*tasks, return_exceptions=True)

        await db.commit()
        return {"checked": len(due_endpoints), "skipped": len(endpoints) - len(due_endpoints)}


async def scheduler_loop():
    """Main scheduler loop — runs forever, checks endpoints every 30 seconds."""
    # Wait 5 seconds before first run (let app fully start)
    await asyncio.sleep(5)

    while True:
        try:
            result = await ping_all_endpoints()
            if result["checked"] > 0:
                print(f"[Scheduler] Checked {result['checked']} endpoints, skipped {result['skipped']}")
        except Exception as e:
            print(f"[Scheduler] Error: {e}")

        # Sleep 30 seconds — then check again which endpoints are due
        await asyncio.sleep(30)
