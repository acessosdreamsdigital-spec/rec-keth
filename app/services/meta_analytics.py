"""
Meta cost sync.

Periodically pulls the WhatsApp Business Account `pricing_analytics` edge —
the authoritative source of what Meta actually charged (in USD) — and upserts a
daily snapshot into `meta_cost_daily`. This is what lets us reconcile real cost
against the messages we recorded as "sent" (which only means API-accepted).

Why polling instead of a status webhook: the number's webhook is already owned
by Chatwoot and Meta allows a single callback URL, so we read cost out-of-band.
"""

import logging
import time
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.database import get_supabase

logger = logging.getLogger(__name__)


async def fetch_cost_data_points(lookback_days: int) -> list[dict]:
    """Call pricing_analytics and return the raw data_points list."""
    end = int(time.time())
    start = end - lookback_days * 86_400

    fields = (
        f"pricing_analytics.start({start}).end({end})"
        ".granularity(DAILY)"
        '.dimensions(["PRICING_CATEGORY","PRICING_TYPE"])'
    )
    url = f"https://graph.facebook.com/{settings.meta_api_version}/{settings.meta_waba_id}"
    params = {"fields": fields, "access_token": settings.meta_access_token}

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

    return (data.get("pricing_analytics") or {}).get("data", [{}])[0].get("data_points", [])


async def sync_costs(lookback_days: int | None = None) -> int:
    """
    Fetch recent cost data and upsert one row per (day, category, type).
    Returns the number of rows written. No-op (returns 0) if WABA id is unset.
    """
    if not settings.meta_waba_id:
        logger.warning("Cost sync skipped: META_WABA_ID is not set")
        return 0

    lookback_days = lookback_days or settings.cost_sync_lookback_days
    points = await fetch_cost_data_points(lookback_days)
    if not points:
        logger.info("Cost sync: no data_points returned")
        return 0

    # Aggregate per (day, category, type) — granularity is daily but a day can
    # appear once per dimension combination.
    agg: dict[tuple, dict] = {}
    for p in points:
        start = p.get("start")
        if not start:
            continue
        day = datetime.fromtimestamp(start, tz=timezone.utc).date().isoformat()
        category = p.get("pricing_category") or "UNKNOWN"
        ptype = p.get("pricing_type") or "UNKNOWN"
        key = (day, category, ptype)

        row = agg.setdefault(
            key,
            {
                "day": day,
                "pricing_category": category,
                "pricing_type": ptype,
                "currency": p.get("currency"),
                "cost": 0.0,
                "volume": 0,
                "raw": p,
            },
        )
        row["cost"] += float(p.get("cost", 0) or 0)
        row["volume"] += int(p.get("volume", 0) or 0)

    rows = list(agg.values())
    db = await get_supabase()
    await (
        db.table("meta_cost_daily")
        .upsert(rows, on_conflict="day,pricing_category,pricing_type")
        .execute()
    )

    total = sum(r["cost"] for r in rows)
    logger.info(
        f"Cost sync: upserted {len(rows)} row(s), total≈{total:.2f} "
        f"over last {lookback_days}d"
    )
    return len(rows)
