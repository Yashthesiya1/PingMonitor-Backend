import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.workers.celery_app import celery
from app.database import async_session
from app.models.check import EndpointCheck


@celery.task(name="app.workers.cleanup_worker.cleanup_old_checks")
def cleanup_old_checks():
    """Delete endpoint checks older than 24 hours for free tier users."""
    async def _cleanup():
        async with async_session() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

            result = await db.execute(
                delete(EndpointCheck).where(EndpointCheck.checked_at < cutoff)
            )
            await db.commit()

            return {"deleted": result.rowcount}

    return asyncio.run(_cleanup())
