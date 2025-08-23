import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.config import settings
from app.models import EventSubNotification, EventSubChallenge
from app.eventsub import verify_signature
from app.streamers import StreamerManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks")

# Use the global streamer manager instance - we'll get it from main.py
# For now, create a new instance - this should be refactored to use dependency injection
streamer_manager = StreamerManager()


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

        # Process the event
        await streamer_manager.handle_event(notification)

        logger.info(f"Processed event: {notification.subscription.type}")
        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
