from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import json
from datetime import datetime
import redis.asyncio as redis
from app.config import settings
from app.models import StreamEvent, Streamer, StreamStatus


class StorageInterface(ABC):
    """Abstract storage interface"""

    @abstractmethod
    async def connect(self) -> None:
        """Connect to storage backend"""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from storage backend"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check storage health"""
        pass

    @abstractmethod
    async def store_event(self, event: StreamEvent) -> None:
        """Store a stream event"""
        pass

    @abstractmethod
    async def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent stream events"""
        pass

    @abstractmethod
    async def store_streamer(self, streamer: Streamer) -> None:
        """Store streamer configuration"""
        pass

    @abstractmethod
    async def get_streamer(self, username: str) -> Optional[Streamer]:
        """Get streamer by username"""
        pass

    @abstractmethod
    async def get_all_streamers(self) -> List[Streamer]:
        """Get all configured streamers"""
        pass

    @abstractmethod
    async def remove_streamer(self, username: str) -> None:
        """Remove streamer configuration"""
        pass

    @abstractmethod
    async def store_stream_status(self, status: StreamStatus) -> None:
        """Store current stream status"""
        pass

    @abstractmethod
    async def get_stream_status(self, username: str) -> Optional[StreamStatus]:
        """Get current stream status"""
        pass

    @abstractmethod
    async def get_live_streams(self) -> List[StreamStatus]:
        """Get all currently live streams"""
        pass


class MemoryStorage(StorageInterface):
    """In-memory storage for testing"""

    def __init__(self):
        self.events: List[StreamEvent] = []
        self.streamers: Dict[str, Streamer] = {}
        self.stream_statuses: Dict[str, StreamStatus] = {}
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def health_check(self) -> bool:
        return self.connected

    async def store_event(self, event: StreamEvent) -> None:
        self.events.append(event)
        # Keep only last 1000 events
        if len(self.events) > 1000:
            self.events = self.events[-1000:]

    async def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        recent_events = (
            self.events[-limit:] if limit <= len(self.events) else self.events
        )
        return [
            {
                "id": event.id,
                "event_type": event.event_type,
                "broadcaster_id": event.broadcaster_id,
                "broadcaster_login": event.broadcaster_login,
                "broadcaster_name": event.broadcaster_name,
                "timestamp": event.timestamp.isoformat(),
                "data": event.data,
            }
            for event in reversed(recent_events)
        ]

    async def store_streamer(self, streamer: Streamer) -> None:
        self.streamers[streamer.username] = streamer

    async def get_streamer(self, username: str) -> Optional[Streamer]:
        return self.streamers.get(username)

    async def get_all_streamers(self) -> List[Streamer]:
        return list(self.streamers.values())

    async def remove_streamer(self, username: str) -> None:
        if username in self.streamers:
            del self.streamers[username]
        if username in self.stream_statuses:
            del self.stream_statuses[username]

    async def store_stream_status(self, status: StreamStatus) -> None:
        self.stream_statuses[status.username] = status

    async def get_stream_status(self, username: str) -> Optional[StreamStatus]:
        return self.stream_statuses.get(username)

    async def get_live_streams(self) -> List[StreamStatus]:
        return [status for status in self.stream_statuses.values() if status.is_live]


class RedisStorage(StorageInterface):
    """Redis storage implementation"""

    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.events_key = "twitch:events"
        self.streamers_key = "twitch:streamers"
        self.status_key = "twitch:stream_status"

    async def connect(self) -> None:
        self.redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        await self.redis_client.ping()

    async def disconnect(self) -> None:
        if self.redis_client:
            await self.redis_client.aclose()

    async def health_check(self) -> bool:
        try:
            if self.redis_client:
                await self.redis_client.ping()
                return True
        except Exception:
            pass
        return False

    async def store_event(self, event: StreamEvent) -> None:
        if not self.redis_client:
            raise RuntimeError("Redis client not connected")

        event_data = {
            "id": event.id,
            "event_type": event.event_type,
            "broadcaster_id": event.broadcaster_id,
            "broadcaster_login": event.broadcaster_login,
            "broadcaster_name": event.broadcaster_name,
            "timestamp": event.timestamp.isoformat(),
            "data": event.data,
        }

        # Store event with timestamp as score for ordering
        await self.redis_client.zadd(
            self.events_key, {json.dumps(event_data): event.timestamp.timestamp()}
        )

        # Keep only last 1000 events
        await self.redis_client.zremrangebyrank(self.events_key, 0, -1001)

    async def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.redis_client:
            raise RuntimeError("Redis client not connected")

        # Get most recent events (highest scores)
        events = await self.redis_client.zrevrange(self.events_key, 0, limit - 1)

        return [json.loads(event) for event in events]

    async def store_streamer(self, streamer: Streamer) -> None:
        if not self.redis_client:
            raise RuntimeError("Redis client not connected")

        streamer_data = streamer.model_dump()
        await self.redis_client.hset(
            self.streamers_key, streamer.username, json.dumps(streamer_data)
        )

    async def get_streamer(self, username: str) -> Optional[Streamer]:
        if not self.redis_client:
            raise RuntimeError("Redis client not connected")

        data = await self.redis_client.hget(self.streamers_key, username)
        if data:
            return Streamer(**json.loads(data))
        return None

    async def get_all_streamers(self) -> List[Streamer]:
        if not self.redis_client:
            raise RuntimeError("Redis client not connected")

        streamers_data = await self.redis_client.hgetall(self.streamers_key)
        return [Streamer(**json.loads(data)) for data in streamers_data.values()]

    async def remove_streamer(self, username: str) -> None:
        if not self.redis_client:
            raise RuntimeError("Redis client not connected")

        await self.redis_client.hdel(self.streamers_key, username)
        await self.redis_client.hdel(self.status_key, username)

    async def store_stream_status(self, status: StreamStatus) -> None:
        if not self.redis_client:
            raise RuntimeError("Redis client not connected")

        status_data = {
            "user_id": status.user_id,
            "username": status.username,
            "display_name": status.display_name,
            "is_live": status.is_live,
            "stream_data": status.stream_data,
            "last_updated": status.last_updated.isoformat(),
            "last_event_type": status.last_event_type,
        }

        await self.redis_client.hset(
            self.status_key, status.username, json.dumps(status_data)
        )

    async def get_stream_status(self, username: str) -> Optional[StreamStatus]:
        if not self.redis_client:
            raise RuntimeError("Redis client not connected")

        data = await self.redis_client.hget(self.status_key, username)
        if data:
            status_data = json.loads(data)
            status_data["last_updated"] = datetime.fromisoformat(
                status_data["last_updated"]
            )
            return StreamStatus(**status_data)
        return None

    async def get_live_streams(self) -> List[StreamStatus]:
        if not self.redis_client:
            raise RuntimeError("Redis client not connected")

        all_status_data = await self.redis_client.hgetall(self.status_key)
        live_streams = []

        for data in all_status_data.values():
            status_data = json.loads(data)
            status_data["last_updated"] = datetime.fromisoformat(
                status_data["last_updated"]
            )
            status = StreamStatus(**status_data)
            if status.is_live:
                live_streams.append(status)

        return live_streams


# Storage factory
_storage_instance: Optional[StorageInterface] = None


def get_storage() -> StorageInterface:
    """Get storage instance based on configuration"""
    global _storage_instance

    if _storage_instance is None:
        if settings.STORAGE_TYPE.lower() == "redis":
            _storage_instance = RedisStorage()
        else:
            _storage_instance = MemoryStorage()

    return _storage_instance
