import logging
import traceback
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.analytics import analytics_service
from app.streamers import StreamerManager

# Get the global streamer manager instance
streamer_manager = StreamerManager()

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


@router.get("/comprehensive-summary")
async def get_comprehensive_summary():
    """Get comprehensive analytics summary including configured streamers"""
    try:
        summary = await analytics_service.get_comprehensive_summary()
        return summary
    except Exception as e:
        logger.error(f"Error getting comprehensive summary: {type(e).__name__}: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/eventsub-diagnostics")
async def get_eventsub_diagnostics():
    """Get diagnostics about EventSub subscription status"""
    try:
        diagnostics = await streamer_manager.get_eventsub_diagnostics()
        return diagnostics
    except Exception as e:
        logger.error(f"Error getting EventSub diagnostics: {type(e).__name__}: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/missing-offline-events")
async def detect_missing_offline_events():
    """Detect streams that have active sessions but are no longer live (missing offline events)"""
    try:
        result = await analytics_service.detect_missing_offline_events()
        return result
    except Exception as e:
        logger.error(f"Error detecting missing offline events: {type(e).__name__}: {str(e)}")
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


@router.post("/cleanup-sessions")
async def cleanup_sessions(max_age_hours: int = 24):
    """Clean up old active sessions and create stats for active sessions"""
    try:
        # Delete old active sessions
        deleted_count = await analytics_service.end_old_active_sessions(max_age_hours)

        # Create stats for active sessions that don't have them
        stats_created = await analytics_service.create_stats_for_active_sessions()

        return {
            "message": f"Cleanup completed: deleted {deleted_count} old sessions, created {stats_created} new stats",
            "sessions_deleted": deleted_count,
            "stats_created": stats_created,
        }
    except Exception as e:
        logger.error(f"Error during cleanup: {type(e).__name__}: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/fallback-detection")
async def trigger_fallback_detection():
    """Manually trigger fallback detection for very old active sessions (>2 hours)"""
    try:
        deleted_count = await analytics_service.trigger_fallback_detection()

        return {
            "message": f"Fallback detection completed: deleted {deleted_count} very old sessions",
            "sessions_deleted": deleted_count,
        }
    except Exception as e:
        logger.error(f"Error during fallback detection: {type(e).__name__}: {str(e)}")
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
