import logging
import traceback
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.analytics import analytics_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics")


@router.get("/summary")
async def get_analytics_summary():
    """Get overall analytics summary"""
    try:
        summary = await analytics_service.get_analytics_summary()
        return summary
    except Exception as e:
        logger.error(f"Error getting analytics summary: {type(e).__name__}: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/streamer/{broadcaster_login}/stats")
async def get_streamer_stats(broadcaster_login: str):
    """Get statistics for a specific streamer"""
    try:
        stats = await analytics_service.get_streamer_stats(broadcaster_login)
        if not stats:
            raise HTTPException(
                status_code=404,
                detail=f"No analytics data found for {broadcaster_login}",
            )
        return stats
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        logger.error(
            f"Error getting streamer stats for {broadcaster_login}: {type(e).__name__}: {str(e)}"
        )
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/streamer/{broadcaster_login}/sessions")
async def get_stream_sessions(
    broadcaster_login: str, limit: int = Query(50, ge=1, le=500)
):
    """Get stream sessions for a broadcaster"""
    try:
        sessions = await analytics_service.get_stream_sessions(broadcaster_login, limit)
        return {
            "broadcaster_login": broadcaster_login,
            "sessions": sessions,
            "count": len(sessions),
        }
    except Exception as e:
        logger.error(
            f"Error getting stream sessions for {broadcaster_login}: {type(e).__name__}: {str(e)}"
        )
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/top-streamers/hours")
async def get_top_streamers_by_hours(limit: int = Query(10, ge=1, le=50)):
    """Get top streamers by total hours streamed"""
    try:
        streamers = await analytics_service.get_top_streamers_by_hours(limit)
        return {"top_streamers": streamers, "count": len(streamers)}
    except Exception as e:
        logger.error(f"Error getting top streamers: {type(e).__name__}: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/snapshots")
async def get_recent_snapshots(
    broadcaster_login: Optional[str] = None, limit: int = Query(100, ge=1, le=1000)
):
    """Get recent stream snapshots"""
    try:
        snapshots = await analytics_service.get_recent_snapshots(
            broadcaster_login, limit
        )
        return {
            "snapshots": snapshots,
            "count": len(snapshots),
            "broadcaster_login": broadcaster_login,
        }
    except Exception as e:
        logger.error(f"Error getting snapshots: {type(e).__name__}: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/streamer/{broadcaster_login}/recalculate")
async def recalculate_streamer_stats(broadcaster_login: str):
    """Force recalculation of statistics for a specific streamer"""
    try:
        # First, get the streamer stats to find broadcaster_id
        existing_stats = await analytics_service.get_streamer_stats(broadcaster_login)
        if not existing_stats:
            raise HTTPException(
                status_code=404,
                detail=f"No analytics data found for {broadcaster_login}",
            )

        broadcaster_id = existing_stats["broadcaster_id"]
        success = await analytics_service.recalculate_streamer_stats(broadcaster_id)

        if not success:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to recalculate stats for {broadcaster_login}",
            )

        # Return the updated stats
        updated_stats = await analytics_service.get_streamer_stats(broadcaster_login)
        return {
            "message": f"Successfully recalculated stats for {broadcaster_login}",
            "stats": updated_stats,
        }
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        logger.error(
            f"Error recalculating stats for {broadcaster_login}: {type(e).__name__}: {str(e)}"
        )
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")
