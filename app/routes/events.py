from fastapi import APIRouter, HTTPException
from app.storage import get_storage

router = APIRouter(prefix="/events")


@router.get("")
async def get_recent_events(limit: int = 50):
    """Get recent stream events"""
    storage = get_storage()
    events = await storage.get_recent_events(limit)
    return {"events": events}


@router.get("/type/{event_type}")
async def get_events_by_type(event_type: str, limit: int = 50):
    """Get recent stream events filtered by event type (stream.online or stream.offline)"""
    if event_type not in ["stream.online", "stream.offline"]:
        raise HTTPException(
            status_code=400,
            detail="event_type must be 'stream.online' or 'stream.offline'",
        )

    storage = get_storage()
    all_events = await storage.get_recent_events(limit * 3)  # Get more to filter from

    # Filter events by type
    filtered_events = [
        event for event in all_events if event.get("event_type") == event_type
    ][:limit]

    return {
        "events": filtered_events,
        "event_type": event_type,
        "count": len(filtered_events),
    }


@router.get("/streamer/{username}")
async def get_events_by_streamer(username: str, limit: int = 50):
    """Get recent stream events filtered by streamer username"""
    storage = get_storage()
    all_events = await storage.get_recent_events(limit * 3)  # Get more to filter from

    # Filter events by streamer (case-insensitive)
    filtered_events = [
        event
        for event in all_events
        if event.get("broadcaster_login", "").lower() == username.lower()
    ][:limit]

    return {
        "events": filtered_events,
        "streamer": username,
        "count": len(filtered_events),
    }
