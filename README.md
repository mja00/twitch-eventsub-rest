# Twitch EventSub REST API

A Python FastAPI server that listens to Twitch's EventSub system for stream live events. The server can monitor multiple Twitch streamers and store events in either Redis or in-memory for testing.

## Features

- 🎮 **Twitch EventSub Integration**: Listen to stream.online and stream.offline events
- 🔧 **Flexible Storage**: Redis for production, in-memory for testing
- 📡 **REST API**: Manage streamers and view events via HTTP endpoints
- 🔍 **Live Stream Status**: Real-time status checking for any Twitch streamer
- ⏰ **Smart Updates**: Background refresh of live stream data every 5 minutes
- 🚀 **Startup Initialization**: Populate stream status on server start
- 🐳 **Docker Ready**: Complete Docker setup with docker-compose
- 🔐 **Secure**: Webhook signature verification
- 📊 **Event History**: Store and retrieve recent stream events

## Quick Start

### 1. Clone and Setup

```bash
git clone <repository-url>
cd twitch-pubsub-rest
cp .env.example .env
```

### 2. Configure Environment

Edit `.env` with your Twitch application credentials:

```env
TWITCH_CLIENT_ID=your_twitch_client_id_here
TWITCH_CLIENT_SECRET=your_twitch_client_secret_here
WEBHOOK_SECRET=your-webhook-secret-here
WEBHOOK_URL=https://your-domain.com/webhooks/eventsub
```

### 3. Run with Docker

```bash
# Start with Redis (recommended for production)
docker-compose up -d

# Or start in memory mode for testing
STORAGE_TYPE=memory docker-compose up -d
```

### 4. Test the API

```bash
# Add a streamer to monitor
curl -X POST "http://localhost:8000/streamers/shroud"

# Check any streamer's current status
curl "http://localhost:8000/streamers/shroud/status"

# View all live streams
curl "http://localhost:8000/streams/live"

# List monitored streamers
curl "http://localhost:8000/streamers"

# Get recent events
curl "http://localhost:8000/events"
```

**With API Key Protection (when enabled):**
```bash
# All API calls require Authorization header
curl -H "Authorization: Bearer your-api-key" "http://localhost:8000/streams/live"

# Add streamer with API key
curl -H "Authorization: Bearer your-api-key" -X POST "http://localhost:8000/streamers/shroud"
```

## API Endpoints

### Health & Status
- `GET /` - API info
- `GET /health` - Health check

> **Note**: Health endpoints are always accessible without API key

### Stream Status & Live Streams
- `GET /streamers/{username}/status` - Get current status for any streamer
- `GET /streams/live` - Get all currently live streams we know about

### Streamers Management
- `POST /streamers/{username}` - Add streamer to monitor
- `DELETE /streamers/{username}` - Remove streamer
- `GET /streamers` - List all monitored streamers

### Events
- `GET /events?limit=50` - Get recent stream events
- `POST /webhooks/eventsub` - EventSub webhook endpoint (used by Twitch)

> **Note**: The webhook endpoint is always accessible without API key (Twitch needs access)

### Response Examples

**Individual Streamer Status:**
```json
{
  "user_id": "12345",
  "username": "shroud",
  "display_name": "shroud",
  "is_live": true,
  "stream_data": {
    "viewer_count": 25000,
    "game_name": "VALORANT",
    "title": "Ranked matches"
  },
  "last_updated": "2024-01-15T11:45:23.123456",
  "last_event_type": "stream.online",
  "source": "storage"
}
```

**All Live Streams:**
```json
{
  "live_streams": [
    {
      "user_id": "12345",
      "username": "shroud",
      "display_name": "shroud",
      "is_live": true,
      "stream_data": {
        "viewer_count": 25000,
        "game_name": "VALORANT"
      },
      "last_updated": "2024-01-15T11:45:23.123456"
    }
  ],
  "count": 1
}
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TWITCH_CLIENT_ID` | Your Twitch application client ID | Required |
| `TWITCH_CLIENT_SECRET` | Your Twitch application client secret | Required |
| `WEBHOOK_SECRET` | Secret for webhook signature verification | `your-webhook-secret` |
| `WEBHOOK_URL` | Public URL for EventSub webhooks | Required for production |
| `STORAGE_TYPE` | Storage backend (`redis` or `memory`) | `memory` |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379` |
| `DEFAULT_STREAMERS` | Comma-separated list of streamers to monitor | Empty |
| `REQUIRE_API_KEY` | Enable API key authentication (`true` or `false`) | `false` |
| `API_KEY` | API key for protected endpoints | Empty |

### Twitch Application Setup

1. Go to [Twitch Developers Console](https://dev.twitch.tv/console/apps)
2. Create a new application
3. Set OAuth Redirect URLs to `http://localhost` (not used but required)
4. Copy Client ID and Client Secret to your `.env` file

