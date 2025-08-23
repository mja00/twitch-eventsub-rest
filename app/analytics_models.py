from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from bson import ObjectId


class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type="string")


class StreamSession(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    broadcaster_id: str
    broadcaster_login: str
    broadcaster_name: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    title: Optional[str] = None
    viewer_count_samples: list[Dict[str, Any]] = Field(default_factory=list)
    max_viewers: Optional[int] = None
    avg_viewers: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class StreamSnapshot(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    broadcaster_id: str
    broadcaster_login: str
    broadcaster_name: str
    is_live: bool
    stream_id: Optional[str] = None
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    title: Optional[str] = None
    viewer_count: Optional[int] = None
    started_at: Optional[datetime] = None
    language: Optional[str] = None
    thumbnail_url: Optional[str] = None
    tag_ids: list[str] = Field(default_factory=list)
    captured_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class StreamerStats(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    broadcaster_id: str
    broadcaster_login: str
    broadcaster_name: str
    total_streams: int = 0
    total_hours_streamed: float = 0.0
    avg_stream_duration_minutes: float = 0.0
    max_concurrent_viewers: int = 0
    avg_viewers_all_time: float = 0.0
    last_stream_at: Optional[datetime] = None
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
