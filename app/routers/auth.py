"""Authentication — Supabase Auth JWT login/logout."""

import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(tags=["auth"])

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "static")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://tzqjezbsysetkmzxpuet.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")


@router.get("/login", include_in_schema=False)
async def login_page():
    """Serve the login page."""
    return FileResponse(os.path.join(_STATIC_DIR, "login.html"))


@router.post("/auth/login")
async def do_login(request: Request):
    """Server-side login — proxies Supabase Auth with service_role key."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    email = body.get("email", "")
    password = body.get("password", "")

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")

    url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json={"email": email, "password": password}, headers=headers)
            if resp.status_code != 200:
                detail = "Credenciais inválidas"
                try:
                    err = resp.json()
                    detail = err.get("error_description") or err.get("msg") or detail
                except Exception:
                    pass
                raise HTTPException(status_code=401, detail=detail)
            data = resp.json()
    except httpx.TransportError:
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "expires_in": data.get("expires_in", 3600),
        "user": {"email": data.get("user", {}).get("email", email)},
    }


@router.post("/auth/verify")
async def verify_token(request: Request):
    """Verify a JWT token is still valid."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    token = body.get("token", "")
    if not token:
        raise HTTPException(status_code=400, detail="Token required")

    url = f"{SUPABASE_URL}/auth/v1/user"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=401, detail="Token inválido")
            user = resp.json()
    except httpx.TransportError:
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    return {"valid": True, "user": {"email": user.get("email", "")}}