### Webhook URL Setup

For production, you need a publicly accessible HTTPS endpoint:

1. Deploy your server to a cloud provider
2. Set up HTTPS (required by Twitch)
3. Update `WEBHOOK_URL` in your environment

**For Development with Ngrok:**
```bash
# Start your FastAPI server
uvicorn app.main:app --host 0.0.0.0 --port 8000

# In another terminal, start ngrok
ngrok http 8000

# Copy the HTTPS URL from ngrok and update your .env
WEBHOOK_URL=https://abc123.ngrok.io/webhooks/eventsub
```

## Development

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run in development mode
STORAGE_TYPE=memory uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Project Structure

```
app/
├── main.py          # FastAPI application and routes
├── config.py        # Configuration and settings
├── models.py        # Pydantic models
├── storage.py       # Storage abstraction (Redis/Memory)
├── streamers.py     # Streamer management
├── twitch_api.py    # Twitch API client
└── eventsub.py      # EventSub webhook verification
```

## Event Types

The server listens for these Twitch EventSub events:

- `stream.online` - When a streamer goes live
- `stream.offline` - When a streamer goes offline

Each event is stored with:
- Event ID and type
- Broadcaster information (ID, login, display name)
- Timestamp
- Original event data from Twitch

## How It Works

### Startup Process
1. **Load Configuration**: Reads environment variables and default streamers
2. **Connect to Storage**: Initializes Redis or in-memory storage
3. **Initialize Stream Status**: Queries Twitch API for current status of all monitored streamers
4. **Start EventSub Subscriptions**: Creates webhooks for monitored streamers
5. **Launch Background Tasks**: Starts 5-minute refresh cycle for live streams

### Real-time Updates
- **EventSub Webhooks**: Twitch sends instant notifications when streams go live/offline
- **Background Refresh**: Every 5 minutes, updates viewer counts, games, titles for live streams
- **API Fallback**: Unknown streamers are queried from Twitch API and cached

### Data Flow
```
Twitch EventSub → Webhook → Update Storage → Background Refresh → API Responses
                     ↓
              Instant Status Updates
```

## Storage

### Redis (Production)
- Persistent storage across restarts
- Efficient sorted sets for event history
- Hash maps for streamer configurations and stream status
- Automatic cleanup of old events (keeps last 1000)

### Memory (Testing)
- Fast in-memory storage
- No persistence across restarts
- Good for development and testing
- Automatic cleanup (keeps last 1000 events)

## Docker Deployment

The included `docker-compose.yml` provides:

- **FastAPI application** with health checks
- **Redis** with persistence
- **Volume mounting** for Redis data
- **Environment configuration**
- **Automatic restarts**

```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f app

# Stop services
docker-compose down
```

## Monitoring

### Health Checks
- Application: `GET /health`
- Docker: Built-in health checks
- Storage connectivity verification

### Logs
- Structured logging with timestamps
- Event processing logs
- Stream status initialization on startup
- Background update progress
- Error handling and reporting

### Log Examples
```
INFO: Initializing status for 35 monitored streamers...
INFO: Initialized shroud: live - VALORANT - 25000 viewers
INFO: Initialized ninja: offline
INFO: Stream online: shroud (shroud)
INFO: Updated stream status for pokimane: live
```

## Security

- **Webhook Verification**: All EventSub webhooks are verified using HMAC-SHA256
- **Environment Variables**: Sensitive data stored in environment variables
- **Non-root User**: Docker container runs as non-root user
- **HTTPS Required**: Twitch requires HTTPS for webhook endpoints in production

## License

MIT License - see LICENSE file for details