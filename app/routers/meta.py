"""
Meta WhatsApp webhook — receives incoming messages, button clicks, and
status updates from the WhatsApp Cloud API.

GET  /webhooks/meta — verification challenge (required by Meta setup)
POST /webhooks/meta — incoming notifications (messages + statuses)
"""

import asyncio
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response

from app.config import settings
from app.services.journey_engine import process_response
from app.services.message_buffer import buffer_and_debounce
from app.utils.phone import normalize_phone

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meta-webhook"])


def _verify_signature(body: bytes, signature_header: str) -> bool:
    """Validate X-Hub-Signature-256 HMAC-SHA256."""
    if not settings.meta_app_secret:
        logger.warning("META_APP_SECRET not set — skipping signature validation")
        return True
    try:
        expected_sig = hmac.new(
            key=settings.meta_app_secret.encode(),
            msg=body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        expected = f"sha256={expected_sig}"
        return hmac.compare_digest(expected.encode(), signature_header.encode())
    except Exception:
        logger.exception("Signature verification error")
        return False


@router.get("/webhooks/meta")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    """
    Meta sends a GET to verify the webhook URL.
    Must respond with the challenge string if verify_token matches.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_verify_token:
        logger.info("Meta webhook verified successfully")
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhooks/meta")
async def receive_webhook(
    request: Request,
    x_hub_signature_256: str = Header(default="", alias="X-Hub-Signature-256"),
):
    """
    Receives WhatsApp notifications:
    - messages: text, button, interactive replies
    - statuses: sent, delivered, read, failed

    Validates signature, then processes relevant events through the
    journey engine.
    """
    body = await request.body()

    # Validate signature
    if not _verify_signature(body, x_hub_signature_256):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in Meta webhook body")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Process each entry
    entries = data.get("entry", [])
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            statuses = value.get("statuses", [])
            profile_names = {
                c.get("wa_id"): (c.get("profile") or {}).get("name", "")
                for c in value.get("contacts", [])
                if c.get("wa_id")
            }

            # ── Process incoming messages ──
            for msg in messages:
                await _handle_incoming_message(msg, profile_names)

            # ── Forward to Chatwoot (transparent proxy) ──
            await _forward_to_chatwoot(body)

            # ── Process status updates ──
            for status in statuses:
                await _handle_status_update(status)

    # Always return 200 — Meta expects a quick ack
    return {"status": "ok"}


async def _is_human_takeover(phone: str) -> bool:
    """True once a human agent has replied via Chatwoot for this contact
    (status="suporte", set by app/routers/chatwoot.py). Sticky — there is
    no automatic resume, so Júlia stays silent even if the customer keeps
    messaging."""
    from app.database import get_supabase

    db = await get_supabase()
    result = await (
        db.table("contact_journeys")
        .select("id")
        .eq("phone", phone)
        .eq("status", "suporte")
        .limit(1)
        .execute()
    )
    return bool(result.data)


async def _pause_journey_for(phone: str) -> None:
    """Pause automated journey when student sends text (avoids template
    interruption during human/agent conversation)."""
    from app.database import get_supabase
    from datetime import datetime as dt, timezone as tz

    db = await get_supabase()
    result = await (
        db.table("contact_journeys")
        .select("id, status")
        .eq("phone", phone)
        .eq("status", "active")
        .execute()
    )
    if not result.data:
        return

    journey_id = result.data[0]["id"]
    await (
        db.table("contact_journeys")
        .update({
            "status": "paused",
            "updated_at": dt.now(tz.utc).isoformat(),
        })
        .eq("id", journey_id)
        .execute()
    )
    # Cancel pending messages so nothing fires during pause
    await (
        db.table("journey_messages")
        .update({"status": "cancelled"})
        .eq("journey_id", journey_id)
        .eq("status", "pending")
        .execute()
    )
    logger.info(f"Journey auto-paused for {phone}")


async def _resume_if_paused(phone: str) -> None:
    """Resume journey when student clicks a button (re-engaging with flow)."""
    from app.database import get_supabase
    from datetime import datetime as dt, timezone as tz

    db = await get_supabase()
    result = await (
        db.table("contact_journeys")
        .select("id")
        .eq("phone", phone)
        .eq("status", "paused")
        .execute()
    )
    if result.data:
        journey_id = result.data[0]["id"]
        await (
            db.table("contact_journeys")
            .update({
                "status": "active",
                "updated_at": dt.now(tz.utc).isoformat(),
            })
            .eq("id", journey_id)
            .execute()
        )
        logger.info(f"Journey RESUMED for {phone} — button clicked")


async def _forward_to_chatwoot(body: bytes) -> None:
    """Forward the original Meta payload to Chatwoot so human agents
    continue to receive messages normally."""
    if not settings.chatwoot_webhook_url:
        return

    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                settings.chatwoot_webhook_url,
                content=body,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code >= 400:
                logger.warning(f"Chatwoot forward returned {resp.status_code}")
    except Exception as exc:
        logger.warning(f"Chatwoot forward failed: {exc}")


async def _handle_incoming_message(msg: dict, profile_names: dict | None = None) -> None:
    """Extract phone, text, and button from an incoming WhatsApp message.
    Routes to journey engine AND/OR Júlia agent depending on context."""
    from_number = msg.get("from")
    if not from_number:
        return

    phone = normalize_phone(from_number)
    msg_type = msg.get("type", "unknown")

    # Durable record of everyone who has ever messaged us, regardless of
    # purchase history. contacts/contact_journeys were previously only
    # created on a Kiwify/Assiny purchase event — someone messaging with no
    # purchase history had zero permanent record; the Redis conversation
    # history (see app/agent/engine.py) expires after 7 days.
    try:
        from app.services.recovery import upsert_contact
        await upsert_contact(phone, (profile_names or {}).get(from_number, ""), "")
    except Exception:
        logger.exception(f"Error upserting contact for {phone}")

    if await _is_human_takeover(phone):
        logger.info(f"Skipping automation for {phone} — handed off to a human agent")
        return

    button_text: str | None = None
    text_body: str | None = None

    if msg_type == "text":
        text_body = msg.get("text", {}).get("body", "")
        logger.info(f"Incoming TEXT from {phone}: {text_body[:100] if text_body else ''}")
    elif msg_type == "button":
        button_text = msg.get("button", {}).get("text", "")
        logger.info(f"Incoming BUTTON from {phone}: {button_text}")
    elif msg_type == "interactive":
        interactive = msg.get("interactive", {})
        int_type = interactive.get("type")
        if int_type == "button_reply":
            button_text = interactive.get("button_reply", {}).get("title", "")
            logger.info(f"Incoming BUTTON_REPLY from {phone}: {button_text}")
        elif int_type == "list_reply":
            button_text = interactive.get("list_reply", {}).get("title", "")
            logger.info(f"Incoming LIST_REPLY from {phone}: {button_text}")
    else:
        logger.debug(f"Ignoring message type={msg_type} from {phone}")
        return

    # Text message = student is talking → pause journey so templates don't interrupt
    if msg_type == "text" and text_body:
        await _pause_journey_for(phone)

    # Button click = student engaging with journey → resume
    if button_text:
        await _resume_if_paused(phone)

    # Always process through journey engine first (updates state/tags)
    journey_result = None
    try:
        journey_result = await process_response(
            phone=phone,
            button_text=button_text,
            text_body=text_body,
        )
        logger.info(f"Journey: {phone} → {journey_result.get('transition', 'no_change')}")
    except Exception:
        logger.exception(f"Error processing journey response for {phone}")

    # Determine if we need the AI agent to reply
    needs_agent = _should_call_agent(journey_result, button_text)

    # A button click that doesn't need Júlia (e.g. "Não quero mais", a
    # journey engine action that just advances state) still won't trigger
    # _call_agent_and_reply below, which is the only other place profiling
    # runs. Without this, a lead who only ever clicks buttons would get
    # analyzed exactly once — at purchase time, before any signal existed
    # — and never again. Trigger here only when the agent path won't run,
    # so the 24h recency guard in analyze_lead isn't "used up" by a less
    # informed pass right before the better-informed one (post-reply).
    if not needs_agent and (button_text or text_body):
        from app.services.lead_analyzer import analyze_lead_background
        analyze_lead_background(phone)

    if needs_agent and text_body:
        # Debounce: a burst of fragments ("oi" / "tudo bem?" / "eu preciso
        # de...") collapses into one combined reply instead of Júlia
        # answering each fragment separately. Fire-and-forget so the Meta
        # webhook responds immediately instead of blocking on the debounce
        # window + LLM call + WhatsApp send.
        asyncio.create_task(buffer_and_debounce(phone, text_body, _call_agent_and_reply))
    elif needs_agent and button_text:
        asyncio.create_task(_call_agent_and_reply(phone, button_text))


def _should_call_agent(journey_result: dict | None, button_text: str | None) -> bool:
    """Determine if this message needs Júlia's AI response."""
    if not journey_result:
        return True  # no journey → agent handles

    action = journey_result.get("action", "")

    # Journey engine explicitly requests human/agent handoff
    if action in ("human_handoff", "continue_flow"):
        return True

    # If journey says "stop" (suporte, opted_out), don't call agent
    if action == "stop":
        return False

    # For open questions (no buttons), always engage agent
    if not button_text:
        return True

    return False


async def _call_agent_and_reply(phone: str, message: str) -> None:
    """Call Júlia agent, split her reply into WhatsApp-sized bubbles, and
    send each one — via Chatwoot when possible, direct Meta API otherwise.

    Inbox 7 in Chatwoot is a live WhatsApp Cloud channel using the SAME
    Meta credentials as this app: posting an "outgoing" message there makes
    Chatwoot itself deliver it over WhatsApp. Sending via both send_text()
    AND send_chatwoot_message() for the same chunk double-sends it to the
    customer — so this is either/or per chunk, never both."""
    from app.agent.engine import julia_reply
    from app.services.whatsapp import send_text
    from app.services.chatwoot_client import find_conversation, send_chatwoot_message
    from app.services.lead_analyzer import analyze_lead_background
    from app.utils.message_split import split_message

    try:
        result = await julia_reply(phone=phone, message=message)
        reply = result.get("reply", "")

        if reply:
            chunks = split_message(reply)
            conv = await find_conversation(phone)

            for i, chunk in enumerate(chunks):
                sent_via_chatwoot = False
                if conv:
                    account_id, conversation_id = conv
                    sent_via_chatwoot = await send_chatwoot_message(account_id, conversation_id, chunk)
                if not sent_via_chatwoot:
                    await send_text(phone=phone, body=chunk)
                if i < len(chunks) - 1:
                    await asyncio.sleep(1.2)

            logger.info(f"Agent reply sent to {phone} in {len(chunks)} part(s): {reply[:80]}...")

            # Background AI profiling (temperatura/ticket/estagio) — guarded
            # by a 24h recency check inside analyze_lead itself.
            analyze_lead_background(phone)
    except Exception:
        logger.exception(f"Error calling agent for {phone}")


async def _handle_status_update(status: dict) -> None:
    """Update journey_message status based on delivery/read receipts."""
    wa_id = status.get("id")
    new_status = status.get("status")  # sent, delivered, read, failed
    if not wa_id or not new_status:
        return

    from app.database import get_supabase
    db = await get_supabase()

    try:
        await (
            db.table("journey_messages")
            .update({"status": new_status})
            .eq("whatsapp_message_id", wa_id)
            .execute()
        )
        logger.debug(f"Status update: {wa_id} → {new_status}")
    except Exception:
        logger.exception(f"Error updating status for {wa_id}")
