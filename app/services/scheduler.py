"""
Background scheduler.

Two main loops:
1. Recovery messages — claims due scheduled_messages (3-msg linear sequences)
2. Journey messages — claims due journey_messages (37-template state machine)

Plus a cost sync loop for Meta pricing_analytics.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.database import get_supabase
from app.services.journey_engine import evaluate_silence, schedule_next
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


async def _process_due_journey_messages() -> None:
    """
    Claims due journey_messages atomically and sends them via Meta API.
    After each successful send, calls schedule_next() to advance the state machine.
    """
    db = await get_supabase()

    claimed = await db.rpc(
        "claim_due_journey_messages", {"p_limit": settings.scheduler_batch_size}
    ).execute()
    messages = claimed.data or []
    if not messages:
        return

    logger.info(f"Journey scheduler: claimed {len(messages)} message(s)")

    # Load journeys to get full_name for template variables
    journey_ids = list({m["journey_id"] for m in messages})
    journey_result = await (
        db.table("contact_journeys")
        .select("id, full_name, status, current_state")
        .in_("id", journey_ids)
        .execute()
    )
    journeys = {j["id"]: j for j in (journey_result.data or [])}

    for msg in messages:
        journey = journeys.get(msg["journey_id"]) or {}

        # Journey was closed while this message waited
        if journey.get("status") != "active":
            await (
                db.table("journey_messages")
                .update({"status": "cancelled"})
                .eq("id", msg["id"])
                .execute()
            )
            continue

        # Build body variables with student's name
        full_name = journey.get("full_name", "") or ""
        first_name = full_name.split()[0] if full_name else ""

        try:
            response = await send_template(
                phone=msg["phone"],
                template_name=msg["template_name"],
                body_variables=[first_name] if first_name else None,
            )
        except WhatsAppSendError as exc:
            await _retry_or_fail_journey(db, msg, str(exc), transient=exc.transient)
            continue
        except Exception as exc:
            await _retry_or_fail_journey(db, msg, f"unexpected: {exc}", transient=True)
            continue

        wa_id = (response.get("messages") or [{}])[0].get("id")
        sent_at = _now().isoformat()

        await (
            db.table("journey_messages")
            .update({
                "status": "sent",
                "sent_at": sent_at,
                "whatsapp_message_id": wa_id,
            })
            .eq("id", msg["id"])
            .execute()
        )

        logger.info(
            f"Journey msg sent: {msg['template_name']} to={msg['phone']} "
            f"wa_id={wa_id} state={journey.get('current_state')}"
        )

        # Advance state machine — schedule next template
        try:
            result = await schedule_next(msg["journey_id"], msg["template_name"])
            logger.info(f"Journey next: {result}")
        except Exception:
            logger.exception(f"Error scheduling next after {msg['template_name']}")


async def _retry_or_fail_journey(db, msg: dict, error: str, transient: bool) -> None:
    """Retry or fail a journey message (same logic as recovery _retry_or_fail)."""
    attempts = (msg.get("attempts") or 0) + 1
    can_retry = transient and attempts < settings.message_max_attempts

    if can_retry:
        backoff = settings.message_retry_base_minutes * (2 ** (attempts - 1))
        next_at = (_now() + timedelta(minutes=backoff)).isoformat()
        await (
            db.table("journey_messages")
            .update({
                "status": "pending",
                "attempts": attempts,
                "claimed_at": None,
                "scheduled_for": next_at,
                "error_message": error,
            })
            .eq("id", msg["id"])
            .execute()
        )
        logger.warning(
            f"Journey retry msg {msg['id']} (attempt {attempts}/{settings.message_max_attempts}) "
            f"in {backoff}min: {error}"
        )
    else:
        await (
            db.table("journey_messages")
            .update({
                "status": "failed",
                "attempts": attempts,
                "error_message": error,
            })
            .eq("id", msg["id"])
            .execute()
        )
        logger.error(f"Journey failed msg {msg['id']} after {attempts} attempt(s): {error}")


async def _check_journey_silence() -> None:
    """
    Periodically scans active journeys for silence > 48h.
    If a student hasn't responded since the last message, transitions
    from ativacao/engajada → fria.
    """
    db = await get_supabase()

    # Find journeys with sent messages but no recent response
    result = await (
        db.table("contact_journeys")
        .select("id, current_state, last_message_sent_at, last_response_at")
        .eq("status", "active")
        .not_.is_("last_message_sent_at", "null")
        .execute()
    )

    journeys = result.data or []
    checked = 0

    for j in journeys:
        # Only check journeys in states that can transition to fria
        if j["current_state"] not in ("ativacao", "engajada"):
            continue
        try:
            res = await evaluate_silence(j["id"])
            if res.get("status") == "transitioned_to_fria":
                logger.info(f"Journey {j['id']}: silence → fria ({res.get('silence_hours', 0):.0f}h)")
            checked += 1
        except Exception:
            logger.exception(f"Error checking silence for journey {j['id']}")

    if checked:
        logger.debug(f"Silence check: {checked} journey(s) evaluated")


async def run_scheduler(interval_seconds: int = 30) -> None:
    """Runs forever, processing due recovery + journey messages every `interval_seconds`."""
    logger.info(f"Scheduler started (interval={interval_seconds}s)")
    while True:
        try:
            await _process_due_messages()          # recovery messages (existing)
            await _process_due_journey_messages()   # journey messages (new)
            await _check_journey_silence()          # auto-transition to fria
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
