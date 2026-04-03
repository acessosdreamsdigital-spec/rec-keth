"""
Dashboard API — all endpoints consumed by the frontend at /dashboard.

Endpoints:
  GET /dashboard/           → serve index.html
  GET /dashboard/stats      → KPI cards
  GET /dashboard/sessions   → paginated sessions table (filterable by email)
  GET /dashboard/funnel     → conversions by message number
  GET /dashboard/product-stats → per-product aggregation
  GET /dashboard/daily      → sessions + conversions per day (timeline chart)

All endpoints accept the same optional query filters:
  start_date, end_date, platform, product (template_prefix), status, email
"""

import os
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.database import get_supabase

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "static")


@router.get("/", include_in_schema=False)
async def serve_dashboard():
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


# ── helpers ────────────────────────────────────────────────────────────────

def _apply_base_filters(query, start_date, end_date, platform, product):
    if start_date:
        query = query.gte("created_at", start_date.isoformat())
    if end_date:
        query = query.lte("created_at", f"{end_date.isoformat()}T23:59:59")
    if platform:
        query = query.eq("platform", platform)
    if product:
        query = query.eq("template_prefix", product)
    return query


def _default_start() -> date:
    return date.today() - timedelta(days=30)


# ── endpoints ──────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    platform: Optional[str] = Query(default=None),
    product: Optional[str] = Query(default=None),
):
    """Top-level KPI cards."""
    db = await get_supabase()

    sd = start_date or _default_start()
    ed = end_date or date.today()

    query = db.table("recovery_sessions").select("status, messages_sent, amount_cents")
    query = _apply_base_filters(query, sd, ed, platform, product)
    result = await query.execute()
    sessions = result.data

    total = len(sessions)
    converted = sum(1 for s in sessions if s["status"] == "converted")
    active = sum(1 for s in sessions if s["status"] == "active")
    exhausted = sum(1 for s in sessions if s["status"] == "exhausted")
    cancelled = sum(1 for s in sessions if s["status"] == "cancelled")
    messages_sent = sum(s.get("messages_sent") or 0 for s in sessions)
    total_revenue_cents = sum(s.get("amount_cents") or 0 for s in sessions)
    recovered_cents = sum(
        s.get("amount_cents") or 0 for s in sessions if s["status"] == "converted"
    )

    return {
        "total_sessions": total,
        "converted": converted,
        "active": active,
        "exhausted": exhausted,
        "cancelled": cancelled,
        "conversion_rate": round(converted / total * 100, 1) if total > 0 else 0.0,
        "messages_sent": messages_sent,
        "total_revenue_cents": total_revenue_cents,
        "recovered_cents": recovered_cents,
    }


@router.get("/sessions")
async def get_sessions(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    platform: Optional[str] = Query(default=None),
    product: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    email: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, le=100),
):
    """Paginated sessions table with email search."""
    db = await get_supabase()

    sd = start_date or _default_start()
    ed = end_date or date.today()

    offset = (page - 1) * limit

    query = db.table("v_recovery_overview").select("*", count="exact")
    query = _apply_base_filters(query, sd, ed, platform, product)

    if status:
        query = query.eq("status", status)
    if email:
        query = query.ilike("email", f"%{email}%")

    query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
    result = await query.execute()

    total = result.count or 0
    return {
        "data": result.data,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // limit)),  # ceiling division
    }


@router.get("/funnel")
async def get_funnel(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    platform: Optional[str] = Query(default=None),
    product: Optional[str] = Query(default=None),
):
    """Conversions by message number — shows which message converts most."""
    db = await get_supabase()

    sd = start_date or _default_start()
    ed = end_date or date.today()

    query = db.table("recovery_sessions").select("messages_sent").eq("status", "converted")
    query = _apply_base_filters(query, sd, ed, platform, product)
    result = await query.execute()

    funnel = {1: 0, 2: 0, 3: 0}
    for s in result.data:
        n = s.get("messages_sent") or 0
        if n in funnel:
            funnel[n] += 1

    return [{"message_number": k, "converted": v} for k, v in funnel.items()]


@router.get("/product-stats")
async def get_product_stats(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    platform: Optional[str] = Query(default=None),
):
    """Aggregated performance per product."""
    db = await get_supabase()

    sd = start_date or _default_start()
    ed = end_date or date.today()

    query = db.table("recovery_sessions").select(
        "template_prefix, product_name, status, amount_cents"
    )
    query = _apply_base_filters(query, sd, ed, platform, None)
    result = await query.execute()

    stats: dict = {}
    for s in result.data:
        prefix = s["template_prefix"]
        if prefix not in stats:
            stats[prefix] = {
                "template_prefix": prefix,
                "product_name": s["product_name"],
                "total": 0,
                "converted": 0,
                "active": 0,
                "exhausted": 0,
                "recovered_cents": 0,
            }
        entry = stats[prefix]
        entry["total"] += 1
        if s["status"] == "converted":
            entry["converted"] += 1
            entry["recovered_cents"] += s.get("amount_cents") or 0
        elif s["status"] == "active":
            entry["active"] += 1
        elif s["status"] == "exhausted":
            entry["exhausted"] += 1

    for entry in stats.values():
        entry["conversion_rate"] = (
            round(entry["converted"] / entry["total"] * 100, 1)
            if entry["total"] > 0 else 0.0
        )

    return sorted(stats.values(), key=lambda x: x["total"], reverse=True)


@router.get("/daily")
async def get_daily(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    platform: Optional[str] = Query(default=None),
    product: Optional[str] = Query(default=None),
):
    """Sessions and conversions per day for the timeline chart."""
    db = await get_supabase()

    sd = start_date or _default_start()
    ed = end_date or date.today()

    query = db.table("recovery_sessions").select("created_at, status, amount_cents")
    query = _apply_base_filters(query, sd, ed, platform, product)
    result = await query.execute()

    daily: dict = defaultdict(lambda: {"sessions": 0, "converted": 0, "recovered_cents": 0})
    for s in result.data:
        day = (s.get("created_at") or "")[:10]
        if not day:
            continue
        daily[day]["sessions"] += 1
        if s["status"] == "converted":
            daily[day]["converted"] += 1
            daily[day]["recovered_cents"] += s.get("amount_cents") or 0

    return sorted(
        [{"day": k, **v} for k, v in daily.items()],
        key=lambda x: x["day"],
    )
