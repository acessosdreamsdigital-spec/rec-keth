"""
Security utilities — API key auth, JWT validation, rate limit helpers.
"""

import os
import secrets

import httpx
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
jwt_bearer = HTTPBearer(auto_error=False)


async def verify_api_key(key: str = Security(api_key_header)) -> str:
    """Validate x-api-key header against configured API_KEY."""
    if not settings.api_key:
        return "dev-no-key"
    if not key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing x-api-key header")
    if not secrets.compare_digest(key, settings.api_key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")
    return key


async def verify_jwt(credentials: HTTPAuthorizationCredentials | None = Security(jwt_bearer)) -> str:
    """
    Validate Supabase Auth JWT from Authorization: Bearer <token>.
    Returns the user's email if valid. Redirect to login if invalid.
    Used by dashboard endpoints.
    """
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token JWT ausente")

    token = credentials.credentials
    supabase_url = os.environ.get("SUPABASE_URL", "https://tzqjezbsysetkmzxpuet.supabase.co")
    supabase_key = os.environ.get("SUPABASE_KEY", "")

    url = f"{supabase_url}/auth/v1/user"
    headers = {"apikey": supabase_key, "Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token JWT inválido ou expirado")
            user = resp.json()
    except httpx.TransportError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Serviço de autenticação indisponível")

    return user.get("email", "")
