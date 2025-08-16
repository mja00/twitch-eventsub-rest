from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
import logging
from contextlib import asynccontextmanager

from app.config import settings
from app.storage import get_storage
from app.models import EventSubNotification, EventSubChallenge
from app.eventsub import verify_signature
from app.streamers import StreamerManager
from app.auth import verify_api_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

streamer_manager = StreamerManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting up Twitch EventSub server...")
    storage = get_storage()
    await storage.connect()

    # Initialize streamers and subscriptions
    await streamer_manager.initialize()

    yield

    logger.info("Shutting down...")
    await streamer_manager.shutdown()
    await storage.disconnect()

app = FastAPI(
    title="Twitch EventSub REST API",
    description="A REST API server for listening to Twitch EventSub events",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    return {"message": "Twitch EventSub REST API"}


@app.get("/health")
async def health_check():
    storage = get_storage()
    storage_status = await storage.health_check()
    return {
        "status": "healthy" if storage_status else "unhealthy",
        "storage": "connected" if storage_status else "disconnected"
    }


@app.post("/webhooks/eventsub")
async def eventsub_webhook(request: Request):
    """Handle Twitch EventSub webhook notifications"""
    try:
        headers = request.headers
        body = await request.body()

        # Verify the signature
        if not verify_signature(headers, body, settings.WEBHOOK_SECRET):
            raise HTTPException(status_code=403, detail="Invalid signature")

        # Parse the JSON payload
        payload = await request.json()

        # Handle challenge verification
        if "challenge" in payload:
            challenge = EventSubChallenge(**payload)
            logger.info(f"Received EventSub challenge: {challenge.challenge}")
            return JSONResponse(
                content=challenge.challenge,
                media_type="text/plain"
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
async def get_recent_events(limit: int = 50, api_key_valid: bool = Depends(verify_api_key)):
    """Get recent stream events"""
    storage = get_storage()
    events = await storage.get_recent_events(limit)
    return {"events": events}


@app.get("/streamers/{username}/status")
async def get_streamer_status(username: str, api_key_valid: bool = Depends(verify_api_key)):
    """Get current stream status for a streamer"""
    try:
        status = await streamer_manager.get_stream_status(username)
        if not status:
            raise HTTPException(status_code=404, detail=f"Streamer {username} not found")
        return status
    except Exception as e:
        logger.error(f"Error getting status for {username}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/streams/live")
async def get_live_streams(api_key_valid: bool = Depends(verify_api_key)):
    """Get all currently live streams"""
    try:
        live_streams = await streamer_manager.get_live_streams()
        return {
            "live_streams": live_streams,
            "count": len(live_streams)
        }
    except Exception as e:
        logger.error(f"Error getting live streams: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
