from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime


class EventSubSubscription(BaseModel):
    id: str
    status: str
    type: str
    version: str
    condition: Dict[str, Any]
    transport: Dict[str, Any]
    created_at: str
    cost: int


class EventSubEvent(BaseModel):
    """Base EventSub event model"""

    pass


class StreamOnlineEvent(EventSubEvent):
    id: str
    broadcaster_user_id: str
    broadcaster_user_login: str
    broadcaster_user_name: str
    type: str
    started_at: str


class StreamOfflineEvent(EventSubEvent):
    broadcaster_user_id: str
    broadcaster_user_login: str
    broadcaster_user_name: str


class EventSubNotification(BaseModel):
    subscription: EventSubSubscription
    event: Dict[str, Any]


class EventSubChallenge(BaseModel):
    challenge: str
    subscription: EventSubSubscription


class StreamEvent(BaseModel):
    """Stored stream event"""

    id: str
    event_type: str  # "stream.online" or "stream.offline"
    broadcaster_id: str
    broadcaster_login: str
    broadcaster_name: str
    timestamp: datetime
    data: Dict[str, Any]


class Streamer(BaseModel):
    """Streamer configuration"""

    user_id: str
    username: str
    display_name: str
    subscription_id: Optional[str] = None
    is_active: bool = True


class StreamStatus(BaseModel):
    """Current stream status"""

    user_id: str
    username: str
    display_name: str
    is_live: bool
    stream_data: Optional[Dict[str, Any]] = None
    last_updated: datetime
    last_event_type: Optional[str] = None
