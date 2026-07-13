"""
Chatwoot webhook — detects when a human agent takes over a conversation.

Customer messages are already fully handled via /webhooks/meta (Meta calls
rec-keth directly; see app/routers/meta.py). This endpoint only cares about
messages a real human agent types into the Chatwoot UI:

- sender_type == "Contact"  → the customer, already processed via /webhooks/meta.
  Ignored here, otherwise the journey engine + Júlia would run twice per message.
- sender_type == "AgentBot" → Júlia's own replies, posted via her dedicated bot
  token (see app/services/chatwoot_client.py). Ignored here, otherwise she'd
  detect her own message as a "human takeover" and pause herself.
- sender_type == "User"     → a real human agent replying in the Chatwoot UI.
  This is the only case we act on.

The Chatwoot account also hosts other inboxes on different WABAs/numbers
(e.g. "Amanda - Keth"). This webhook fires for the whole account, so events
are scoped to settings.chatwoot_inbox_id — a human reply in another inbox
must never pause a Júlia ("Recuperação e Up") journey.

When a human agent replies, the journey is permanently marked as handed off
(status="suporte"). That status no longer matches the status="active" checks
used everywhere else (journey engine, scheduler, agent routing), so nothing
will schedule a template or call Júlia for this contact again — even after
the customer replies again. There is no automatic resume from "suporte".
"""

from __future__ import annotations

import logging
from datetime import datetime as dt, timezone as tz

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.database import get_supabase
from app.utils.phone import normalize_phone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["chatwoot"])


@router.post("/chatwoot")
async def chatwoot_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Chatwoot can send either a single event or an array
    events = body if isinstance(body, list) else [body]

    for event in events:
        if event.get("message_type") != "outgoing":
            continue
        if event.get("private"):
            continue  # internal notes never reach the customer
        if event.get("sender_type") != "User":
            continue  # Contact (customer) or AgentBot (Júlia) — not a human agent

        contact = event.get("contact") or {}
        conversation = event.get("conversation") or {}
        sender = event.get("sender") or {}

        inbox_id = (event.get("inbox") or {}).get("id") or conversation.get("inbox_id")
        if str(inbox_id) != str(settings.chatwoot_inbox_id):
            continue  # event from another inbox (e.g. "Amanda - Keth") — not ours

        phone_raw = (
            contact.get("phone_number")
            or contact.get("identifier")
            or (conversation.get("contact_inbox") or {}).get("source_id")
            or ""
        )
        if not phone_raw:
            continue

        phone = normalize_phone(phone_raw)
        await _handle_human_takeover(phone, sender.get("name") or "agente")

    return {"status": "ok"}


async def _handle_human_takeover(phone: str, agent_name: str) -> None:
    """Permanently hand this conversation to a human — cancels pending
    automated messages and marks the journey so nothing auto-resumes it."""
    db = await get_supabase()
    result = await (
        db.table("contact_journeys")
        .select("id")
        .eq("phone", phone)
        .in_("status", ["active", "paused"])
        .execute()
    )

    if not result.data:
        return

    journey_id = result.data[0]["id"]
    await (
        db.table("contact_journeys")
        .update({"status": "suporte", "updated_at": dt.now(tz.utc).isoformat()})
        .eq("id", journey_id)
        .execute()
    )
    await (
        db.table("journey_messages")
        .update({"status": "cancelled"})
        .eq("journey_id", journey_id)
        .eq("status", "pending")
        .execute()
    )
    logger.info(f"Human takeover for {phone} by {agent_name} — Júlia paused permanently")
