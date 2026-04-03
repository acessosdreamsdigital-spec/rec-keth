"""
Core recovery logic.

Responsibilities:
- Normalize and upsert contacts
- Deduplicate recovery sessions (one active session per contact + template_prefix)
- Create sessions and schedule 3 messages
- Handle purchase approval: mark sessions as converted, cancel pending messages

Message scheduling:
  Default (abandoned_cart, pix, payment_refused):
    msg 1 — immediate, msg 2 — +24h, msg 3 — +48h

  Boleto (billet_created / bank_slip_generated):
    msg 1 — +24h, msg 2 — +48h, msg 3 — +72h
    Rationale: boleto is valid for ~24h so we wait for it to expire
    before starting the recovery sequence.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.database import get_supabase
from app.utils.phone import normalize_phone

logger = logging.getLogger(__name__)

# Product name keyword → WhatsApp template prefix
# Checked in order; first match wins. Case-insensitive substring match.
PRODUCT_TEMPLATE_MAP: list[tuple[str, str]] = [
    ("combo wow", "rec_combo_wow"),
    ("capcut wow", "rec_capcut_wow"),
    ("conteúdo wow", "rec_conteudo_wow"),
    ("conteudo wow", "rec_conteudo_wow"),
    ("meu primeiro infoproduto", "rec_mpi"),
]

# Default offsets: immediate → +24h → +48h
DEFAULT_OFFSETS = [
    timedelta(0),
    timedelta(hours=24),
    timedelta(hours=48),
]

# Boleto offsets: wait 24h for boleto to expire, then +48h → +72h
BOLETO_OFFSETS = [
    timedelta(hours=24),
    timedelta(hours=48),
    timedelta(hours=72),
]

# Platform event types that represent boleto generation
BOLETO_EVENT_TYPES = {"billet_created", "bank_slip_generated"}


def resolve_template_prefix(product_name: str) -> Optional[str]:
    name = product_name.lower()
    for keyword, prefix in PRODUCT_TEMPLATE_MAP:
        if keyword in name:
            return prefix
    return None


async def upsert_contact(phone: str, full_name: str, email: str) -> dict:
    db = await get_supabase()
    result = await db.table("contacts").select("*").eq("phone", phone).execute()

    if result.data:
        contact = result.data[0]
        # Update name/email only if the new values are non-empty
        updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if full_name and full_name != contact.get("full_name"):
            updates["full_name"] = full_name
        if email and email != contact.get("email"):
            updates["email"] = email
        if len(updates) > 1:
            await db.table("contacts").update(updates).eq("id", contact["id"]).execute()
        return contact

    inserted = await db.table("contacts").insert(
        {"phone": phone, "full_name": full_name, "email": email}
    ).execute()
    return inserted.data[0]


async def has_active_session(contact_id: str, template_prefix: str) -> bool:
    """
    Dedup guard: returns True if there is already an active recovery
    session for this contact + product (identified via template_prefix).
    This prevents double-triggering when both Kiwify and Assiny fire
    events for the same product.
    """
    db = await get_supabase()
    result = (
        await db.table("recovery_sessions")
        .select("id")
        .eq("contact_id", contact_id)
        .eq("template_prefix", template_prefix)
        .eq("status", "active")
        .execute()
    )
    return len(result.data) > 0


async def _create_session(
    contact_id: str,
    platform: str,
    platform_order_id: Optional[str],
    platform_event_type: str,
    trigger_event: str,
    product_id: str,
    product_name: str,
    template_prefix: str,
    amount_cents: Optional[int],
    raw_payload: dict,
) -> dict:
    db = await get_supabase()
    result = await db.table("recovery_sessions").insert(
        {
            "contact_id": contact_id,
            "platform": platform,
            "platform_order_id": platform_order_id,
            "platform_event_type": platform_event_type,
            "trigger_event": trigger_event,
            "product_id": product_id,
            "product_name": product_name,
            "template_prefix": template_prefix,
            "amount_cents": amount_cents,
            "status": "active",
            "messages_sent": 0,
            "raw_payload": raw_payload,
        }
    ).execute()
    return result.data[0]


async def _schedule_messages(
    session_id: str,
    contact_id: str,
    phone: str,
    template_prefix: str,
    offsets: list,
) -> None:
    db = await get_supabase()
    now = datetime.now(timezone.utc)
    rows = [
        {
            "recovery_session_id": session_id,
            "contact_id": contact_id,
            "message_number": i,
            "template_name": f"{template_prefix}{i}",
            "phone": phone,
            "scheduled_for": (now + offset).isoformat(),
            "status": "pending",
        }
        for i, offset in enumerate(offsets, start=1)
    ]
    await db.table("scheduled_messages").insert(rows).execute()


async def handle_recovery_event(
    platform: str,
    platform_order_id: Optional[str],
    platform_event_type: str,
    trigger_event: str,
    product_id: str,
    product_name: str,
    amount_cents: Optional[int],
    phone_raw: str,
    full_name: str,
    email: str,
    raw_payload: dict,
) -> dict:
    """
    Entry point for all recovery triggers (abandoned_cart, waiting_payment,
    payment_refused) from both Kiwify and Assiny.

    Returns a dict with {"status": "created"|"skipped", ...}.
    """
    if not phone_raw:
        logger.warning(f"Recovery event with no phone: platform={platform} event={platform_event_type}")
        return {"status": "skipped", "reason": "no_phone"}

    phone = normalize_phone(phone_raw)

    template_prefix = resolve_template_prefix(product_name)
    if not template_prefix:
        logger.warning(f"No template for product '{product_name}' — skipping")
        return {"status": "skipped", "reason": "unknown_product", "product": product_name}

    contact = await upsert_contact(phone, full_name, email)
    contact_id = contact["id"]

    if await has_active_session(contact_id, template_prefix):
        logger.info(
            f"Active session exists for contact={contact_id} prefix={template_prefix} — skipping"
        )
        return {"status": "skipped", "reason": "already_active"}

    session = await _create_session(
        contact_id=contact_id,
        platform=platform,
        platform_order_id=platform_order_id,
        platform_event_type=platform_event_type,
        trigger_event=trigger_event,
        product_id=product_id,
        product_name=product_name,
        template_prefix=template_prefix,
        amount_cents=amount_cents,
        raw_payload=raw_payload,
    )

    offsets = BOLETO_OFFSETS if platform_event_type in BOLETO_EVENT_TYPES else DEFAULT_OFFSETS
    await _schedule_messages(session["id"], contact_id, phone, template_prefix, offsets)

    logger.info(
        f"Recovery session created: id={session['id']} "
        f"platform={platform} event={platform_event_type} product={product_name} phone={phone} "
        f"schedule={'boleto' if offsets is BOLETO_OFFSETS else 'default'}"
    )
    return {"status": "created", "session_id": session["id"]}


async def handle_purchase_approved(
    platform: str,
    platform_order_id: Optional[str],
    product_name: str,
    phone_raw: str,
    raw_payload: dict,
) -> dict:
    """
    Called when a purchase is confirmed on either platform.
    Marks all active sessions for this contact+product as converted
    and cancels pending scheduled messages.
    """
    if not phone_raw:
        return {"status": "skipped", "reason": "no_phone"}

    phone = normalize_phone(phone_raw)
    template_prefix = resolve_template_prefix(product_name)
    if not template_prefix:
        # Unknown product — not a recoverable product, nothing to convert
        return {"status": "skipped", "reason": "unknown_product"}

    db = await get_supabase()

    contact_result = await db.table("contacts").select("id").eq("phone", phone).execute()
    if not contact_result.data:
        # No contact = no active session, nothing to do
        return {"status": "skipped", "reason": "contact_not_found"}

    contact_id = contact_result.data[0]["id"]
    now = datetime.now(timezone.utc).isoformat()

    sessions_result = (
        await db.table("recovery_sessions")
        .select("id")
        .eq("contact_id", contact_id)
        .eq("template_prefix", template_prefix)
        .eq("status", "active")
        .execute()
    )

    if not sessions_result.data:
        return {"status": "skipped", "reason": "no_active_session"}

    session_ids = [s["id"] for s in sessions_result.data]

    # Mark sessions as converted
    await (
        db.table("recovery_sessions")
        .update(
            {
                "status": "converted",
                "converted_at": now,
                "converted_order_id": platform_order_id,
                "updated_at": now,
            }
        )
        .in_("id", session_ids)
        .execute()
    )

    # Cancel all pending messages for those sessions
    await (
        db.table("scheduled_messages")
        .update({"status": "cancelled"})
        .in_("recovery_session_id", session_ids)
        .eq("status", "pending")
        .execute()
    )

    logger.info(
        f"Converted sessions {session_ids} for phone={phone} "
        f"prefix={template_prefix} order={platform_order_id}"
    )
    return {"status": "converted", "session_ids": session_ids}
