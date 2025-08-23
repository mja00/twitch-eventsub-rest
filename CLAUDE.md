# Claude Instructions for Twitch PubSub REST Repository

## Project Overview

This is a **Twitch EventSub REST API** built with FastAPI that monitors Twitch streamers and provides real-time stream status information. The application listens to Twitch's EventSub webhooks for `stream.online` and `stream.offline` events and stores this data in either Redis or in-memory storage.

## Key Technologies & Dependencies

- **FastAPI** (0.104.1) - Web framework
- **Uvicorn** (0.24.0) - ASGI server
- **Redis** (5.0.1) - Production storage backend
- **Pydantic** (2.5.0) - Data validation and serialization
- **HTTPX** (0.25.2) - HTTP client for Twitch API calls
- **Python-dotenv** (1.0.0) - Environment variable management
- **MongoDB Motor** (3.3.2) - Async MongoDB driver for analytics
- **PyMongo** (4.6.0) - MongoDB integration and aggregation

## Project Structure

```
app/
├── main.py              # FastAPI application, routes, and middleware
├── config.py            # Configuration management and settings
├── models.py            # Pydantic models for core data validation
├── analytics_models.py  # MongoDB/Analytics Pydantic models
├── storage.py           # Storage abstraction (Redis/Memory)
├── analytics.py         # MongoDB analytics service and calculations
├── streamers.py         # Streamer management and EventSub subscriptions
├── twitch_api.py        # Twitch API client and authentication
├── eventsub.py          # EventSub webhook verification
├── auth.py              # API key authentication
└── routes/              # Organized API route modules
    ├── basic.py         # Health and root endpoints
    ├── webhooks.py      # EventSub webhook handling
    ├── streamers.py     # Streamer management endpoints
    ├── events.py        # Event history endpoints
    ├── streams.py       # Live stream endpoints
    ├── admin.py         # Admin/management endpoints
    └── analytics.py     # Analytics and statistics endpoints
```

## Core Functionality

### 1. EventSub Webhook Processing
- Receives and verifies Twitch EventSub webhooks
- Handles `stream.online` and `stream.offline` events
- Stores events with broadcaster information and timestamps
- Responds to webhook challenges for subscription verification

### 2. Streamer Management
- Add/remove streamers to monitor
- Automatic EventSub subscription creation and validation
- Background status updates every 5 minutes
- Startup initialization of all monitored streamers

### 3. REST API Endpoints
- **Health**: `/health` - Application health check
- **Stream Status**: `/streamers/{username}/status` - Get current stream status
- **Live Streams**: `/streams/live` - Get all currently live streams
- **Streamer Management**: `POST/DELETE /streamers/{username}` - Add/remove streamers
- **Events**: `/events` - Get stored events with filtering options
- **Analytics**: `/analytics/*` - Comprehensive stream analytics and statistics
- **Admin**: `/admin/*` - Subscription management and monitoring

### 4. Storage System
- **Redis**: Production storage with persistence for streamer configs and events
- **Memory**: Development/testing storage (non-persistent)
- **MongoDB**: Analytics storage for stream sessions, snapshots, and aggregated statistics
- Automatic cleanup of old events (keeps last 1000)
- Efficient data structures for fast queries

### 5. Analytics System
- **Stream Session Tracking**: Complete session lifecycle from online to offline events
- **Real-time Snapshots**: Viewer count and metadata captured every 5 minutes during streams
- **Aggregated Statistics**: Total hours, average viewers, max concurrent viewers per streamer
- **Historical Data**: Searchable stream history with detailed viewer statistics
- **MongoDB Integration**: Optimized collections with proper indexing for time-series data

## Development Guidelines

### When Making Changes

1. **Follow FastAPI Best Practices**
   - Use Pydantic models for request/response validation
   - Implement proper error handling with HTTPException
   - Use dependency injection for shared resources
   - Add comprehensive logging

2. **Storage Considerations**
   - Always use the storage abstraction layer in `storage.py`
   - Support both Redis and memory backends
   - Handle connection errors gracefully
   - Implement proper cleanup and disconnection

3. **Twitch API Integration**
   - Use the `twitch_api.py` module for all Twitch API calls
   - Handle rate limiting and authentication properly
   - Cache responses when appropriate
   - Implement retry logic for failed requests

4. **EventSub Webhook Security**
   - Always verify webhook signatures using `eventsub.py`
   - Handle challenge verification correctly
   - Validate event data before processing
   - Log all webhook activities for debugging

### Code Style & Patterns

1. **Async/Await Pattern**
   - Use async functions for I/O operations
   - Avoid blocking operations in async contexts
   - Use `asyncio.create_task()` for background operations

