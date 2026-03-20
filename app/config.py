from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Database — SQLite for dev, PostgreSQL for production
    DATABASE_URL: str = "sqlite+aiosqlite:///./pingmonitor.db"

    # Redis (optional — not needed for dev)
    REDIS_URL: str = ""

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # App
    APP_NAME: str = "PingMonitor"
    APP_URL: str = "https://ping.yashai.me"
    API_URL: str = "http://localhost:8000"
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "https://ping.yashai.me"]

    # Email
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "PingMonitor <noreply@ping.yashai.me>"

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
