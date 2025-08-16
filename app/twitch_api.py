import httpx
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

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
            and datetime.utcnow() < self.token_expires_at - timedelta(minutes=5)
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
            self.token_expires_at = datetime.utcnow() + timedelta(
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
            await self._make_request(
                "DELETE", f"eventsub/subscriptions?id={subscription_id}"
            )
        except Exception as e:
            logger.error(f"Error deleting EventSub subscription {subscription_id}: {e}")
            raise

    async def get_eventsub_subscriptions(self) -> List[Dict[str, Any]]:
        """Get all EventSub subscriptions"""
        try:
            response = await self._make_request("GET", "eventsub/subscriptions")
            return response.get("data", [])
        except Exception as e:
            logger.error(f"Error getting EventSub subscriptions: {e}")
            return []

    async def get_stream_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get current stream information for a user"""
        try:
            response = await self._make_request("GET", f"streams?user_id={user_id}")
            streams = response.get("data", [])
            return streams[0] if streams else None
        except Exception as e:
            logger.error(f"Error getting stream info for {user_id}: {e}")
            return None
