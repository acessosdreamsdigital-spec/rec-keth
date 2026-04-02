"""
Background scheduler.

Polls Supabase every N seconds for scheduled_messages that are due.
For each due message:
  1. Verify the parent session is still active (not converted/cancelled)
  2. Send the WhatsApp template via Meta API
  3. Update message status (sent / failed)
  4. Increment messages_sent on session; mark exhausted after message 3
"""

import asyncio
import logging
from datetime import datetime, timezone

from app.database import get_supabase
from app.services.whatsapp import send_template

logger = logging.getLogger(__name__)


async def _process_due_messages() -> None:
    db = await get_supabase()
    now = datetime.now(timezone.utc).isoformat()

    # Fetch pending messages that are due, joined with their session status
    result = (
        await db.table("scheduled_messages")
        .select("*, recovery_sessions(status, messages_sent)")
        .eq("status", "pending")
        .lte("scheduled_for", now)
        .execute()
    )

    if not result.data:
        return

    logger.info(f"Scheduler: {len(result.data)} message(s) due")

    for msg in result.data:
        session_info = msg.get("recovery_sessions") or {}
        session_status = session_info.get("status")

        # Session was converted or cancelled while this message was pending
        if session_status != "active":
            await (
                db.table("scheduled_messages")
                .update({"status": "cancelled"})
                .eq("id", msg["id"])
                .execute()
            )
            logger.info(
                f"Cancelled msg {msg['id']} — session {msg['recovery_session_id']} is {session_status}"
            )
            continue

        try:
            response = await send_template(msg["phone"], msg["template_name"])
            wa_id = (response.get("messages") or [{}])[0].get("id")

            sent_at = datetime.now(timezone.utc).isoformat()
            await (
                db.table("scheduled_messages")
                .update({"status": "sent", "sent_at": sent_at, "whatsapp_message_id": wa_id})
                .eq("id", msg["id"])
                .execute()
            )

            # Update session: increment messages_sent; exhaust after msg 3
            current_sent = (session_info.get("messages_sent") or 0) + 1
            session_update: dict = {
                "messages_sent": current_sent,
                "updated_at": sent_at,
            }
            if current_sent >= 3:
                session_update["status"] = "exhausted"

            await (
                db.table("recovery_sessions")
                .update(session_update)
                .eq("id", msg["recovery_session_id"])
                .execute()
            )

            logger.info(
                f"Sent msg#{msg['message_number']} template={msg['template_name']} "
                f"to={msg['phone']} wa_id={wa_id}"
            )

        except Exception as exc:
            logger.error(
                f"Failed to send msg {msg['id']} template={msg['template_name']} "
                f"to={msg['phone']}: {exc}"
            )
            await (
                db.table("scheduled_messages")
                .update({"status": "failed", "error_message": str(exc)})
                .eq("id", msg["id"])
                .execute()
            )


async def run_scheduler(interval_seconds: int = 30) -> None:
    """Runs forever, processing due messages every `interval_seconds`."""
    logger.info(f"Recovery scheduler started (interval={interval_seconds}s)")
    while True:
        try:
            await _process_due_messages()
        except Exception as exc:
            logger.error(f"Scheduler loop error: {exc}")
        await asyncio.sleep(interval_seconds)
