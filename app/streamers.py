import logging
from typing import List, Dict, Any, Optional
import uuid
import asyncio
from datetime import datetime, timedelta

from app.models import Streamer, StreamEvent, EventSubNotification, StreamStatus
from app.storage import get_storage
from app.twitch_api import TwitchAPI
from app.config import settings
from app.analytics import analytics_service

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

        # Create EventSub subscriptions for both stream.online and stream.offline events
        await self._create_subscriptions_for_streamer(streamer, username)

        return streamer

    async def remove_streamer(self, username: str) -> None:
        """Remove a streamer from monitoring"""
        streamer = await self.storage.get_streamer(username)
        if not streamer:
            raise ValueError(f"Streamer {username} not found")

        # Remove EventSub subscriptions
        subscription_ids = []
        if streamer.online_subscription_id:
            subscription_ids.append(("online", streamer.online_subscription_id))
        if streamer.offline_subscription_id:
            subscription_ids.append(("offline", streamer.offline_subscription_id))
        # Backward compatibility
        if streamer.subscription_id and streamer.subscription_id not in [
            streamer.online_subscription_id,
            streamer.offline_subscription_id,
        ]:
            subscription_ids.append(("legacy", streamer.subscription_id))

        for sub_type, sub_id in subscription_ids:
            try:
                await self.twitch_api.delete_eventsub_subscription(sub_id)
                logger.info(
                    f"Deleted {sub_type} EventSub subscription {sub_id} for {username}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to delete {sub_type} EventSub subscription for {username}: {e}"
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
                "subscription_id": s.subscription_id,  # Deprecated
                "online_subscription_id": s.online_subscription_id,
                "offline_subscription_id": s.offline_subscription_id,
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
                timestamp=datetime.now(datetime.UTC),
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
                last_updated=datetime.now(datetime.UTC),
                last_event_type="stream.online",
            )
            await self.storage.store_stream_status(status)

            # Start analytics session
            await analytics_service.start_stream_session(event_data)

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
                timestamp=datetime.now(datetime.UTC),
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
                last_updated=datetime.now(datetime.UTC),
                last_event_type="stream.offline",
            )
            await self.storage.store_stream_status(status)

            # End analytics session
            await analytics_service.end_stream_session(
                event_data["broadcaster_user_id"]
            )

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
                last_updated=datetime.now(datetime.UTC),
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
                            or (datetime.now(datetime.UTC) - current_status.last_updated)
                            > timedelta(minutes=10)
                        )

                        if should_update:
                            # Get fresh data from Twitch API
                            stream_data = await self.twitch_api.get_stream_info(
                                streamer.user_id
                            )
                            is_live = stream_data is not None

                            # Be conservative: only update if we have a definitive change
                            # or if this is the first time we're checking
                            should_store_update = True

                            if current_status is not None:
                                # If we currently think they're live but API says offline,
                                # be more cautious - could be a temporary API issue
                                if current_status.is_live and not is_live:
                                    # Only mark as offline if EventSub hasn't updated recently
                                    # and we've had multiple API checks confirming they're offline
                                    time_since_update = (
                                        datetime.now(datetime.UTC) - current_status.last_updated
                                    )
                                    if time_since_update < timedelta(minutes=15):
                                        logger.debug(
                                            f"API says {streamer.username} is offline but recent status was live, keeping live status"
                                        )
                                        should_store_update = False

                            if should_store_update:
                                # Update status
                                status = StreamStatus(
                                    user_id=streamer.user_id,
                                    username=streamer.username,
                                    display_name=streamer.display_name,
                                    is_live=is_live,
                                    stream_data=stream_data,
                                    last_updated=datetime.now(datetime.UTC),
                                    last_event_type=(
                                        current_status.last_event_type
                                        if current_status
                                        else None
                                    ),
                                )
                                await self.storage.store_stream_status(status)

                                # Capture analytics snapshot
                                if stream_data:
                                    await analytics_service.capture_stream_snapshot(
                                        stream_data
                                    )

                            if should_store_update:
                                logger.debug(
                                    f"Updated stream status for {streamer.username}: {'live' if is_live else 'offline'}"
                                )
                            else:
                                logger.debug(
                                    f"Skipped status update for {streamer.username} (preserving live status)"
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
                        last_updated=datetime.now(datetime.UTC),
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

                # Check if subscriptions exist and are valid
                online_valid = False
                offline_valid = False

                if streamer.online_subscription_id:
                    online_valid = await self.twitch_api.validate_subscription(
                        streamer.online_subscription_id
                    )
                elif streamer.subscription_id:  # Backward compatibility
                    online_valid = await self.twitch_api.validate_subscription(
                        streamer.subscription_id
                    )
                    if online_valid:
                        streamer.online_subscription_id = streamer.subscription_id

                if streamer.offline_subscription_id:
                    offline_valid = await self.twitch_api.validate_subscription(
                        streamer.offline_subscription_id
                    )

                needs_fixing = not (online_valid and offline_valid)

                if needs_fixing:
                    logger.info(
                        f"Fixing subscriptions for {streamer.username} (online: {online_valid}, offline: {offline_valid})"
                    )

                    # Delete invalid subscriptions
                    if not online_valid and streamer.online_subscription_id:
                        await self._delete_subscription_safely(
                            streamer.online_subscription_id, streamer.username, "online"
                        )
                        streamer.online_subscription_id = None
                    if not offline_valid and streamer.offline_subscription_id:
                        await self._delete_subscription_safely(
                            streamer.offline_subscription_id,
                            streamer.username,
                            "offline",
                        )
                        streamer.offline_subscription_id = None

                    # Recreate all subscriptions
                    try:
                        await self._create_subscriptions_for_streamer(
                            streamer, streamer.username
                        )
                        fixed_count += 1
                        logger.info(f"Fixed subscriptions for {streamer.username}")
                    except Exception as e:
                        logger.error(
                            f"Failed to fix subscriptions for {streamer.username}: {e}"
                        )
                else:
                    logger.debug(f"All subscriptions valid for {streamer.username}")

            logger.info(
                f"Subscription validation complete. Fixed {fixed_count} subscriptions."
            )

        except Exception as e:
            logger.error(f"Error during subscription validation: {e}")

    async def _create_subscriptions_for_streamer(
        self, streamer: Streamer, username: str
    ) -> None:
        """Create both online and offline EventSub subscriptions for a streamer"""
        online_success = False
        offline_success = False

        # Create stream.online subscription
        try:
            online_subscription_id = await self.twitch_api.create_eventsub_subscription(
                event_type="stream.online",
                condition={"broadcaster_user_id": streamer.user_id},
            )
            streamer.online_subscription_id = online_subscription_id
            streamer.subscription_id = online_subscription_id  # Backward compatibility
            online_success = True
            logger.info(
                f"Created stream.online subscription {online_subscription_id} for {username}"
            )

        except Exception as e:
            if "409" in str(e) and "already exists" in str(e):
                online_success = await self._find_existing_subscription(
                    streamer, username, "stream.online"
                )
            else:
                logger.error(
                    f"Failed to create stream.online subscription for {username}: {e}"
                )

        # Create stream.offline subscription
        try:
            offline_subscription_id = (
                await self.twitch_api.create_eventsub_subscription(
                    event_type="stream.offline",
                    condition={"broadcaster_user_id": streamer.user_id},
                )
            )
            streamer.offline_subscription_id = offline_subscription_id
            offline_success = True
            logger.info(
                f"Created stream.offline subscription {offline_subscription_id} for {username}"
            )

        except Exception as e:
            if "409" in str(e) and "already exists" in str(e):
                offline_success = await self._find_existing_subscription(
                    streamer, username, "stream.offline"
                )
            else:
                logger.error(
                    f"Failed to create stream.offline subscription for {username}: {e}"
                )

        # Update streamer status based on success
        streamer.is_active = online_success and offline_success
        await self.storage.store_streamer(streamer)

        if not streamer.is_active:
            logger.warning(
                f"Streamer {username} marked as inactive due to subscription failures"
            )

    async def _find_existing_subscription(
        self, streamer: Streamer, username: str, event_type: str
    ) -> bool:
        """Find existing subscription for a streamer and event type"""
        try:
            subscriptions = await self.twitch_api.get_eventsub_subscriptions()
            for sub in subscriptions:
                if (
                    sub.get("type") == event_type
                    and sub.get("condition", {}).get("broadcaster_user_id")
                    == streamer.user_id
                    and sub.get("transport", {}).get("callback") == settings.WEBHOOK_URL
                ):
                    subscription_id = sub.get("id")
                    if event_type == "stream.online":
                        streamer.online_subscription_id = subscription_id
                        streamer.subscription_id = (
                            subscription_id  # Backward compatibility
                        )
                    elif event_type == "stream.offline":
                        streamer.offline_subscription_id = subscription_id

                    logger.info(
                        f"Found existing {event_type} subscription {subscription_id} for {username}"
                    )
                    return True

            logger.warning(
                f"Could not find existing {event_type} subscription for {username}"
            )
            return False

        except Exception as find_error:
            logger.error(
                f"Error finding existing {event_type} subscription for {username}: {find_error}"
            )
            return False

    async def _delete_subscription_safely(
        self, subscription_id: str, username: str, sub_type: str
    ) -> None:
        """Safely delete a subscription with error handling"""
        try:
            await self.twitch_api.delete_eventsub_subscription(subscription_id)
            logger.debug(
                f"Deleted invalid {sub_type} subscription {subscription_id} for {username}"
            )
        except Exception as e:
            logger.debug(
                f"Could not delete {sub_type} subscription for {username}: {e}"
            )
