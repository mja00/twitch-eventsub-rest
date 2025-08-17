import logging
from typing import List, Dict, Any, Optional
import uuid
import asyncio
from datetime import datetime, timedelta

from app.models import Streamer, StreamEvent, EventSubNotification, StreamStatus
from app.storage import get_storage
from app.twitch_api import TwitchAPI
from app.config import settings

logger = logging.getLogger(__name__)


class StreamerManager:
    """Manages streamer configurations and EventSub subscriptions"""

    def __init__(self):
        self.twitch_api = TwitchAPI()
        self.storage = get_storage()
        self._update_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """Initialize streamer manager"""
        # Load default streamers from config
        if settings.DEFAULT_STREAMERS:
            default_streamers = [
                s.strip() for s in settings.DEFAULT_STREAMERS.split(",") if s.strip()
            ]

            for username in default_streamers:
                try:
                    await self.add_streamer(username)
                    logger.info(f"Added default streamer: {username}")
                except Exception as e:
                    logger.error(f"Failed to add default streamer {username}: {e}")

        # Validate and fix EventSub subscriptions for all streamers
        await self.validate_and_fix_subscriptions()

        # Initialize current status for all monitored streamers
        await self._initialize_streamer_statuses()

        # Start background update task
        self._update_task = asyncio.create_task(self._update_live_streams())

    async def shutdown(self):
        """Shutdown streamer manager"""
        if self._update_task and not self._update_task.done():
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass

    async def add_streamer(self, username: str) -> Streamer:
        """Add a new streamer to monitor"""
        # Check if streamer already exists
        existing = await self.storage.get_streamer(username)
        if existing:
            logger.info(f"Streamer {username} already exists")
            return existing

        # Get user info from Twitch API
        user_info = await self.twitch_api.get_user_by_login(username)
        if not user_info:
            raise ValueError(f"Twitch user {username} not found")

        # Create streamer object
        streamer = Streamer(
            user_id=user_info["id"],
            username=user_info["login"],
            display_name=user_info["display_name"],
        )

        # Store streamer
        await self.storage.store_streamer(streamer)

        # Create EventSub subscription for stream.online events
        try:
            subscription_id = await self.twitch_api.create_eventsub_subscription(
                event_type="stream.online",
                condition={"broadcaster_user_id": streamer.user_id},
            )

            # Update streamer with subscription ID
            streamer.subscription_id = subscription_id
            await self.storage.store_streamer(streamer)

            logger.info(
                f"Created EventSub subscription {subscription_id} for {username}"
            )

        except Exception as e:
            # Check if it's a "subscription already exists" error (409)
            if "409" in str(e) and "already exists" in str(e):
                logger.info(f"EventSub subscription already exists for {username}, skipping creation")
                # Try to find existing subscription ID by checking all subscriptions
                try:
                    subscriptions = await self.twitch_api.get_eventsub_subscriptions()
                    for sub in subscriptions:
                        if (sub.get("type") == "stream.online" and 
                            sub.get("condition", {}).get("broadcaster_user_id") == streamer.user_id and
                            sub.get("transport", {}).get("callback") == settings.WEBHOOK_URL):
                            streamer.subscription_id = sub.get("id")
                            streamer.is_active = True
                            await self.storage.store_streamer(streamer)
                            logger.info(f"Found existing subscription {sub.get('id')} for {username}")
                            break
                    else:
                        # Couldn't find the subscription, mark as inactive
                        streamer.is_active = False
                        await self.storage.store_streamer(streamer)
                        logger.warning(f"Could not find existing subscription for {username}")
                except Exception as find_error:
                    logger.error(f"Error finding existing subscription for {username}: {find_error}")
                    streamer.is_active = False
                    await self.storage.store_streamer(streamer)
            else:
                logger.error(f"Failed to create EventSub subscription for {username}: {e}")
                # Keep the streamer but mark as inactive
                streamer.is_active = False
                await self.storage.store_streamer(streamer)

        return streamer

    async def remove_streamer(self, username: str) -> None:
        """Remove a streamer from monitoring"""
        streamer = await self.storage.get_streamer(username)
        if not streamer:
            raise ValueError(f"Streamer {username} not found")

        # Remove EventSub subscription
        if streamer.subscription_id:
            try:
                await self.twitch_api.delete_eventsub_subscription(
                    streamer.subscription_id
                )
                logger.info(
                    f"Deleted EventSub subscription {streamer.subscription_id} for {username}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to delete EventSub subscription for {username}: {e}"
                )

        # Remove from storage
        await self.storage.remove_streamer(username)
        logger.info(f"Removed streamer: {username}")

    async def get_streamers(self) -> List[Dict[str, Any]]:
        """Get all configured streamers"""
        streamers = await self.storage.get_all_streamers()
        return [
            {
                "user_id": s.user_id,
                "username": s.username,
                "display_name": s.display_name,
                "subscription_id": s.subscription_id,
                "is_active": s.is_active,
            }
            for s in streamers
        ]

    async def handle_event(self, notification: EventSubNotification) -> None:
        """Handle incoming EventSub notification"""
        event_type = notification.subscription.type
        event_data = notification.event

        if event_type == "stream.online":
            await self._handle_stream_online(event_data)
        elif event_type == "stream.offline":
            await self._handle_stream_offline(event_data)
        else:
            logger.warning(f"Unhandled event type: {event_type}")

    async def _handle_stream_online(self, event_data: Dict[str, Any]) -> None:
        """Handle stream.online event"""
        try:
            stream_event = StreamEvent(
                id=str(uuid.uuid4()),
                event_type="stream.online",
                broadcaster_id=event_data["broadcaster_user_id"],
                broadcaster_login=event_data["broadcaster_user_login"],
                broadcaster_name=event_data["broadcaster_user_name"],
                timestamp=datetime.utcnow(),
                data=event_data,
            )

            await self.storage.store_event(stream_event)

            # Update stream status
            status = StreamStatus(
                user_id=event_data["broadcaster_user_id"],
                username=event_data["broadcaster_user_login"],
                display_name=event_data["broadcaster_user_name"],
                is_live=True,
                stream_data=event_data,
                last_updated=datetime.utcnow(),
                last_event_type="stream.online",
            )
            await self.storage.store_stream_status(status)

            logger.info(
                f"Stream online: {event_data['broadcaster_user_name']} "
                f"({event_data['broadcaster_user_login']})"
            )

        except Exception as e:
            logger.error(f"Error handling stream.online event: {e}")

    async def _handle_stream_offline(self, event_data: Dict[str, Any]) -> None:
        """Handle stream.offline event"""
        try:
            stream_event = StreamEvent(
                id=str(uuid.uuid4()),
                event_type="stream.offline",
                broadcaster_id=event_data["broadcaster_user_id"],
                broadcaster_login=event_data["broadcaster_user_login"],
                broadcaster_name=event_data["broadcaster_user_name"],
                timestamp=datetime.utcnow(),
                data=event_data,
            )

            await self.storage.store_event(stream_event)

            # Update stream status
            status = StreamStatus(
                user_id=event_data["broadcaster_user_id"],
                username=event_data["broadcaster_user_login"],
                display_name=event_data["broadcaster_user_name"],
                is_live=False,
                stream_data=None,
                last_updated=datetime.utcnow(),
                last_event_type="stream.offline",
            )
            await self.storage.store_stream_status(status)

            logger.info(
                f"Stream offline: {event_data['broadcaster_user_name']} "
                f"({event_data['broadcaster_user_login']})"
            )

        except Exception as e:
            logger.error(f"Error handling stream.offline event: {e}")

    async def get_stream_status(self, username: str) -> Optional[Dict[str, Any]]:
        """Get current stream status with fallback to Twitch API"""
        try:
            # First, check if we have the status in storage
            status = await self.storage.get_stream_status(username)
            if status:
                return {
                    "user_id": status.user_id,
                    "username": status.username,
                    "display_name": status.display_name,
                    "is_live": status.is_live,
                    "stream_data": status.stream_data,
                    "last_updated": status.last_updated.isoformat(),
                    "last_event_type": status.last_event_type,
                    "source": "storage",
                }

            # If not in storage, check if we have the streamer configured
            streamer = await self.storage.get_streamer(username)
            if not streamer:
                # Try to get user info from Twitch
                user_info = await self.twitch_api.get_user_by_login(username)
                if not user_info:
                    return None

                # Create a temporary streamer object for the API call
                user_id = user_info["id"]
                display_name = user_info["display_name"]
            else:
                user_id = streamer.user_id
                display_name = streamer.display_name

            # Query Twitch API for current stream status
            stream_data = await self.twitch_api.get_stream_info(user_id)
            is_live = stream_data is not None

            # Store the status for future queries
            status = StreamStatus(
                user_id=user_id,
                username=username,
                display_name=display_name,
                is_live=is_live,
                stream_data=stream_data,
                last_updated=datetime.utcnow(),
                last_event_type=None,
            )
            await self.storage.store_stream_status(status)

            return {
                "user_id": user_id,
                "username": username,
                "display_name": display_name,
                "is_live": is_live,
                "stream_data": stream_data,
                "last_updated": status.last_updated.isoformat(),
                "last_event_type": None,
                "source": "twitch_api",
            }

        except Exception as e:
            logger.error(f"Error getting stream status for {username}: {e}")
            return None

    async def get_live_streams(self) -> List[Dict[str, Any]]:
        """Get all currently live streams"""
        try:
            live_streams = await self.storage.get_live_streams()
            return [
                {
                    "user_id": stream.user_id,
                    "username": stream.username,
                    "display_name": stream.display_name,
                    "is_live": stream.is_live,
                    "stream_data": stream.stream_data,
                    "last_updated": stream.last_updated.isoformat(),
                    "last_event_type": stream.last_event_type,
                }
                for stream in live_streams
            ]
        except Exception as e:
            logger.error(f"Error getting live streams: {e}")
            return []

    async def _update_live_streams(self):
        """Background task to update live stream data every 5 minutes"""
        while True:
            try:
                await asyncio.sleep(300)  # 5 minutes

                # Get all monitored streamers
                streamers = await self.storage.get_all_streamers()

                for streamer in streamers:
                    if not streamer.is_active:
                        continue

                    try:
                        # Check current status
                        current_status = await self.storage.get_stream_status(
                            streamer.username
                        )

                        # Only update if we think they're live or haven't checked recently
                        should_update = (
                            current_status is None
                            or current_status.is_live
                            or (datetime.utcnow() - current_status.last_updated)
                            > timedelta(minutes=10)
                        )

                        if should_update:
                            # Get fresh data from Twitch API
                            stream_data = await self.twitch_api.get_stream_info(
                                streamer.user_id
                            )
                            is_live = stream_data is not None

                            # Update status
                            status = StreamStatus(
                                user_id=streamer.user_id,
                                username=streamer.username,
                                display_name=streamer.display_name,
                                is_live=is_live,
                                stream_data=stream_data,
                                last_updated=datetime.utcnow(),
                                last_event_type=(
                                    current_status.last_event_type
                                    if current_status
                                    else None
                                ),
                            )
                            await self.storage.store_stream_status(status)

                            logger.debug(
                                f"Updated stream status for {streamer.username}: {'live' if is_live else 'offline'}"
                            )

                    except Exception as e:
                        logger.error(
                            f"Error updating stream status for {streamer.username}: {e}"
                        )

            except asyncio.CancelledError:
                logger.info("Stream update task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in stream update task: {e}")
                # Continue running even if there's an error

    async def _initialize_streamer_statuses(self):
        """Initialize current status for all monitored streamers on startup"""
        try:
            streamers = await self.storage.get_all_streamers()
            if not streamers:
                logger.info("No monitored streamers found to initialize")
                return

            logger.info(
                f"Initializing status for {len(streamers)} monitored streamers..."
            )

            for streamer in streamers:
                if not streamer.is_active:
                    continue

                try:
                    # Get current stream status from Twitch API
                    stream_data = await self.twitch_api.get_stream_info(
                        streamer.user_id
                    )
                    is_live = stream_data is not None

                    # Create and store initial status
                    status = StreamStatus(
                        user_id=streamer.user_id,
                        username=streamer.username,
                        display_name=streamer.display_name,
                        is_live=is_live,
                        stream_data=stream_data,
                        last_updated=datetime.utcnow(),
                        last_event_type=None,
                    )
                    await self.storage.store_stream_status(status)

                    logger.info(
                        f"Initialized {streamer.username}: {'live' if is_live else 'offline'}"
                        + (
                            f" - {stream_data.get('game_name', 'Unknown')} - {stream_data.get('viewer_count', 0)} viewers"
                            if is_live and stream_data
                            else ""
                        )
                    )

                except Exception as e:
                    logger.error(
                        f"Error initializing status for {streamer.username}: {e}"
                    )

            logger.info("Completed streamer status initialization")

        except Exception as e:
            logger.error(f"Error during streamer status initialization: {e}")

    async def validate_and_fix_subscriptions(self):
        """Validate and fix EventSub subscriptions for all streamers"""
        try:
            streamers = await self.storage.get_all_streamers()
            if not streamers:
                logger.info("No streamers found to validate subscriptions")
                return

            logger.info(
                f"Validating EventSub subscriptions for {len(streamers)} streamers..."
            )

            fixed_count = 0
            for streamer in streamers:
                if not streamer.is_active:
                    continue

                # Check if subscription exists and is valid
                subscription_valid = False
                if streamer.subscription_id:
                    subscription_valid = await self.twitch_api.validate_subscription(
                        streamer.subscription_id
                    )

                if not subscription_valid:
                    # Delete the old one (if it exists)
                    if streamer.subscription_id:
                        try:
                            await self.twitch_api.delete_eventsub_subscription(
                                streamer.subscription_id
                            )
                        except Exception as e:
                            logger.debug(
                                f"Could not delete old subscription for {streamer.username}: {e}"
                            )

                    logger.info(f"Creating new subscription for {streamer.username}")
                    try:
                        # Create new EventSub subscription
                        subscription_id = (
                            await self.twitch_api.create_eventsub_subscription(
                                event_type="stream.online",
                                condition={"broadcaster_user_id": streamer.user_id},
                            )
                        )

                        # Update streamer with new subscription ID
                        streamer.subscription_id = subscription_id
                        streamer.is_active = True
                        await self.storage.store_streamer(streamer)

                        fixed_count += 1
                        logger.info(
                            f"Fixed subscription for {streamer.username}: {subscription_id}"
                        )

                    except Exception as e:
                        logger.error(
                            f"Failed to fix subscription for {streamer.username}: {e}"
                        )
                        # Mark streamer as inactive if subscription creation fails
                        streamer.is_active = False
                        await self.storage.store_streamer(streamer)
                else:
                    logger.debug(
                        f"Subscription valid for {streamer.username}: {streamer.subscription_id}"
                    )

            logger.info(
                f"Subscription validation complete. Fixed {fixed_count} subscriptions."
            )

        except Exception as e:
            logger.error(f"Error during subscription validation: {e}")
