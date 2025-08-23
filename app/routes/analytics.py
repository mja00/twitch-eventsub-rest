import logging
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
        logger.error(f"Error getting analytics summary: {str(e)}")
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
    except Exception as e:
        logger.error(f"Error getting streamer stats for {broadcaster_login}: {str(e)}")
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
        logger.error(f"Error getting stream sessions for {broadcaster_login}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/top-streamers/hours")
async def get_top_streamers_by_hours(limit: int = Query(10, ge=1, le=50)):
    """Get top streamers by total hours streamed"""
    try:
        streamers = await analytics_service.get_top_streamers_by_hours(limit)
        return {"top_streamers": streamers, "count": len(streamers)}
    except Exception as e:
        logger.error(f"Error getting top streamers: {str(e)}")
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
        logger.error(f"Error getting snapshots: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
