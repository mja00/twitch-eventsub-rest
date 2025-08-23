import logging
from fastapi import APIRouter, HTTPException, Depends

from app.auth import verify_api_key
from app.streamers import StreamerManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/streamers")

# Use a new instance - should be refactored to use dependency injection
streamer_manager = StreamerManager()


@router.get("")
async def get_streamers(api_key_valid: bool = Depends(verify_api_key)):
    """Get list of configured streamers"""
    return await streamer_manager.get_streamers()


@router.post("/{username}")
async def add_streamer(username: str, api_key_valid: bool = Depends(verify_api_key)):
    """Add a streamer to monitor"""
    try:
        await streamer_manager.add_streamer(username)
        return {"message": f"Added streamer: {username}"}
    except Exception as e:
        logger.error(f"Error adding streamer {username}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{username}")
async def remove_streamer(username: str, api_key_valid: bool = Depends(verify_api_key)):
    """Remove a streamer from monitoring"""
    try:
        await streamer_manager.remove_streamer(username)
        return {"message": f"Removed streamer: {username}"}
    except Exception as e:
        logger.error(f"Error removing streamer {username}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{username}/status")
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
