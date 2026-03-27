"""Create all tables and seed with initial data."""
import asyncio
from datetime import datetime, timezone, timedelta
from app.database import engine, Base, async_session
from app.models import *  # noqa
from app.utils.security import hash_password


async def main():
    # 1. Create all tables
    print("Creating tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created!")

    # 2. Seed data
    async with async_session() as db:
        from sqlalchemy import select

        # Check if admin already exists
        result = await db.execute(select(User).where(User.email == "admin@ping.yashai.me"))
        if result.scalar_one_or_none():
            print("Seed data already exists. Skipping.")
            await engine.dispose()
            return

        print("Seeding data...")

        # --- Admin User ---
        admin = User(
            email="admin@ping.yashai.me",
            password_hash=hash_password("Admin@2026"),
            name="Admin",
            role="admin",
            credits=9999,
            max_endpoints=100,
            is_verified=True,
        )
        db.add(admin)
        await db.flush()

        # --- Demo User ---
        demo_user = User(
            email="demo@ping.yashai.me",
            password_hash=hash_password("Demo@2026"),
            name="Demo User",
            role="user",
            credits=100,
            max_endpoints=7,
            is_verified=True,
        )
        db.add(demo_user)
        await db.flush()

        # --- Demo Endpoints ---
        endpoints_data = [
            {"name": "Supabase", "url": "https://supabase.com", "monitor_type": "http", "check_interval": 1},
            {"name": "GitHub", "url": "https://github.com", "monitor_type": "http", "check_interval": 5},
            {"name": "OpenAI Status", "url": "https://status.openai.com/api/v2/status.json", "monitor_type": "status", "check_interval": 5},
        ]

        created_endpoints = []
        for ep_data in endpoints_data:
            ep = Endpoint(
                user_id=demo_user.id,
                name=ep_data["name"],
                url=ep_data["url"],
                monitor_type=ep_data["monitor_type"],
                check_interval=ep_data["check_interval"],
            )
            db.add(ep)
            await db.flush()
            created_endpoints.append(ep)

        # --- Demo Checks (last 2 hours, every 5 min) ---
        now = datetime.now(timezone.utc)
        for ep in created_endpoints:
            for i in range(24):
                check_time = now - timedelta(minutes=i * 5)
                is_up = i != 5  # One failure for demo
                check = EndpointCheck(
                    endpoint_id=ep.id,
                    status_code=200 if is_up else 503,
                    response_time_ms=40 + (i * 2) if is_up else None,
                    is_up=is_up,
                    error_message=None if is_up else "Service Unavailable",
                    checked_at=check_time,
                )
                db.add(check)

        # --- Demo Incident (resolved) ---
        incident = Incident(
            endpoint_id=created_endpoints[0].id,
            user_id=demo_user.id,
            started_at=now - timedelta(hours=1, minutes=25),
            resolved_at=now - timedelta(hours=1, minutes=20),
            is_resolved=True,
            cause="HTTP 503",
            duration_seconds=300,
            consecutive_failures=1,
        )
        db.add(incident)

        # --- Demo Notification Channel ---
        channel = NotificationChannel(
            user_id=demo_user.id,
            channel_type="email",
            name="Email",
            config="{}",
        )
        db.add(channel)

        # --- Demo Notification Log ---
        await db.flush()
        log = NotificationLog(
            user_id=demo_user.id,
            endpoint_id=created_endpoints[0].id,
            incident_id=incident.id,
            channel_type="email",
            event_type="endpoint_down",
            status="sent",
        )
        db.add(log)

        await db.commit()
        print("Seed data created!")
        print()
        print("=== Login Credentials ===")
        print(f"Admin:  admin@ping.yashai.me / Admin@2026")
        print(f"Demo:   demo@ping.yashai.me / Demo@2026")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
