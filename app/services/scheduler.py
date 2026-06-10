"""
Background scheduler.

Claims due scheduled_messages atomically (so multiple replicas never double-send)
and, for each:
  1. Verify the parent session is still active (not converted/cancelled)
  2. Send the WhatsApp template via Meta API
  3. On success: mark 'sent', increment messages_sent, exhaust after message 3
  4. On transient failure: back off and retry up to MESSAGE_MAX_ATTEMPTS
  5. On permanent failure (or attempts exhausted): mark 'failed'

A second loop periodically syncs Meta cost (pricing_analytics) into meta_cost_daily.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.database import get_supabase
from app.services.meta_analytics import sync_costs
from app.services.whatsapp import WhatsAppSendError, send_template

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _load_sessions(db, session_ids: list[str]) -> dict[str, dict]:
    """Fetch status + messages_sent for the given sessions, keyed by id."""
    if not session_ids:
        return {}
    result = (
        await db.table("recovery_sessions")
        .select("id, status, messages_sent")
        .in_("id", session_ids)
        .execute()
    )
    return {s["id"]: s for s in result.data}


async def _retry_or_fail(db, msg: dict, error: str, transient: bool) -> None:
    attempts = (msg.get("attempts") or 0) + 1
    can_retry = transient and attempts < settings.message_max_attempts

    if can_retry:
        backoff = settings.message_retry_base_minutes * (2 ** (attempts - 1))
        next_at = (_now() + timedelta(minutes=backoff)).isoformat()
        await (
            db.table("scheduled_messages")
            .update(
                {
                    "status": "pending",
                    "attempts": attempts,
                    "claimed_at": None,
                    "scheduled_for": next_at,
                    "error_message": error,
                }
            )
            .eq("id", msg["id"])
            .execute()
        )
        logger.warning(
            f"Retry msg {msg['id']} (attempt {attempts}/{settings.message_max_attempts}) "
            f"in {backoff}min: {error}"
        )
    else:
        await (
            db.table("scheduled_messages")
            .update({"status": "failed", "attempts": attempts, "error_message": error})
            .eq("id", msg["id"])
            .execute()
        )
        logger.error(f"Failed msg {msg['id']} after {attempts} attempt(s): {error}")


async def _process_due_messages() -> None:
    db = await get_supabase()

    # Atomically claim due messages (flips them to 'processing').
    claimed = await db.rpc(
        "claim_due_messages", {"p_limit": settings.scheduler_batch_size}
    ).execute()
    messages = claimed.data or []
    if not messages:
        return

    logger.info(f"Scheduler: claimed {len(messages)} message(s)")

    sessions = await _load_sessions(db, list({m["recovery_session_id"] for m in messages}))
    # Track increments locally so multiple messages of the same session in one
    # batch increment correctly (instead of all writing the same stale value).
    sent_counter = {sid: (s.get("messages_sent") or 0) for sid, s in sessions.items()}

    for msg in messages:
        session = sessions.get(msg["recovery_session_id"]) or {}
        session_status = session.get("status")

        # Session was converted/cancelled/exhausted while this message waited.
        if session_status != "active":
            await (
                db.table("scheduled_messages")
                .update({"status": "cancelled"})
                .eq("id", msg["id"])
                .execute()
            )
            logger.info(
                f"Cancelled msg {msg['id']} — session {msg['recovery_session_id']} "
                f"is {session_status}"
            )
            continue

        try:
            response = await send_template(msg["phone"], msg["template_name"])
        except WhatsAppSendError as exc:
            await _retry_or_fail(db, msg, str(exc), transient=exc.transient)
            continue
        except Exception as exc:  # unexpected — treat as transient, retry
            await _retry_or_fail(db, msg, f"unexpected: {exc}", transient=True)
            continue

        wa_id = (response.get("messages") or [{}])[0].get("id")
        sent_at = _now().isoformat()

        await (
            db.table("scheduled_messages")
            .update({"status": "sent", "sent_at": sent_at, "whatsapp_message_id": wa_id})
            .eq("id", msg["id"])
            .execute()
        )

        # Increment session counter (locally tracked → correct within a batch).
        sid = msg["recovery_session_id"]
        sent_counter[sid] = sent_counter.get(sid, 0) + 1
        current_sent = sent_counter[sid]
        session_update: dict = {"messages_sent": current_sent, "updated_at": sent_at}
        if current_sent >= 3:
            session_update["status"] = "exhausted"
            session["status"] = "exhausted"  # reflect locally for later batch msgs

        await (
            db.table("recovery_sessions")
            .update(session_update)
            .eq("id", sid)
            .execute()
        )

        logger.info(
            f"Sent msg#{msg['message_number']} template={msg['template_name']} "
            f"to={msg['phone']} wa_id={wa_id}"
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


async def run_cost_sync(interval_seconds: int) -> None:
    """Runs forever, syncing Meta cost into meta_cost_daily every `interval_seconds`."""
    logger.info(f"Cost sync started (interval={interval_seconds}s)")
    while True:
        try:
            await sync_costs()
        except Exception as exc:
            logger.error(f"Cost sync error: {exc}")
        await asyncio.sleep(interval_seconds)
