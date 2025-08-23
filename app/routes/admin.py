import logging
from fastapi import APIRouter, HTTPException, Depends

from app.auth import verify_api_key
from app.config import settings
from app.streamers import StreamerManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")

# Use a new instance - should be refactored to use dependency injection
streamer_manager = StreamerManager()


@router.post("/cleanup-subscriptions")
async def cleanup_subscriptions(api_key_valid: bool = Depends(verify_api_key)):
    """Manually cleanup EventSub subscriptions for our webhook URL"""
    try:
        from app.twitch_api import TwitchAPI

        twitch_api = TwitchAPI()
        cleanup_count = await twitch_api.cleanup_webhook_subscriptions()
        return {
            "message": f"Cleaned up {cleanup_count} EventSub subscriptions",
            "cleanup_count": cleanup_count,
        }
    except Exception as e:
        logger.error(f"Error during subscription cleanup: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/subscriptions")
async def get_current_subscriptions(api_key_valid: bool = Depends(verify_api_key)):
    """Get all current EventSub subscriptions"""
    try:
        from app.twitch_api import TwitchAPI

        twitch_api = TwitchAPI()
        subscriptions = await twitch_api.get_eventsub_subscriptions()
        costs = await twitch_api.get_eventsub_costs()

        # Filter to show only our webhook subscriptions and add details
        our_subscriptions = []
        other_subscriptions = []
        for sub in subscriptions:
            if sub.get("transport", {}).get("callback") == settings.WEBHOOK_URL:
                our_subscriptions.append(
                    {
                        "id": sub.get("id"),
                        "type": sub.get("type"),
                        "status": sub.get("status"),
                        "condition": sub.get("condition"),
                        "created_at": sub.get("created_at"),
                        "cost": sub.get("cost", 0),
                    }
                )
            else:
                other_subscriptions.append(
                    {
                        "id": sub.get("id"),
                        "type": sub.get("type"),
                        "status": sub.get("status"),
                        "condition": sub.get("condition"),
                        "created_at": sub.get("created_at"),
                        "cost": sub.get("cost", 0),
                    }
                )

        return {
            "subscriptions": our_subscriptions,
            "other_subscriptions": other_subscriptions,
            "total_subscriptions": len(subscriptions),
            "our_subscriptions_count": len(our_subscriptions),
            "other_subscriptions_count": len(other_subscriptions),
            "webhook_url": settings.WEBHOOK_URL,
            "costs": costs,
        }
    except Exception as e:
        logger.error(f"Error getting subscriptions: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/verify-subscriptions")
async def verify_all_subscriptions(api_key_valid: bool = Depends(verify_api_key)):
    """Re-verify and fix EventSub subscriptions for all tracked streamers"""
    try:
        await streamer_manager.validate_and_fix_subscriptions()
        return {"message": "Subscription verification completed", "status": "success"}
    except Exception as e:
        logger.error(f"Error during subscription verification: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/reload-default-streamers")
async def reload_default_streamers(api_key_valid: bool = Depends(verify_api_key)):
    """Re-add all default streamers from configuration"""
    try:
        if not settings.DEFAULT_STREAMERS:
            return {"message": "No default streamers configured", "added_count": 0}

        default_streamers = [
            s.strip() for s in settings.DEFAULT_STREAMERS.split(",") if s.strip()
        ]

        added_count = 0
        failed_streamers = []

        for username in default_streamers:
            try:
                await streamer_manager.add_streamer(username)
                added_count += 1
                logger.info(f"Re-added default streamer: {username}")
            except Exception as e:
                failed_streamers.append({"username": username, "error": str(e)})
                logger.error(f"Failed to re-add default streamer {username}: {e}")

        result = {
            "message": f"Re-added {added_count} default streamers",
            "added_count": added_count,
            "total_configured": len(default_streamers),
        }

        if failed_streamers:
            result["failed_streamers"] = failed_streamers

        return result

    except Exception as e:
        logger.error(f"Error during default streamers reload: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/delete-all-subscriptions")
async def delete_all_subscriptions(api_key_valid: bool = Depends(verify_api_key)):
    """Delete ALL EventSub subscriptions (WARNING: affects all callback URLs)"""
    try:
        from app.twitch_api import TwitchAPI

        twitch_api = TwitchAPI()
        deleted_count = await twitch_api.delete_all_subscriptions()
        return {
            "message": f"Deleted {deleted_count} total EventSub subscriptions",
            "deleted_count": deleted_count,
            "warning": "This action deleted ALL subscriptions, not just our webhook URL",
        }
    except Exception as e:
        logger.error(f"Error during all subscriptions deletion: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
