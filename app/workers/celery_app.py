from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery = Celery(
    "pingmonitor",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.workers.ping_worker",
        "app.workers.notification_worker",
        "app.workers.cleanup_worker",
    ],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Beat schedule
celery.conf.beat_schedule = {
    "ping-all-endpoints": {
        "task": "app.workers.ping_worker.ping_all_endpoints",
        "schedule": 60.0,  # Every 60 seconds
    },
    "cleanup-old-checks": {
        "task": "app.workers.cleanup_worker.cleanup_old_checks",
        "schedule": crontab(hour=3, minute=0),  # Daily at 3 AM
    },
    "weekly-summary": {
        "task": "app.workers.notification_worker.send_weekly_summaries",
        "schedule": crontab(hour=9, minute=0, day_of_week=1),  # Monday 9 AM
    },
}
