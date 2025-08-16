# Twitch EventSub REST API

A Python FastAPI server that listens to Twitch's EventSub system for stream live events. The server can monitor multiple Twitch streamers and store events in either Redis or in-memory for testing.

## Features

- 🎮 **Twitch EventSub Integration**: Listen to stream.online and stream.offline events
- 🔧 **Flexible Storage**: Redis for production, in-memory for testing
- 📡 **REST API**: Manage streamers and view events via HTTP endpoints
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

### 4. Add Streamers to Monitor

```bash
# Add a streamer
curl -X POST "http://localhost:8000/streamers/shroud"

# List all streamers
curl "http://localhost:8000/streamers"

# Get recent events
curl "http://localhost:8000/events"
```

## API Endpoints

### Health & Status
- `GET /` - API info
- `GET /health` - Health check

### Streamers Management
- `POST /streamers/{username}` - Add streamer to monitor
- `DELETE /streamers/{username}` - Remove streamer
- `GET /streamers` - List all monitored streamers

### Events
- `GET /events?limit=50` - Get recent stream events
- `POST /webhooks/eventsub` - EventSub webhook endpoint (used by Twitch)

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

## Storage

### Redis (Production)
- Persistent storage across restarts
- Efficient sorted sets for event history
- Hash maps for streamer configurations
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
- Error handling and reporting

## Security

- **Webhook Verification**: All EventSub webhooks are verified using HMAC-SHA256
- **Environment Variables**: Sensitive data stored in environment variables
- **Non-root User**: Docker container runs as non-root user
- **HTTPS Required**: Twitch requires HTTPS for webhook endpoints in production

## License

MIT License - see LICENSE file for details