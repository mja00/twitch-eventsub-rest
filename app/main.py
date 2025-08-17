from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import Response
import logging
import asyncio
from typing import Optional
from contextlib import asynccontextmanager
import time

from app.config import settings
from app.storage import get_storage
from app.models import EventSubNotification, EventSubChallenge
from app.eventsub import verify_signature
from app.streamers import StreamerManager
from app.auth import verify_api_key

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
    await storage.disconnect()


app = FastAPI(
    title="Twitch EventSub REST API",
    description="A REST API server for listening to Twitch EventSub events",
    version="1.0.0",
    lifespan=lifespan,
)


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


@app.get("/")
async def root():
    return {"message": "Twitch EventSub REST API"}


@app.get("/health")
async def health_check():
    storage = get_storage()
    storage_status = await storage.health_check()
    return {
        "status": "healthy" if storage_status else "unhealthy",
        "storage": "connected" if storage_status else "disconnected",
    }


@app.post("/webhooks/eventsub")
async def eventsub_webhook(request: Request):
    """Handle Twitch EventSub webhook notifications"""
    try:
        headers = request.headers
        body = await request.body()
        client_ip = get_real_ip(request)

        logger.debug(f"Received webhook request from {client_ip}: {headers}")

        # Verify the signature
        if not verify_signature(headers, body, settings.WEBHOOK_SECRET):
            logger.warning(f"Invalid webhook signature from {client_ip}")
            raise HTTPException(status_code=403, detail="Invalid signature")

        # Parse the JSON payload
        payload = await request.json()
        logger.debug(f"Received webhook payload: {payload}")

        # Handle challenge verification
        if "challenge" in payload:
            challenge = EventSubChallenge(**payload)
            logger.info(
                f"Received EventSub challenge from {client_ip}: {challenge.challenge}"
            )

            # Return raw challenge
            challenge_value = challenge.challenge
            return Response(
                content=challenge_value,
                status_code=200,
                headers={"Content-Type": "text/plain"},
            )

        # Handle notification
        notification = EventSubNotification(**payload)

        # Process the event
        await streamer_manager.handle_event(notification)

        logger.info(f"Processed event: {notification.subscription.type}")
        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/streamers")
async def get_streamers(api_key_valid: bool = Depends(verify_api_key)):
    """Get list of configured streamers"""
    return await streamer_manager.get_streamers()


@app.post("/streamers/{username}")
async def add_streamer(username: str, api_key_valid: bool = Depends(verify_api_key)):
    """Add a streamer to monitor"""
    try:
        await streamer_manager.add_streamer(username)
        return {"message": f"Added streamer: {username}"}
    except Exception as e:
        logger.error(f"Error adding streamer {username}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/streamers/{username}")
async def remove_streamer(username: str, api_key_valid: bool = Depends(verify_api_key)):
    """Remove a streamer from monitoring"""
    try:
        await streamer_manager.remove_streamer(username)
        return {"message": f"Removed streamer: {username}"}
    except Exception as e:
        logger.error(f"Error removing streamer {username}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/events")
async def get_recent_events(limit: int = 50):
    """Get recent stream events"""
    storage = get_storage()
    events = await storage.get_recent_events(limit)
    return {"events": events}


@app.get("/streamers/{username}/status")
async def get_streamer_status(username: str):
    """Get current stream status for a streamer"""
    try:
        status = await streamer_manager.get_stream_status(username)
        if not status:
            raise HTTPException(
                status_code=404, detail=f"Streamer {username} not found"
            )
        return status
    except Exception as e:
        logger.error(f"Error getting status for {username}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/streams/live")
async def get_live_streams():
    """Get all currently live streams"""
    try:
        live_streams = await streamer_manager.get_live_streams()
        return {"live_streams": live_streams, "count": len(live_streams)}
    except Exception as e:
        logger.error(f"Error getting live streams: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/admin/cleanup-subscriptions")
async def cleanup_subscriptions(api_key_valid: bool = Depends(verify_api_key)):
    """Manually cleanup EventSub subscriptions for our webhook URL"""
    try:
        from app.twitch_api import TwitchAPI

        twitch_api = TwitchAPI()
        cleanup_count = await twitch_api.cleanup_webhook_subscriptions()
        return {
            "message": f"Cleaned up {cleanup_count} EventSub subscriptions",
            "cleanup_count": cleanup_count,
        }
    except Exception as e:
        logger.error(f"Error during subscription cleanup: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/admin/subscriptions")
async def get_current_subscriptions(api_key_valid: bool = Depends(verify_api_key)):
    """Get all current EventSub subscriptions"""
    try:
        from app.twitch_api import TwitchAPI

        twitch_api = TwitchAPI()
        subscriptions = await twitch_api.get_eventsub_subscriptions()
        costs = await twitch_api.get_eventsub_costs()

        # Filter to show only our webhook subscriptions and add details
        our_subscriptions = []
        other_subscriptions = []
        for sub in subscriptions:
            if sub.get("transport", {}).get("callback") == settings.WEBHOOK_URL:
                our_subscriptions.append(
                    {
                        "id": sub.get("id"),
                        "type": sub.get("type"),
                        "status": sub.get("status"),
                        "condition": sub.get("condition"),
                        "created_at": sub.get("created_at"),
                        "cost": sub.get("cost", 0),
                    }
                )
            else:
                other_subscriptions.append(
                    {
                        "id": sub.get("id"),
                        "type": sub.get("type"),
                        "status": sub.get("status"),
                        "condition": sub.get("condition"),
                        "created_at": sub.get("created_at"),
                        "cost": sub.get("cost", 0),
                    }
                )

        return {
            "subscriptions": our_subscriptions,
            "other_subscriptions": other_subscriptions,
            "total_subscriptions": len(subscriptions),
            "our_subscriptions_count": len(our_subscriptions),
            "other_subscriptions_count": len(other_subscriptions),
            "webhook_url": settings.WEBHOOK_URL,
            "costs": costs,
        }
    except Exception as e:
        logger.error(f"Error getting subscriptions: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/admin/verify-subscriptions")
async def verify_all_subscriptions(api_key_valid: bool = Depends(verify_api_key)):
    """Re-verify and fix EventSub subscriptions for all tracked streamers"""
    try:
        await streamer_manager.validate_and_fix_subscriptions()
        return {"message": "Subscription verification completed", "status": "success"}
    except Exception as e:
        logger.error(f"Error during subscription verification: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/admin/delete-all-subscriptions")
async def delete_all_subscriptions(api_key_valid: bool = Depends(verify_api_key)):
    """Delete ALL EventSub subscriptions (WARNING: affects all callback URLs)"""
    try:
        from app.twitch_api import TwitchAPI

        twitch_api = TwitchAPI()
        deleted_count = await twitch_api.delete_all_subscriptions()
        return {
            "message": f"Deleted {deleted_count} total EventSub subscriptions",
            "deleted_count": deleted_count,
            "warning": "This action deleted ALL subscriptions, not just our webhook URL",
        }
    except Exception as e:
        logger.error(f"Error during all subscriptions deletion: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)
