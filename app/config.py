import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Twitch API credentials
    CLIENT_ID: str = os.getenv("TWITCH_CLIENT_ID", "")
    CLIENT_SECRET: str = os.getenv("TWITCH_CLIENT_SECRET", "")

    # EventSub webhook configuration
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "your-webhook-secret")
    WEBHOOK_URL: str = os.getenv(
        "WEBHOOK_URL", "https://your-domain.com/webhooks/eventsub"
    )

    # Storage configuration
    STORAGE_TYPE: str = os.getenv("STORAGE_TYPE", "memory")  # "redis" or "memory"
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")

    # MongoDB configuration for analytics
    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    MONGODB_DATABASE: str = os.getenv("MONGODB_DATABASE", "twitch_analytics")

    # Default streamers to monitor
    DEFAULT_STREAMERS: str = os.getenv("DEFAULT_STREAMERS", "")

    # API Security
    REQUIRE_API_KEY: bool = os.getenv("REQUIRE_API_KEY", "false").lower() == "true"
    API_KEY: str = os.getenv("API_KEY", "")

    class Config:
        env_file = ".env"


settings = Settings()
