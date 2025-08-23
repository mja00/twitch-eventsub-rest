from fastapi import FastAPI, Request
import logging
import asyncio
from typing import Optional
from contextlib import asynccontextmanager
import time

from app.storage import get_storage
from app.streamers import StreamerManager
from app.analytics import analytics_service

# Import route modules
from app.routes import basic, webhooks, streamers, events, streams, admin, analytics

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set HTTPX to ERROR level only to reduce verbosity
logging.getLogger("httpx").setLevel(logging.ERROR)

# Disable uvicorn access logging since we have our own middleware
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

streamer_manager = StreamerManager()
_initialization_task: Optional[asyncio.Task] = None


def get_real_ip(request: Request) -> str:
    """Extract the real client IP from request headers"""
    # Check Cloudflare header first (most specific)
    cf_connecting_ip = request.headers.get("CF-Connecting-IP")
    if cf_connecting_ip:
        return cf_connecting_ip

    # Check X-Forwarded-For header (standard proxy header)
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        # X-Forwarded-For can contain multiple IPs, take the first one (original client)
        return x_forwarded_for.split(",")[0].strip()

    # Check X-Real-IP header (Nginx)
    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip

    # Fall back to direct client IP
    if request.client:
        return request.client.host

    return "unknown"


async def _initialize_in_background():
    """Initialize streamers in background to avoid blocking startup"""
    try:
        logger.info("Starting background initialization...")
        await streamer_manager.initialize()
        logger.info("Background initialization complete")
    except Exception as e:
        logger.error(f"Error during background initialization: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global _initialization_task

    logger.info("Starting up Twitch EventSub server...")
    storage = get_storage()
    await storage.connect()

    # Connect analytics service
    await analytics_service.connect()

    # Start initialization in background so webhook can respond immediately
    _initialization_task = asyncio.create_task(_initialize_in_background())

    yield

    logger.info("Shutting down...")
    if _initialization_task and not _initialization_task.done():
        _initialization_task.cancel()
        try:
            await _initialization_task
        except asyncio.CancelledError:
            pass

    await streamer_manager.shutdown()
    await analytics_service.disconnect()
    await storage.disconnect()


app = FastAPI(
    title="Twitch EventSub REST API",
    description="A REST API server for listening to Twitch EventSub events",
    version="1.0.0",
    lifespan=lifespan,
)

# Include all route modules
app.include_router(basic.router)
app.include_router(webhooks.router)
app.include_router(streamers.router)
app.include_router(events.router)
app.include_router(streams.router)
app.include_router(admin.router)
app.include_router(analytics.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log requests with real IP addresses"""
    client_ip = get_real_ip(request)
    start_time = time.time()

    # Call the endpoint
    response = await call_next(request)

    # Log the request
    process_time_ms = (time.time() - start_time) * 1000
    logger.info(
        f'{client_ip} - "{request.method} {request.url.path}" '
        f"{response.status_code} - {process_time_ms:.1f}ms"
    )

    return response


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)
