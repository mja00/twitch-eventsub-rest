import logging
from fastapi import APIRouter, HTTPException

from app.streamers import StreamerManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/streams")

# Use a new instance - should be refactored to use dependency injection
streamer_manager = StreamerManager()


@router.get("/live")
async def get_live_streams():
    """Get all currently live streams"""
    try:
        live_streams = await streamer_manager.get_live_streams()
        return {"live_streams": live_streams, "count": len(live_streams)}
    except Exception as e:
        logger.error(f"Error getting live streams: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
