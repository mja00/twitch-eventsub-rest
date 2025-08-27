import logging
import asyncio
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from typing import Dict, Any

from app.config import settings
from app.models import EventSubNotification, EventSubChallenge
from app.eventsub import verify_signature
from app.streamers import StreamerManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks")

# Use the global streamer manager instance - we'll get it from main.py
# For now, create a new instance - this should be refactored to use dependency injection
streamer_manager = StreamerManager()

# Global webhook diagnostics tracking
webhook_stats = {
    "events_received": 0,
    "events_processed": 0,
    "events_failed": 0,
    "events_by_type": defaultdict(int),
    "errors_by_type": defaultdict(int),
    "recent_events": [],
    "start_time": datetime.now(timezone.utc)
}


def get_real_ip(request: Request) -> str:
    """Extract the real client IP from request headers"""
    # Check Cloudflare header first (most specific)
    cf_connecting_ip = request.headers.get("CF-Connecting-IP")
    if cf_connecting_ip:
        return cf_connecting_ip

    # Check X-Forwarded-For header (standard proxy header)
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        # X-Forwarded-For can contain multiple IPs, take the first one (original client)
        return x_forwarded_for.split(",")[0].strip()

    # Check X-Real-IP header (Nginx)
    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip

    # Fall back to direct client IP
    if request.client:
        return request.client.host

    return "unknown"


@router.post("/eventsub")
async def eventsub_webhook(request: Request):
    """Handle Twitch EventSub webhook notifications"""
    event_type = "unknown"
    broadcaster_login = "unknown"
    event_id = None

    try:
        headers = request.headers
        body = await request.body()
        client_ip = get_real_ip(request)

        logger.debug(f"Received webhook request from {client_ip}: {headers}")

        # Verify the signature
        if not verify_signature(headers, body, settings.WEBHOOK_SECRET):
            logger.warning(f"Invalid webhook signature from {client_ip}")
            raise HTTPException(status_code=403, detail="Invalid signature")

        # Parse the JSON payload
        payload = await request.json()
        logger.debug(f"Received webhook payload: {payload}")

        # Handle challenge verification
        if "challenge" in payload:
            challenge = EventSubChallenge(**payload)
            logger.info(
                f"Received EventSub challenge from {client_ip}: {challenge.challenge}"
            )

            # Return raw challenge
            challenge_value = challenge.challenge
            return Response(
                content=challenge_value,
                status_code=200,
                headers={"Content-Type": "text/plain"},
            )

        # Handle notification
        notification = EventSubNotification(**payload)
        event_type = notification.subscription.type
        event_id = notification.event.get("id", "no-id")

        # Extract broadcaster info for logging
        if hasattr(notification.event, 'broadcaster_user_login'):
            broadcaster_login = notification.event.broadcaster_user_login
        elif "broadcaster_user_login" in notification.event:
            broadcaster_login = notification.event["broadcaster_user_login"]

        # Track webhook statistics
        webhook_stats["events_received"] += 1
        webhook_stats["events_by_type"][event_type] += 1

        # Add to recent events (keep last 100)
        webhook_stats["recent_events"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "broadcaster_login": broadcaster_login,
            "event_id": event_id,
            "client_ip": client_ip
        })
        if len(webhook_stats["recent_events"]) > 100:
            webhook_stats["recent_events"] = webhook_stats["recent_events"][-100:]

        logger.info(f"Processing webhook event: {event_type} for {broadcaster_login} (event_id: {event_id})")

        # Process the event
        await streamer_manager.handle_event(notification)

        webhook_stats["events_processed"] += 1
        logger.info(f"Successfully processed event: {event_type} for {broadcaster_login}")
        return {"status": "success"}

    except Exception as e:
        webhook_stats["events_failed"] += 1
        webhook_stats["errors_by_type"][str(type(e).__name__)] += 1

        logger.error(f"Error processing webhook event {event_type} for {broadcaster_login} (event_id: {event_id}): {str(e)}")
        logger.error(f"Webhook payload was: {payload if 'payload' in locals() else 'not available'}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/diagnostics")
async def get_webhook_diagnostics():
    """Get webhook diagnostics and statistics"""
    now = datetime.now(timezone.utc)
    uptime = now - webhook_stats["start_time"]

    # Calculate rates
    uptime_hours = uptime.total_seconds() / 3600
    events_per_hour = webhook_stats["events_received"] / uptime_hours if uptime_hours > 0 else 0
    failure_rate = (webhook_stats["events_failed"] / webhook_stats["events_received"] * 100) if webhook_stats["events_received"] > 0 else 0

    # Get recent events summary
    recent_online = sum(1 for e in webhook_stats["recent_events"][-20:] if e["event_type"] == "stream.online")
    recent_offline = sum(1 for e in webhook_stats["recent_events"][-20:] if e["event_type"] == "stream.offline")

    return {
        "uptime": {
            "started_at": webhook_stats["start_time"].isoformat(),
            "uptime_seconds": uptime.total_seconds(),
            "uptime_formatted": f"{uptime.days}d {uptime.seconds//3600}h {(uptime.seconds%3600)//60}m"
        },
        "event_counts": {
            "total_received": webhook_stats["events_received"],
            "total_processed": webhook_stats["events_processed"],
            "total_failed": webhook_stats["events_failed"],
            "events_per_hour": round(events_per_hour, 2),
            "failure_rate_percent": round(failure_rate, 2)
        },
        "events_by_type": dict(webhook_stats["events_by_type"]),
        "errors_by_type": dict(webhook_stats["errors_by_type"]),
        "recent_activity": {
            "last_20_events": webhook_stats["recent_events"][-20:],
            "recent_online_events": recent_online,
            "recent_offline_events": recent_offline,
            "online_offline_ratio": f"{recent_online}:{recent_offline}"
        },
        "health_status": {
            "overall_health": "healthy" if failure_rate < 5 else "warning" if failure_rate < 15 else "critical",
            "event_balance": "balanced" if abs(recent_online - recent_offline) <= 2 else "unbalanced",
            "processing_efficiency": round((webhook_stats["events_processed"] / webhook_stats["events_received"] * 100) if webhook_stats["events_received"] > 0 else 100, 2)
        }
    }
