import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorDatabase,
    AsyncIOMotorCollection,
)
import pymongo
from bson import ObjectId

from app.config import settings
from app.analytics_models import StreamSession, StreamSnapshot, StreamerStats
from app.storage import get_storage

logger = logging.getLogger(__name__)


class AnalyticsService:
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None
        self.sessions: Optional[AsyncIOMotorCollection] = None
        self.snapshots: Optional[AsyncIOMotorCollection] = None
        self.stats: Optional[AsyncIOMotorCollection] = None

    async def connect(self, max_retries: int = 5, retry_delay: int = 2):
        """Initialize MongoDB connection with retry logic"""
        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Attempting MongoDB connection (attempt {attempt + 1}/{max_retries})"
                )
                # Log connection details (without exposing password)
                safe_url = (
                    settings.MONGODB_URL.replace(
                        settings.MONGODB_URL.split("@")[0].split("//")[1], "***:***"
                    )
                    if "@" in settings.MONGODB_URL
                    else settings.MONGODB_URL
                )
                logger.info(f"MongoDB URL: {safe_url}")
                logger.info(f"MongoDB Database: {settings.MONGODB_DATABASE}")

                self.client = AsyncIOMotorClient(
                    settings.MONGODB_URL,
                    serverSelectionTimeoutMS=5000,  # 5 second timeout
                )
                self.db = self.client[settings.MONGODB_DATABASE]

                # Test the connection
                await self.client.admin.command("ping")
                logger.info("MongoDB ping successful")

                # Test database access
                await self.db.list_collection_names()
                logger.info(
                    f"Successfully accessed database: {settings.MONGODB_DATABASE}"
                )

                self.sessions = self.db["stream_sessions"]
                self.snapshots = self.db["stream_snapshots"]
                self.stats = self.db["streamer_stats"]

                # Create indexes for better performance
                await self._create_indexes()

                logger.info("MongoDB analytics service connected successfully")
                return

            except Exception as e:
                logger.error(
                    f"MongoDB connection attempt {attempt + 1} failed: {type(e).__name__}: {e}"
                )
                if attempt == max_retries - 1:
                    logger.error(
                        f"Failed to connect to MongoDB after {max_retries} attempts"
                    )
                    raise
                else:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)

    async def disconnect(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()

    async def health_check(self) -> bool:
        """Check if MongoDB connection is healthy"""
        try:
            if self.client is None or self.db is None:
                return False
            await self.client.admin.command("ping")
            return True
        except Exception as e:
            logger.error(f"MongoDB health check failed: {e}")
            return False

    async def _create_indexes(self):
        """Create necessary indexes for collections"""
        try:
            # StreamSession indexes
            await self.sessions.create_index("broadcaster_id")
            await self.sessions.create_index("started_at")
            await self.sessions.create_index(
                [("broadcaster_id", 1), ("started_at", -1)]
            )

            # StreamSnapshot indexes
            await self.snapshots.create_index("broadcaster_id")
            await self.snapshots.create_index("captured_at")
            await self.snapshots.create_index(
                [("broadcaster_id", 1), ("captured_at", -1)]
            )

            # StreamerStats indexes
            await self.stats.create_index("broadcaster_id", unique=True)
            await self.stats.create_index("broadcaster_login")

        except Exception as e:
            logger.warning(f"Failed to create some indexes: {e}")

    async def start_stream_session(self, event_data: Dict[str, Any]) -> str:
        """Start a new stream session when stream goes online"""
        session = StreamSession(
            broadcaster_id=event_data["broadcaster_user_id"],
            broadcaster_login=event_data["broadcaster_user_login"],
            broadcaster_name=event_data["broadcaster_user_name"],
            started_at=datetime.fromisoformat(
                event_data["started_at"].replace("Z", "+00:00")
            ),
        )

        result = await self.sessions.insert_one(
            session.dict(by_alias=True, exclude_unset=True)
        )
        logger.info(f"Started stream session for {session.broadcaster_login}")
        return str(result.inserted_id)

    async def end_stream_session(self, broadcaster_id: str, ended_at: datetime = None):
        """End the current stream session when stream goes offline"""
        if ended_at is None:
            ended_at = datetime.now(timezone.utc)

        # Find the most recent active session
        session = await self.sessions.find_one(
            {"broadcaster_id": broadcaster_id, "ended_at": None},
            sort=[("started_at", -1)],
        )

        if not session:
            logger.warning(f"No active session found for broadcaster {broadcaster_id}")
            return

        # Calculate duration - handle timezone differences
        started_at = session["started_at"]
        if started_at.tzinfo is None and ended_at.tzinfo is not None:
            # Make both naive or both aware
            ended_at = ended_at.replace(tzinfo=None)
        elif started_at.tzinfo is not None and ended_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=None)

        duration_minutes = int((ended_at - started_at).total_seconds() / 60)

        # Calculate viewer stats from snapshots
        viewer_stats = await self._calculate_viewer_stats(str(session["_id"]), ended_at)

        # Update session
        update_data = {
            "ended_at": ended_at,
            "duration_minutes": duration_minutes,
            "updated_at": datetime.now(timezone.utc),
            **viewer_stats,
        }

        await self.sessions.update_one({"_id": session["_id"]}, {"$set": update_data})

        # Update streamer stats
        await self._update_streamer_stats(broadcaster_id)

        logger.info(
            f"Ended stream session for {session['broadcaster_login']} (duration: {duration_minutes}m)"
        )

    async def capture_stream_snapshot(self, stream_data: Dict[str, Any]):
        """Capture a snapshot of current stream data"""
        snapshot = StreamSnapshot(
            broadcaster_id=stream_data.get("user_id"),
            broadcaster_login=stream_data.get("user_login"),
            broadcaster_name=stream_data.get("user_name"),
            is_live=bool(stream_data.get("id")),  # Has stream ID if live
            stream_id=stream_data.get("id"),
            category_id=stream_data.get("game_id"),
            category_name=stream_data.get("game_name"),
            title=stream_data.get("title"),
            viewer_count=stream_data.get("viewer_count"),
            started_at=datetime.fromisoformat(
                stream_data["started_at"].replace("Z", "+00:00")
            )
            if stream_data.get("started_at")
            else None,
            language=stream_data.get("language"),
            thumbnail_url=stream_data.get("thumbnail_url"),
            tag_ids=stream_data.get("tag_ids", []),
        )

        await self.snapshots.insert_one(
            snapshot.dict(by_alias=True, exclude_unset=True)
        )

    async def _calculate_viewer_stats(self, session_id: str, ended_at: datetime = None) -> Dict[str, Any]:
        """Calculate viewer statistics for a session from snapshots taken during that session"""
        # Get the session details to find time range
        session = await self.sessions.find_one({"_id": ObjectId(session_id)})
        if not session:
            return {
                "max_viewers": None,
                "avg_viewers": None,
                "viewer_count_samples": [],
            }

        broadcaster_id = session["broadcaster_id"]
        started_at = session["started_at"]

        # Use provided ended_at or get from session or current time
        if ended_at is None:
            ended_at = session.get("ended_at", datetime.now(timezone.utc))

        # Handle timezone differences for MongoDB queries
        if started_at.tzinfo is None:
            # started_at is naive, convert ended_at to naive for comparison
            ended_at = ended_at.replace(tzinfo=None) if ended_at.tzinfo is not None else ended_at

        # Find snapshots within the session time range
        pipeline = [
            {
                "$match": {
                    "broadcaster_id": broadcaster_id,
                    "captured_at": {"$gte": started_at, "$lte": ended_at},
                    "is_live": True,
                    "viewer_count": {"$ne": None},
                }
            },
            {
                "$group": {
                    "_id": None,
                    "max_viewers": {"$max": "$viewer_count"},
                    "avg_viewers": {"$avg": "$viewer_count"},
                    "viewer_samples": {
                        "$push": {
                            "timestamp": "$captured_at",
                            "viewer_count": "$viewer_count",
                        }
                    },
                }
            },
        ]

        result = await self.snapshots.aggregate(pipeline).to_list(1)
        if result and result[0]["max_viewers"] is not None:
            data = result[0]
            return {
                "max_viewers": data.get("max_viewers"),
                "avg_viewers": round(data.get("avg_viewers", 0), 2),
                "viewer_count_samples": data.get("viewer_samples", []),
            }

        return {"max_viewers": None, "avg_viewers": None, "viewer_count_samples": []}

    async def _update_streamer_stats(self, broadcaster_id: str):
        """Update aggregated streamer statistics"""
        # Calculate stats from all sessions (completed only for duration stats)
        session_pipeline = [
            {"$match": {"broadcaster_id": broadcaster_id}},
            {
                "$group": {
                    "_id": None,
                    "total_streams": {
                        "$sum": {"$cond": [{"$ne": ["$ended_at", None]}, 1, 0]}
                    },
                    "total_minutes": {"$sum": {"$ifNull": ["$duration_minutes", 0]}},
                    "avg_duration": {"$avg": {"$ifNull": ["$duration_minutes", None]}},
                    "last_stream": {"$max": "$started_at"},
                    "first_stream": {"$min": "$started_at"},
                    "broadcaster_login": {"$first": "$broadcaster_login"},
                    "broadcaster_name": {"$first": "$broadcaster_name"},
                }
            },
        ]

        # Calculate viewer stats from snapshots directly
        viewer_pipeline = [
            {
                "$match": {
                    "broadcaster_id": broadcaster_id,
                    "is_live": True,
                    "viewer_count": {"$ne": None},
                }
            },
            {
                "$group": {
                    "_id": None,
                    "max_viewers": {"$max": "$viewer_count"},
                    "avg_viewers": {"$avg": "$viewer_count"},
                }
            },
        ]

        session_result = await self.sessions.aggregate(session_pipeline).to_list(1)
        viewer_result = await self.snapshots.aggregate(viewer_pipeline).to_list(1)

        if not session_result:
            return

        session_data = session_result[0]
        viewer_data = viewer_result[0] if viewer_result else {}

        stats = StreamerStats(
            broadcaster_id=broadcaster_id,
            broadcaster_login=session_data["broadcaster_login"],
            broadcaster_name=session_data["broadcaster_name"],
            total_streams=session_data["total_streams"],
            total_hours_streamed=round(session_data["total_minutes"] / 60, 2),
            avg_stream_duration_minutes=round(session_data["avg_duration"] or 0, 2),
            max_concurrent_viewers=viewer_data.get("max_viewers", 0) or 0,
            avg_viewers_all_time=round(viewer_data.get("avg_viewers", 0) or 0, 2),
            last_stream_at=session_data["last_stream"],
            first_seen_at=session_data["first_stream"],
        )

        await self.stats.update_one(
            {"broadcaster_id": broadcaster_id},
            {"$set": stats.dict(by_alias=True, exclude_unset=True, exclude={"id"})},
            upsert=True,
        )

    async def get_streamer_stats(
        self, broadcaster_login: str
    ) -> Optional[Dict[str, Any]]:
        """Get statistics for a specific streamer"""
        if self.stats is None:
            raise RuntimeError("Analytics service not connected to MongoDB")

        stats = await self.stats.find_one({"broadcaster_login": broadcaster_login})
        if stats:
            stats["_id"] = str(stats["_id"])
            return stats
        return None

    async def get_stream_sessions(
        self, broadcaster_login: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get stream sessions for a broadcaster"""
        if self.sessions is None:
            raise RuntimeError("Analytics service not connected to MongoDB")

        cursor = self.sessions.find(
            {"broadcaster_login": broadcaster_login},
            sort=[("started_at", -1)],
            limit=limit,
        )

        sessions = []
        async for session in cursor:
            session["_id"] = str(session["_id"])
            sessions.append(session)

        return sessions

    async def get_top_streamers_by_hours(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top streamers by total hours streamed"""
        if self.stats is None:
            raise RuntimeError("Analytics service not connected to MongoDB")

        cursor = self.stats.find({}, sort=[("total_hours_streamed", -1)], limit=limit)

        streamers = []
        async for streamer in cursor:
            streamer["_id"] = str(streamer["_id"])
            streamers.append(streamer)

        return streamers

    async def get_recent_snapshots(
        self, broadcaster_login: str = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get recent stream snapshots"""
        if self.snapshots is None:
            raise RuntimeError("Analytics service not connected to MongoDB")

        query = {}
        if broadcaster_login:
            query["broadcaster_login"] = broadcaster_login

        cursor = self.snapshots.find(query, sort=[("captured_at", -1)], limit=limit)

        snapshots = []
        async for snapshot in cursor:
            snapshot["_id"] = str(snapshot["_id"])
            snapshots.append(snapshot)

        return snapshots

    async def recalculate_streamer_stats(self, broadcaster_id: str) -> bool:
        """Force recalculation of streamer statistics"""
        try:
            await self._update_streamer_stats(broadcaster_id)
            logger.info(f"Recalculated stats for broadcaster {broadcaster_id}")
            return True
        except Exception as e:
            logger.error(
                f"Failed to recalculate stats for broadcaster {broadcaster_id}: {e}"
            )
            return False

    async def end_old_active_sessions(self, max_age_hours: int = 24) -> int:
        """Delete active sessions that are older than the specified age"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        # Find old active sessions
        old_sessions = await self.sessions.find(
            {"ended_at": None, "started_at": {"$lt": cutoff_time}}
        ).to_list(None)

        deleted_count = 0
        for session in old_sessions:
            try:
                # Delete the session directly instead of trying to end it properly
                result = await self.sessions.delete_one({"_id": session["_id"]})
                if result.deleted_count > 0:
                    deleted_count += 1
                    # Calculate age safely handling timezone differences
                    now = datetime.now(timezone.utc)
                    session_start = session['started_at']
                    if session_start.tzinfo is None:
                        now = now.replace(tzinfo=None)
                    age_hours = (now - session_start).total_seconds() / 3600
                    logger.info(f"Deleted old stuck session for {session['broadcaster_login']} (age: {age_hours:.1f}h)")
                else:
                    logger.warning(f"Failed to delete session for {session['broadcaster_login']}")
            except Exception as e:
                logger.error(f"Failed to delete session for {session['broadcaster_login']}: {e}")

        return deleted_count

    async def create_stats_for_active_sessions(self) -> int:
        """Create streamer stats for active sessions that don't have stats yet"""
        # Find active sessions where streamer doesn't have stats
        pipeline = [
            {
                "$match": {"ended_at": None}
            },
            {
                "$lookup": {
                    "from": "streamer_stats",
                    "localField": "broadcaster_id",
                    "foreignField": "broadcaster_id",
                    "as": "stats"
                }
            },
            {
                "$match": {"stats": {"$size": 0}}  # No stats record exists
            }
        ]

        active_sessions_without_stats = await self.sessions.aggregate(pipeline).to_list(None)

        stats_created = 0
        processed_streamers = set()

        for session in active_sessions_without_stats:
            broadcaster_id = session["broadcaster_id"]
            if broadcaster_id in processed_streamers:
                continue

            try:
                await self._update_streamer_stats(broadcaster_id)
                stats_created += 1
                processed_streamers.add(broadcaster_id)
                logger.info(f"Created stats for active session: {session['broadcaster_login']}")
            except Exception as e:
                logger.error(f"Failed to create stats for {session['broadcaster_login']}: {e}")

        return stats_created

    async def trigger_fallback_detection(self) -> int:
        """Manually trigger fallback detection for old active sessions"""
        # Find sessions that are very old (over 2 hours) and delete them
        # This is more aggressive than the background task's 10-minute threshold
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=2)

        old_sessions = await self.sessions.find(
            {"ended_at": None, "started_at": {"$lt": cutoff_time}}
        ).to_list(None)

        deleted_count = 0
        for session in old_sessions:
            try:
                # Delete the session directly instead of trying to end it properly
                result = await self.sessions.delete_one({"_id": session["_id"]})
                if result.deleted_count > 0:
                    deleted_count += 1
                    # Calculate age safely handling timezone differences
                    now = datetime.now(timezone.utc)
                    session_start = session['started_at']
                    if session_start.tzinfo is None:
                        now = now.replace(tzinfo=None)
                    age_hours = (now - session_start).total_seconds() / 3600
                    logger.info(
                        f"Fallback: Deleted very old stuck session for {session['broadcaster_login']} "
                        f"(age: {age_hours:.1f}h)"
                    )
                else:
                    logger.warning(f"Failed to delete session for {session['broadcaster_login']}")
            except Exception as e:
                logger.error(f"Failed to delete session for {session['broadcaster_login']}: {e}")

        return deleted_count

    async def detect_missing_offline_events(self) -> Dict[str, Any]:
        """Detect streams that are offline but still have active sessions (missing offline events)"""
        try:
            from app.storage import get_storage
            storage = get_storage()
            await storage.connect()

            # Get currently live streams
            live_streams = await storage.get_live_streams()
            live_broadcaster_ids = {stream.user_id for stream in live_streams}

            await storage.disconnect()

            # Get active sessions
            active_sessions = await self.sessions.find(
                {"ended_at": None}
            ).to_list(None)

            missing_offline_events = []
            valid_active_sessions = []

            for session in active_sessions:
                broadcaster_id = session["broadcaster_id"]
                broadcaster_login = session["broadcaster_login"]
                started_at = session["started_at"]

                # Check if this streamer is still live
                if broadcaster_id not in live_broadcaster_ids:
                    # Stream is offline but session is still active - missing offline event!
                    # Handle timezone-aware vs naive datetime comparison
                    now = datetime.now(timezone.utc)
                    if started_at.tzinfo is None:
                        # started_at is naive, make now naive too
                        now = now.replace(tzinfo=None)

                    duration_hours = (now - started_at).total_seconds() / 3600
                    missing_offline_events.append({
                        "broadcaster_login": broadcaster_login,
                        "broadcaster_id": broadcaster_id,
                        "session_started": started_at.isoformat(),
                        "hours_active": round(duration_hours, 1),
                        "session_id": str(session["_id"])
                    })
                else:
                    # Stream is still live, session is valid
                    valid_active_sessions.append(session)

            return {
                "missing_offline_events": missing_offline_events,
                "valid_active_sessions": len(valid_active_sessions),
                "total_active_sessions": len(active_sessions),
                "missing_count": len(missing_offline_events),
                "missing_percentage": round((len(missing_offline_events) / len(active_sessions) * 100) if active_sessions else 0, 1)
            }

        except Exception as e:
            logger.error(f"Error detecting missing offline events: {e}")
            return {"error": str(e)}

    async def get_analytics_summary(self) -> Dict[str, Any]:
        """Get overall analytics summary"""
        if self.stats is None or self.sessions is None or self.snapshots is None:
            raise RuntimeError("Analytics service not connected to MongoDB")

        total_streamers = await self.stats.count_documents({})
        total_sessions = await self.sessions.count_documents({})
        total_snapshots = await self.snapshots.count_documents({})

        # Get session statistics
        active_sessions = await self.sessions.count_documents({"ended_at": None})
        completed_sessions = total_sessions - active_sessions

        # Get total hours across all streamers
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "total_hours": {"$sum": "$total_hours_streamed"},
                    "avg_hours_per_streamer": {"$avg": "$total_hours_streamed"},
                }
            }
        ]

        hours_result = await self.stats.aggregate(pipeline).to_list(1)
        total_hours = 0
        avg_hours = 0

        if hours_result:
            total_hours = round(hours_result[0].get("total_hours", 0), 2)
            avg_hours = round(hours_result[0].get("avg_hours_per_streamer", 0), 2)

        return {
            "total_streamers_tracked": total_streamers,
            "total_stream_sessions": total_sessions,
            "active_sessions": active_sessions,
            "completed_sessions": completed_sessions,
            "total_snapshots_captured": total_snapshots,
            "total_hours_streamed": total_hours,
            "avg_hours_per_streamer": avg_hours,
        }

    async def get_comprehensive_summary(self) -> Dict[str, Any]:
        """Get comprehensive analytics summary including configured streamers"""
        if self.stats is None or self.sessions is None or self.snapshots is None:
            raise RuntimeError("Analytics service not connected to MongoDB")

        # Get configured streamers from storage
        storage = get_storage()
        await storage.connect()
        try:
            configured_streamers = await storage.get_all_streamers()
            total_configured = len(configured_streamers)
        except Exception as e:
            logger.warning(f"Could not get configured streamers count: {e}")
            total_configured = 0
        finally:
            await storage.disconnect()

        # Get analytics data
        total_streamers = await self.stats.count_documents({})
        total_sessions = await self.sessions.count_documents({})
        total_snapshots = await self.snapshots.count_documents({})
        active_sessions = await self.sessions.count_documents({"ended_at": None})
        completed_sessions = total_sessions - active_sessions

        # Get total hours across all streamers
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "total_hours": {"$sum": "$total_hours_streamed"},
                    "avg_hours_per_streamer": {"$avg": "$total_hours_streamed"},
                }
            }
        ]

        hours_result = await self.stats.aggregate(pipeline).to_list(1)
        total_hours = 0
        avg_hours = 0

        if hours_result:
            total_hours = round(hours_result[0].get("total_hours", 0), 2)
            avg_hours = round(hours_result[0].get("avg_hours_per_streamer", 0), 2)

        return {
            "total_streamers_configured": total_configured,
            "total_streamers_tracked": total_streamers,
            "tracking_coverage_percent": round((total_streamers / total_configured * 100) if total_configured > 0 else 0, 1),
            "total_stream_sessions": total_sessions,
            "active_sessions": active_sessions,
            "completed_sessions": completed_sessions,
            "session_completion_rate": round((completed_sessions / total_sessions * 100) if total_sessions > 0 else 0, 1),
            "total_snapshots_captured": total_snapshots,
            "total_hours_streamed": total_hours,
            "avg_hours_per_streamer": avg_hours,
        }


# Global instance
analytics_service = AnalyticsService()
