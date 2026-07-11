"""
Meta WhatsApp webhook — receives incoming messages, button clicks, and
status updates from the WhatsApp Cloud API.

GET  /webhooks/meta — verification challenge (required by Meta setup)
POST /webhooks/meta — incoming notifications (messages + statuses)
"""

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response

from app.config import settings
from app.services.journey_engine import process_response
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

            # ── Process incoming messages ──
            for msg in messages:
                await _handle_incoming_message(msg)

            # ── Process status updates ──
            for status in statuses:
                await _handle_status_update(status)

    # Always return 200 — Meta expects a quick ack
    return {"status": "ok"}


async def _handle_incoming_message(msg: dict) -> None:
    """Extract phone, text, and button from an incoming WhatsApp message.
    Routes to journey engine AND/OR Júlia agent depending on context."""
    from_number = msg.get("from")
    if not from_number:
        return

    phone = normalize_phone(from_number)
    msg_type = msg.get("type", "unknown")

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

    if needs_agent and text_body:
        await _call_agent_and_reply(phone=phone, message=text_body)
    elif needs_agent and button_text:
        await _call_agent_and_reply(phone=phone, message=button_text)


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
    """Call Júlia agent and send the reply via WhatsApp."""
    from app.agent.engine import julia_reply
    from app.services.whatsapp import send_text

    try:
        result = await julia_reply(phone=phone, message=message)
        reply = result.get("reply", "")

        if reply:
            await send_text(phone=phone, body=reply)
            logger.info(f"Agent reply sent to {phone}: {reply[:80]}...")
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
