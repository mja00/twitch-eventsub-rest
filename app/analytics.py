import logging
import asyncio
from datetime import datetime, timedelta
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
            ended_at = datetime.utcnow()

        # Find the most recent active session
        session = await self.sessions.find_one(
            {"broadcaster_id": broadcaster_id, "ended_at": None},
            sort=[("started_at", -1)],
        )

        if not session:
            logger.warning(f"No active session found for broadcaster {broadcaster_id}")
            return

        # Calculate duration
        started_at = session["started_at"]
        duration_minutes = int((ended_at - started_at).total_seconds() / 60)

        # Calculate viewer stats from snapshots
        viewer_stats = await self._calculate_viewer_stats(str(session["_id"]))

        # Update session
        update_data = {
            "ended_at": ended_at,
            "duration_minutes": duration_minutes,
            "updated_at": datetime.utcnow(),
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

    async def _calculate_viewer_stats(self, session_id: str) -> Dict[str, Any]:
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
        ended_at = session.get("ended_at", datetime.utcnow())

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
        # Calculate stats from all sessions
        pipeline = [
            {"$match": {"broadcaster_id": broadcaster_id, "ended_at": {"$ne": None}}},
            {
                "$group": {
                    "_id": None,
                    "total_streams": {"$sum": 1},
                    "total_minutes": {"$sum": "$duration_minutes"},
                    "avg_duration": {"$avg": "$duration_minutes"},
                    "max_viewers": {"$max": "$max_viewers"},
                    "avg_viewers": {"$avg": "$avg_viewers"},
                    "last_stream": {"$max": "$started_at"},
                    "first_stream": {"$min": "$started_at"},
                    "broadcaster_login": {"$first": "$broadcaster_login"},
                    "broadcaster_name": {"$first": "$broadcaster_name"},
                }
            },
        ]

        result = await self.sessions.aggregate(pipeline).to_list(1)
        if not result:
            return

        data = result[0]

        stats = StreamerStats(
            broadcaster_id=broadcaster_id,
            broadcaster_login=data["broadcaster_login"],
            broadcaster_name=data["broadcaster_name"],
            total_streams=data["total_streams"],
            total_hours_streamed=round(data["total_minutes"] / 60, 2),
            avg_stream_duration_minutes=round(data["avg_duration"], 2),
            max_concurrent_viewers=data["max_viewers"] or 0,
            avg_viewers_all_time=round(data["avg_viewers"] or 0, 2),
            last_stream_at=data["last_stream"],
            first_seen_at=data["first_stream"],
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

    async def get_analytics_summary(self) -> Dict[str, Any]:
        """Get overall analytics summary"""
        if self.stats is None or self.sessions is None or self.snapshots is None:
            raise RuntimeError("Analytics service not connected to MongoDB")

        total_streamers = await self.stats.count_documents({})
        total_sessions = await self.sessions.count_documents({})
        total_snapshots = await self.snapshots.count_documents({})

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
            "total_snapshots_captured": total_snapshots,
            "total_hours_streamed": total_hours,
            "avg_hours_per_streamer": avg_hours,
        }


# Global instance
analytics_service = AnalyticsService()
