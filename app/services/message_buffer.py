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
