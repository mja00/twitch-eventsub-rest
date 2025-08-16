from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import settings

# Security scheme for API key authentication
api_key_header = HTTPBearer(auto_error=False)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(api_key_header),
):
    """Verify API key for protected endpoints"""
    # Skip verification if API key protection is disabled
    if not settings.REQUIRE_API_KEY:
        return True

    # Check if API key is configured
    if not settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key authentication is enabled but no API key is configured",
        )

    # Check if credentials were provided
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Provide in Authorization header as 'Bearer YOUR_API_KEY'",
        )

    # Verify the API key
    if credentials.credentials != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )

    return True
