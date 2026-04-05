import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine
from app.scheduler import scheduler_loop
from app.api.v1.auth import router as auth_router
from app.api.v1.endpoints import router as endpoints_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.admin import router as admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background scheduler (pings endpoints every minute)
    scheduler_task = asyncio.create_task(scheduler_loop())
    print(f"{settings.APP_NAME} API started — scheduler running")
    yield
    # Cleanup on shutdown
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()
    print(f"{settings.APP_NAME} API shut down")


app = FastAPI(
    title=f"{settings.APP_NAME} API",
    description="API for PingMonitor — Monitor APIs, websites, and AI services",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
    debug=True,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(auth_router, prefix="/api/v1")
app.include_router(endpoints_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}