2. **Error Handling**
   - Use try/catch blocks for external API calls
   - Log errors with appropriate context
   - Return meaningful HTTP status codes
   - Implement graceful degradation

3. **Configuration Management**
   - Use environment variables for configuration
   - Validate configuration on startup
   - Provide sensible defaults
   - Use the settings class in `config.py`

4. **Logging**
   - Use structured logging with appropriate levels
   - Include relevant context in log messages
   - Log both successful operations and errors
   - Use consistent log message formats

### Testing Considerations

1. **Storage Testing**
   - Test both Redis and memory backends
   - Verify data persistence and cleanup
   - Test connection error scenarios

2. **API Testing**
   - Test all endpoints with valid and invalid data
   - Verify authentication and authorization
   - Test rate limiting and error responses

3. **Webhook Testing**
   - Test signature verification
   - Test challenge response handling
   - Test event processing and storage

## Common Tasks & Patterns

### Adding New Endpoints

```python
@app.get("/new-endpoint")
async def new_endpoint(
    param: str = Query(..., description="Parameter description"),
    api_key: str = Depends(verify_api_key)  # If authentication needed
):
    try:
        # Your logic here
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Error in new endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
```

### Adding New Event Types

1. Update `models.py` with new event models
2. Add event type constants in `streamers.py`
3. Update EventSub subscription creation logic
4. Add event processing in webhook handler
5. Update storage methods if needed

### Adding New Storage Operations

```python
# In storage.py
async def new_operation(self, key: str, data: dict) -> bool:
    try:
        if isinstance(self.storage, RedisStorage):
            # Redis implementation
            await self.storage.redis.hset(key, mapping=data)
        else:
            # Memory implementation
            self.storage.data[key] = data
        return True
    except Exception as e:
        logger.error(f"Storage operation failed: {e}")
        return False
```

## Environment Configuration

### Required Environment Variables
- `TWITCH_CLIENT_ID` - Twitch application client ID
- `TWITCH_CLIENT_SECRET` - Twitch application client secret
- `WEBHOOK_SECRET` - Secret for webhook signature verification
- `WEBHOOK_URL` - Public URL for EventSub webhooks

### Optional Environment Variables
- `STORAGE_TYPE` - `redis` or `memory` (default: `memory`)
- `REDIS_URL` - Redis connection URL (default: `redis://localhost:6379`)
- `MONGODB_URL` - MongoDB connection URL (default: `mongodb://localhost:27017`)
- `MONGODB_DATABASE` - MongoDB database name (default: `twitch_analytics`)
- `MONGO_INITDB_ROOT_USERNAME` - MongoDB root username for Docker
- `MONGO_INITDB_ROOT_PASSWORD` - MongoDB root password for Docker
- `DEFAULT_STREAMERS` - Comma-separated list of streamers to monitor
- `REQUIRE_API_KEY` - Enable API key authentication (`true` or `false`)
- `API_KEY` - API key for protected endpoints

## Docker & Deployment

### Docker Setup
- Use the provided `Dockerfile` and `docker-compose.yml`
- Redis is included in docker-compose for production
- Environment variables can be set in docker-compose or .env file
- Health checks are configured for both app and Redis

### Production Considerations
- Always use Redis for production storage
- Set up HTTPS for webhook endpoints (required by Twitch)
- Configure proper logging and monitoring
- Set up backup and recovery procedures
- Monitor EventSub subscription health

## Troubleshooting Guide

### Common Issues

1. **Webhook Verification Failures**
   - Check `WEBHOOK_SECRET` configuration
   - Verify webhook URL is accessible
   - Check logs for signature verification errors

2. **EventSub Subscription Issues**
   - Use admin endpoints to verify subscriptions
   - Check Twitch application permissions
   - Verify webhook URL is HTTPS in production
   - Fixed: Subscription validation now handles pagination correctly (retrieves all pages)
   - Fixed: Inactive streamers are now included in subscription validation

3. **Storage Connection Issues**
   - Check Redis connection settings
   - Verify Redis is running and accessible
   - Check network connectivity
   - Check MongoDB connection for analytics features

4. **API Authentication Issues**
   - Verify API key configuration
   - Check Authorization header format
   - Ensure `REQUIRE_API_KEY` is set correctly

5. **Analytics Issues**
   - Use recalculate endpoint for ongoing streams with incorrect viewer stats
   - Fixed: Viewer statistics now calculated from snapshots, not just completed sessions
   - Fixed: DateTime compatibility issues resolved (now uses timezone.utc)

