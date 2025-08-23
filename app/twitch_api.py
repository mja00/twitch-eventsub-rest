import httpx
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone

from app.config import settings

logger = logging.getLogger(__name__)


class TwitchAPI:
    """Twitch API client for EventSub and user management"""

    def __init__(self):
        self.client_id = settings.CLIENT_ID
        self.client_secret = settings.CLIENT_SECRET
        self.base_url = "https://api.twitch.tv/helix"
        self.auth_url = "https://id.twitch.tv/oauth2/token"
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None

    async def _get_access_token(self) -> str:
        """Get or refresh access token"""
        if (
            self.access_token
            and self.token_expires_at
            and datetime.now(timezone.utc)
            < self.token_expires_at - timedelta(minutes=5)
        ):
            return self.access_token

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.auth_url,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials",
                },
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get access token: {response.text}")

            data = response.json()
            self.access_token = data["access_token"]
            self.token_expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=data["expires_in"]
            )

            logger.info("Obtained new Twitch access token")
            return self.access_token

    async def _make_request(
        self, method: str, endpoint: str, **kwargs
    ) -> Dict[str, Any]:
        """Make authenticated request to Twitch API"""
        token = await self._get_access_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Client-Id": self.client_id,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=f"{self.base_url}/{endpoint}",
                headers=headers,
                **kwargs,
            )

            if response.status_code not in [200, 201, 202, 204]:
                raise Exception(
                    f"Twitch API error: {response.status_code} - {response.text}"
                )

            return response.json() if response.content else {}

    async def get_user_by_login(self, login: str) -> Optional[Dict[str, Any]]:
        """Get user information by login name"""
        try:
            response = await self._make_request("GET", f"users?login={login}")
            users = response.get("data", [])
            return users[0] if users else None
        except Exception as e:
            logger.error(f"Error getting user {login}: {e}")
            return None

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user information by user ID"""
        try:
            response = await self._make_request("GET", f"users?id={user_id}")
            users = response.get("data", [])
            return users[0] if users else None
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None

    async def create_eventsub_subscription(
        self, event_type: str, condition: Dict[str, Any]
    ) -> str:
        """Create EventSub subscription"""
        payload = {
            "type": event_type,
            "version": "1",
            "condition": condition,
            "transport": {
                "method": "webhook",
                "callback": settings.WEBHOOK_URL,
                "secret": settings.WEBHOOK_SECRET,
            },
        }

        try:
            response = await self._make_request(
                "POST", "eventsub/subscriptions", json=payload
            )
            subscription = response.get("data", [{}])[0]
            return subscription.get("id")
        except Exception as e:
            logger.error(f"Error creating EventSub subscription: {e}")
            raise

    async def delete_eventsub_subscription(self, subscription_id: str) -> None:
        """Delete EventSub subscription"""
        try:
            token = await self._get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Client-Id": self.client_id,
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    f"{self.base_url}/eventsub/subscriptions?id={subscription_id}",
                    headers=headers,
                )

                if response.status_code == 404:
                    # Subscription doesn't exist, which means it's already deleted
                    logger.debug(
                        f"Subscription {subscription_id} already deleted (404)"
                    )
                    return
                elif response.status_code not in [200, 201, 202, 204]:
                    raise Exception(
                        f"Twitch API error: {response.status_code} - {response.text}"
                    )

        except Exception as e:
            # Check if it's a 404 error embedded in the exception message
            if "404" in str(e) or "not found" in str(e).lower():
                logger.debug(f"Subscription {subscription_id} already deleted (404)")
                return
            else:
                logger.error(
                    f"Error deleting EventSub subscription {subscription_id}: {e}"
                )
                raise

    async def get_eventsub_subscriptions(self) -> List[Dict[str, Any]]:
        """Get all EventSub subscriptions"""
        try:
            response = await self._make_request("GET", "eventsub/subscriptions")
            return response.get("data", [])
        except Exception as e:
            logger.error(f"Error getting EventSub subscriptions: {e}")
            return []

    async def get_eventsub_costs(self) -> Dict[str, Any]:
        """Get EventSub costs"""
        try:
            response = await self._make_request("GET", "eventsub/subscriptions")
            total_cost = response.get("total_cost", 0)
            max_total_cost = response.get("max_total_cost", 0)
            return {
                "total_cost": total_cost,
                "max_total_cost": max_total_cost,
            }
        except Exception as e:
            logger.error(f"Error getting EventSub costs: {e}")
            return {}

    async def get_stream_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get current stream information for a user"""
        try:
            response = await self._make_request("GET", f"streams?user_id={user_id}")
            streams = response.get("data", [])
            return streams[0] if streams else None
        except Exception as e:
            logger.error(f"Error getting stream info for {user_id}: {e}")
            return None

    async def cleanup_webhook_subscriptions(self) -> int:
        """Remove all EventSub subscriptions for our webhook URL"""
        try:
            subscriptions = await self.get_eventsub_subscriptions()
            logger.info(f"Found {len(subscriptions)} subscriptions")

            webhook_subscriptions = [
                sub
                for sub in subscriptions
                if sub.get("transport", {}).get("callback") == settings.WEBHOOK_URL
            ]
            cleanup_count = 0
            for subscription in webhook_subscriptions:
                try:
                    await self.delete_eventsub_subscription(subscription["id"])
                    cleanup_count += 1
                    logger.info(
                        f"Cleaned up subscription: {subscription['type']} for {subscription.get('condition', {})}"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to cleanup subscription {subscription['id']}: {e}"
                    )

            logger.info(f"Cleaned up {cleanup_count} existing webhook subscriptions")
            return cleanup_count
        except Exception as e:
            logger.error(f"Error during subscription cleanup: {e}")
            return 0

    async def validate_subscription(self, subscription_id: str) -> bool:
        """Check if a subscription ID is still valid and active"""
        try:
            subscriptions = await self.get_eventsub_subscriptions()
            for subscription in subscriptions:
                if (
                    subscription["id"] == subscription_id
                    and subscription.get("status") == "enabled"
                ):
                    return True
            return False
        except Exception as e:
            logger.error(f"Error validating subscription {subscription_id}: {e}")
            return False

    async def delete_all_subscriptions(self) -> int:
        """Delete ALL EventSub subscriptions (regardless of callback URL)"""
        try:
            subscriptions = await self.get_eventsub_subscriptions()
            logger.info(f"Found {len(subscriptions)} total subscriptions to delete")

            deleted_count = 0
            for subscription in subscriptions:
                try:
                    await self.delete_eventsub_subscription(subscription["id"])
                    deleted_count += 1
                    logger.info(
                        f"Deleted subscription: {subscription['type']} for {subscription.get('condition', {})} "
                        f"(callback: {subscription.get('transport', {}).get('callback', 'unknown')})"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to delete subscription {subscription['id']}: {e}"
                    )

            logger.info(f"Deleted {deleted_count} total subscriptions")
            return deleted_count
        except Exception as e:
            logger.error(f"Error during all subscriptions cleanup: {e}")
            return 0
