"""
Security utilities — API key auth, rate limit helpers.

Simple, effective "rice and beans" security:
- API key for admin/dashboard endpoints
- HMAC for webhooks (in security.py)
- Rate limiting via slowapi (in main.py)
"""

import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)


async def verify_api_key(key: str = Security(api_key_header)) -> str:
    """
    Validate x-api-key header against configured API_KEY.
    Returns the key if valid, raises 403 if not.
    """
    if not settings.api_key:
        # No key configured — allow all (dev mode)
        return "dev-no-key"

    if not key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing x-api-key header",
        )

    if not secrets.compare_digest(key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return key