6. **Python Compatibility Issues**
   - Fixed: Replaced datetime.UTC with timezone.utc for broader Python version support
   - Fixed: Proper factory functions for Pydantic default datetime fields

### Debugging Tips

1. **Enable Debug Logging**
   ```python
   logging.basicConfig(level=logging.DEBUG)
   ```

2. **Check Storage State**
   ```bash
   # For Redis
   redis-cli KEYS "*"
   redis-cli HGETALL "streamer:username"
   ```

3. **Monitor Webhook Requests**
   - Check application logs for webhook processing
   - Verify challenge responses are sent correctly
   - Monitor EventSub subscription status

## Security Considerations

1. **Webhook Security**
   - Always verify webhook signatures
   - Use strong webhook secrets
   - Validate event data before processing

2. **API Security**
   - Use API key authentication for sensitive endpoints
   - Implement rate limiting if needed
   - Validate all input data

3. **Environment Security**
   - Never commit sensitive data to version control
   - Use environment variables for secrets
   - Rotate API keys and secrets regularly

## Performance Optimization

1. **Storage Optimization**
   - Use Redis sorted sets for efficient event queries
   - Implement proper data cleanup
   - Cache frequently accessed data

2. **API Optimization**
   - Use async operations for I/O
   - Implement proper connection pooling
   - Add caching where appropriate

3. **Background Tasks**
   - Use asyncio tasks for background operations
   - Implement proper task cancellation
   - Monitor task performance and errors

## Contributing Guidelines

1. **Code Quality**
   - Follow PEP 8 style guidelines
   - Add type hints to all functions
   - Write comprehensive docstrings
   - Add unit tests for new functionality

2. **Documentation**
   - Update README.md for new features
   - Add API documentation for new endpoints
   - Document configuration changes
   - Update this CLAUDE.md file if needed

3. **Testing**
   - Test with both storage backends
   - Verify webhook functionality
   - Test error scenarios
   - Ensure backward compatibility

## Quick Reference

### Key Files
- `app/main.py` - Main application and routes
- `app/storage.py` - Storage abstraction layer (Redis/Memory)
- `app/analytics.py` - MongoDB analytics service
- `app/streamers.py` - Streamer management logic
- `app/twitch_api.py` - Twitch API integration with pagination support
- `app/eventsub.py` - Webhook verification
- `app/analytics_models.py` - MongoDB data models

### Key Classes
- `StreamerManager` - Manages streamers and subscriptions
- `AnalyticsService` - MongoDB analytics operations
- `Storage` - Abstract storage interface
- `RedisStorage` / `MemoryStorage` - Storage implementations
- `TwitchAPI` - Twitch API client with pagination support
- `StreamSession` / `StreamSnapshot` / `StreamerStats` - Analytics data models

### Key Functions
- `verify_signature()` - Webhook signature verification
- `verify_api_key()` - API key authentication
- `get_storage()` - Storage dependency injection
- `get_real_ip()` - Client IP extraction
- `recalculate_streamer_stats()` - Force refresh analytics for ongoing streams
- `_update_streamer_stats()` - Calculate stats from sessions and snapshots

Remember to always test changes thoroughly and maintain backward compatibility when possible. The application is designed to be robust and handle various error scenarios gracefully.

## Documentation Maintenance

### README.md Updates
When making changes to the codebase, ensure the `README.md` file is kept up to date:

1. **New Features**: Add documentation for any new endpoints, features, or functionality
2. **API Changes**: Update API endpoint documentation, request/response examples, and parameters
3. **Configuration**: Document any new environment variables or configuration options
4. **Deployment**: Update deployment instructions if Docker or deployment processes change
5. **Examples**: Keep code examples and curl commands current and functional
6. **Troubleshooting**: Add new troubleshooting steps for any new features or common issues

### CLAUDE.md Structure Maintenance
This file itself should be maintained and updated as the project evolves:

1. **New Dependencies**: Update the "Key Technologies & Dependencies" section when adding new packages
2. **Project Structure**: Update the file structure diagram if new files are added or existing ones are reorganized
3. **Core Functionality**: Add new functionality descriptions to the appropriate sections
4. **Development Guidelines**: Update patterns and best practices as they evolve
5. **Common Tasks**: Add new code patterns and examples for frequently performed tasks
6. **Environment Variables**: Document any new configuration options
7. **Troubleshooting**: Add new common issues and their solutions
8. **Quick Reference**: Update key files, classes, and functions as they change

### Documentation Standards
- Keep both files synchronized in terms of feature descriptions
- Ensure all code examples are tested and functional
- Use consistent formatting and structure across both files
- Update version numbers and dependency information when they change
- Maintain the same level of detail and clarity in both documents

- Always use Black to format after any changes