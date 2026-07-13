"""
Chatwoot Application API client.

Pushes Júlia's WhatsApp replies into the matching Chatwoot conversation
using her dedicated Agent Bot token — NOT a human agent's token. Chatwoot
tags messages sent this way as sender_type="AgentBot", which is how
app/routers/chatwoot.py tells her replies apart from a real human typing
in the Chatwoot UI (sender_type="User"). Mixing the two up would make
Júlia's own messages look like a human takeover and pause her forever.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def find_conversation(phone: str) -> tuple[str, str] | None:
    """Look up the most recent Chatwoot conversation for a phone number,
    restricted to this agent's inbox (settings.chatwoot_inbox_id).

    The Chatwoot account also hosts other inboxes on different WABAs (e.g.
    "Amanda - Keth"). A contact search by phone is account-wide, so without
    this filter a phone number that also exists in another inbox could send
    Júlia's reply into the wrong conversation. Returns (account_id,
    conversation_id) or None if no conversation exists in THIS inbox."""
    if not settings.chatwoot_api_url or not settings.chatwoot_account_id or not settings.chatwoot_api_token:
        return None

    account_id = settings.chatwoot_account_id
    base = settings.chatwoot_api_url.rstrip("/")
    headers = {"api_access_token": settings.chatwoot_api_token, "Content-Type": "application/json"}

    # /contacts/filter with attribute_key=phone_number + equal_to reliably
    # returns zero results even for an exact match (confirmed against
    # production) — Chatwoot's phone_number filter comparison doesn't match
    # the "+55..." string the way a plain search does. /contacts/search
    # does match correctly, so we use digits-only (matches Chatwoot's own
    # WhatsApp Cloud contact_inboxes.source_id format, e.g. "5522998030398").
    digits = "".join(c for c in phone if c.isdigit())

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{base}/api/v1/accounts/{account_id}/contacts/search",
                headers=headers,
                params={"q": digits},
            )
            if resp.status_code >= 400:
                logger.warning(f"Chatwoot contact search error {resp.status_code}: {resp.text[:200]}")
                return None
            contacts = resp.json().get("payload", [])
            if not contacts:
                return None
            contact_id = contacts[0]["id"]

            resp2 = await client.get(
                f"{base}/api/v1/accounts/{account_id}/contacts/{contact_id}/conversations",
                headers=headers,
            )
            if resp2.status_code >= 400:
                return None
            conversations = resp2.json().get("payload", [])
            inbox_conversations = [
                c for c in conversations
                if str(c.get("inbox_id")) == str(settings.chatwoot_inbox_id)
            ]
            if not inbox_conversations:
                return None
            conversation_id = inbox_conversations[0]["id"]
            return str(account_id), str(conversation_id)
    except Exception:
        logger.exception(f"Chatwoot conversation lookup failed for {phone}")
        return None


async def send_chatwoot_message(account_id: str, conversation_id: str, content: str) -> bool:
    """Post a message into a Chatwoot conversation as Júlia's Agent Bot."""
    if not settings.chatwoot_api_url or not settings.chatwoot_bot_token:
        logger.debug("Chatwoot bot token not configured — skipping Chatwoot sync")
        return False

    url = (
        f"{settings.chatwoot_api_url.rstrip('/')}"
        f"/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    )
    headers = {
        "api_access_token": settings.chatwoot_bot_token,
        "Content-Type": "application/json",
    }
    payload = {"content": content, "message_type": "outgoing", "private": False}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code < 400:
                logger.debug(f"Chatwoot message sent to conv {conversation_id}")
                return True
            logger.warning(f"Chatwoot API error {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as exc:
        logger.warning(f"Chatwoot API unreachable: {exc}")
        return False
