"""Create all database tables on the live PostgreSQL database."""
import asyncio
from app.database import engine, Base
from app.models import *  # noqa — import all models


async def main():
    print("Connecting to database...")
    async with engine.begin() as conn:
        print("Creating all tables...")
        await conn.run_sync(Base.metadata.create_all)
        print("Done! All tables created successfully.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
