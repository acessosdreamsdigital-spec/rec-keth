"""
Chatwoot webhook — receives messages forwarded from Chatwoot.

Chatwoot is the primary Meta webhook. It forwards to rec-keth via
its outgoing webhook integration. This endpoint processes:
- Incoming student messages → journey engine + Júlia agent
- Outgoing agent messages (fromMe) → pauses journey
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from app.database import get_supabase
from app.services.journey_engine import process_response
from app.utils.phone import normalize_phone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["chatwoot"])


@router.post("/chatwoot")
async def chatwoot_webhook(request: Request):
    """
    Receives message events from Chatwoot's outgoing webhook.

    Chatwoot sends a webhook for every message (incoming + outgoing).
    We process incoming student messages through the journey engine
    and Júlia agent. Agent replies are sent BACK through Chatwoot's
    API so they appear in the Chatwoot conversation view.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Chatwoot can send either a single event or an array
    events = body if isinstance(body, list) else [body]

    for event in events:
        message_type = event.get("message_type") or event.get("event", "")
        private = event.get("private", False)

        sender = event.get("sender") or {}
        contact = event.get("contact") or {}
        conversation = event.get("conversation") or {}
        account = event.get("account") or {}

        # Extract phone
        phone_raw = (
            sender.get("phone_number")
            or sender.get("identifier")
            or contact.get("phone_number")
            or contact.get("identifier")
            or ""
        )
        if not phone_raw:
            ci = conversation.get("contact_inbox") or {}
            phone_raw = ci.get("source_id") or ""
        if not phone_raw:
            continue

        phone = normalize_phone(phone_raw)
        content = event.get("content") or ""

        # Extract Chatwoot IDs for replying
        account_id = account.get("id")
        conversation_id = conversation.get("id") or conversation.get("display_id")

        # Determine direction
        from_me = (
            message_type == "outgoing"
            or sender.get("role") == "agent"
            or sender.get("type") == "user"
            or event.get("message", {}).get("sender_type") == "User"
        )

        if from_me:
            await _handle_agent_reply(phone)
        else:
            await _handle_student_message(phone, content, account_id, conversation_id)

    return {"status": "ok"}


async def _handle_agent_reply(phone: str) -> None:
    """Pause automated journey when a human agent replies."""
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
    # Cancel pending messages so nothing fires during human conversation
    await (
        db.table("journey_messages")
        .update({"status": "cancelled"})
        .eq("journey_id", journey_id)
        .eq("status", "pending")
        .execute()
    )
    logger.info(f"Journey paused for {phone} — agent is talking")


async def _handle_student_message(
    phone: str,
    content: str,
    account_id: str | None = None,
    conversation_id: str | None = None,
) -> None:
    """Process a student message through journey engine + Júlia agent."""
    await _resume_journey(phone)

    button_keywords = [
        "Acesso certo", "Preciso de ajuda", "Já editei", "Ainda não comecei",
        "Quero entender", "Quero conhecer", "Quero saber mais", "Agora não",
        "Quero o Feed Wow", "Quero os detalhes", "Quero o acesso",
        "Quero conversar", "Quero continuar", "Sem tempo agora",
        "Não quero mais", "Quero aprender", "Parar mensagens",
        "Tenho uma dúvida", "Quero avançar", "Pode chamar", "Prefiro não",
        "Enviar acesso", "Já consegui", "Deu certo", "Já comecei",
        "Iniciante", "Intermediário", "Avançado",
        "Falta de tempo", "Dificuldade técnica", "Outro motivo",
        "Uso hoje", "Ainda não uso",
    ]

    button_text = None
    text_body = content
    if content.strip() in button_keywords:
        button_text = content.strip()
        text_body = None

    try:
        result = await process_response(
            phone=phone, button_text=button_text, text_body=text_body,
        )
        logger.info(f"Journey: {phone} → {result.get('transition', 'no_change')}")
    except Exception:
        logger.exception(f"Journey error for {phone}")

    if text_body and not button_text:
        await _call_agent(phone, text_body, account_id, conversation_id)


async def _resume_journey(phone: str) -> None:
    """Resume paused journey when student sends a new message."""
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
        logger.info(f"Journey resumed for {phone}")


async def _call_agent(
    phone: str,
    message: str,
    account_id: str | None = None,
    conversation_id: str | None = None,
) -> None:
    """Route a text message to Júlia agent and send reply via Chatwoot API
    so the reply appears in Chatwoot's conversation view."""
    from app.agent.engine import julia_reply

    try:
        result = await julia_reply(phone=phone, message=message)
        reply = result.get("reply", "")
        if reply:
            # Send via Chatwoot API so message appears in Chatwoot UI
            if account_id and conversation_id:
                sent = await _send_chatwoot_message(account_id, conversation_id, reply)
                if not sent:
                    # Fallback: send directly via WhatsApp
                    from app.services.whatsapp import send_text
                    await send_text(phone=phone, body=reply)
            else:
                # No Chatwoot context — send directly
                from app.services.whatsapp import send_text
                await send_text(phone=phone, body=reply)
            logger.info(f"Agent reply sent to {phone}: {reply[:80]}...")
    except Exception:
        logger.exception(f"Agent error for {phone}")


async def _send_chatwoot_message(
    account_id: str | int,
    conversation_id: str | int,
    content: str,
) -> bool:
    """Send a message through Chatwoot's API so it appears in the conversation."""
    import httpx
    from app.config import settings

    if not settings.chatwoot_api_url or not settings.chatwoot_api_token:
        logger.warning("Chatwoot API not configured — message not sent to Chatwoot")
        return False

    url = (
        f"{settings.chatwoot_api_url.rstrip('/')}"
        f"/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    )
    headers = {
        "api_access_token": settings.chatwoot_api_token,
        "Content-Type": "application/json",
    }
    payload = {
        "content": content,
        "message_type": "outgoing",
        "private": False,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code < 400:
                logger.debug(f"Chatwoot message sent to conv {conversation_id}")
                return True
            else:
                logger.warning(f"Chatwoot API error {resp.status_code}: {resp.text[:200]}")
                return False
    except Exception as exc:
        logger.warning(f"Chatwoot API unreachable: {exc}")
        return False
