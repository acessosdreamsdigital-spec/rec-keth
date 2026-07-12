"""
Message buffer — debounces rapid-fire WhatsApp fragments from a single
customer into one combined message before Júlia replies.

People type "oi" / "tudo bem?" / "eu preciso de..." as separate WhatsApp
messages instead of one block. Without this, Júlia would answer each
fragment on its own, out of context. Backed by Redis (not an in-process
dict) because rec-keth can run more than one instance on Railway — a
later fragment can land on a different instance than the first one.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 8
_BUFFER_TTL = 120  # safety net so a buffer can never leak forever
_STALE_GRACE_SECONDS = 15  # how much past DEBOUNCE_SECONDS before we call a buffer abandoned


async def buffer_and_debounce(
    phone: str,
    text: str,
    on_flush: Callable[[str, str], Awaitable[None]],
) -> None:
    """
    Append `text` to phone's buffer and (re)start the debounce window.

    Every fragment schedules its own delayed flush. Only the task holding
    the *latest* token actually flushes — earlier in-flight tasks for the
    same phone see their token superseded by a newer fragment and exit
    quietly. A burst of fragments therefore collapses into a single call
    to `on_flush(phone, combined_text)`.
    """
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        buffer_key = f"julia:buffer:{phone}"
        token_key = f"julia:buffer:token:{phone}"

        await r.rpush(buffer_key, text)
        await r.expire(buffer_key, _BUFFER_TTL)

        token = str(time.time())
        await r.set(token_key, token, ex=_BUFFER_TTL)

        await asyncio.sleep(DEBOUNCE_SECONDS)

        current = await r.get(token_key)
        if current != token:
            return  # a newer fragment arrived — its own task will flush

        messages = await r.lrange(buffer_key, 0, -1)
        await r.delete(buffer_key, token_key)

        if not messages:
            return

        combined = "\n".join(messages)
        logger.info(f"Flushing {len(messages)} buffered message(s) for {phone}")
        await on_flush(phone, combined)
    except Exception:
        logger.exception(f"Message buffer error for {phone}")
    finally:
        await r.aclose()


async def recover_stale_buffers(on_flush: Callable[[str, str], Awaitable[None]]) -> int:
    """
    Safety net for buffers whose debounce task died before it could flush —
    most commonly a deploy restarting the container while a task was mid
    `asyncio.sleep(DEBOUNCE_SECONDS)`. Without this, that customer's message
    just sits in Redis until _BUFFER_TTL expires, silently, with no reply
    ever sent.

    Called periodically from the scheduler loop (see run_scheduler). A
    token older than DEBOUNCE_SECONDS + _STALE_GRACE_SECONDS means its own
    task should have already flushed it and didn't — safe to flush here.
    """
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    recovered = 0
    try:
        async for token_key in r.scan_iter(match="julia:buffer:token:*"):
            token = await r.get(token_key)
            if not token:
                continue
            try:
                age = time.time() - float(token)
            except ValueError:
                continue
            if age < DEBOUNCE_SECONDS + _STALE_GRACE_SECONDS:
                continue  # still within its normal window — its own task owns it

            phone = token_key[len("julia:buffer:token:"):]
            buffer_key = f"julia:buffer:{phone}"

            # Delete the token first so a genuinely-still-running task (e.g.
            # slow OpenAI call, not a dead one) that wakes up after us sees
            # its token gone and quietly no-ops instead of double-flushing.
            deleted = await r.delete(token_key)
            if not deleted:
                continue  # another sweep/task already claimed it

            messages = await r.lrange(buffer_key, 0, -1)
            await r.delete(buffer_key)
            if not messages:
                continue

            combined = "\n".join(messages)
            logger.warning(
                f"Recovered stale buffer for {phone} ({len(messages)} msg, "
                f"{age:.0f}s old) — its debounce task likely died mid-wait"
            )
            await on_flush(phone, combined)
            recovered += 1
    except Exception:
        logger.exception("Error recovering stale message buffers")
    finally:
        await r.aclose()
    return recovered
