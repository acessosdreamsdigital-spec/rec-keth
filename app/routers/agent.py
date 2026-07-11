"""
FastAPI router for Júlia — WhatsApp conversational agent.

POST /webhooks/agent — receives messages routed to Júlia for
human-like sales recovery conversations.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from app.agent.engine import clear_session, julia_reply
from app.database import get_supabase
from app.utils.phone import normalize_phone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["agent"])


async def _lookup_lead(phone: str) -> dict | None:
    """Look up lead by phone in the leads table for name + context."""
    db = await get_supabase()
    result = await db.table("leads").select("*").eq("whatsapp", phone).execute()
    if result.data:
        return result.data[0]
    return None


async def _lookup_journey(phone: str) -> dict | None:
    """Get active journey context for this phone."""
    db = await get_supabase()
    result = await (
        db.table("contact_journeys")
        .select("*")
        .eq("phone", phone)
        .eq("status", "active")
        .execute()
    )
    if result.data:
        return result.data[0]
    return None


@router.post("/agent")
async def agent_webhook(request: Request):
    """
    Receives messages that should be handled by Júlia (the AI agent).

    Expected JSON body:
    {
        "phone": "5521984103779",
        "message": "Quero saber mais sobre o Conteudo Wow",
        "name": "Quézia"  // optional
    }

    This endpoint is called by the journey engine when it detects
    a response that needs human-like conversation (open questions,
    "Quero conhecer", "Tenho uma dúvida", etc.).
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    phone_raw = body.get("phone", "")
    message = body.get("message", "").strip()
    name = body.get("name", "")

    if not phone_raw or not message:
        raise HTTPException(status_code=400, detail="Missing phone or message")

    phone = normalize_phone(phone_raw)

    # Enrich with lead data if available
    if not name:
        lead = await _lookup_lead(phone)
        if lead:
            name = lead.get("nome", "")

    logger.info(f"Agent request: phone={phone} msg={message[:80]}...")

    result = await julia_reply(phone=phone, message=message, full_name=name)

    return {
        "status": "ok",
        "reply": result["reply"],
        "link_type": result["link_type"],
        "link_url": result["link_url"],
    }


@router.post("/agent/reset")
async def reset_session(request: Request):
    """Reset Júlia's conversation memory for a phone number."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    phone_raw = body.get("phone", "")
    if not phone_raw:
        raise HTTPException(status_code=400, detail="Missing phone")

    phone = normalize_phone(phone_raw)
    await clear_session(phone)
    return {"status": "ok", "message": f"Session cleared for {phone}"}
