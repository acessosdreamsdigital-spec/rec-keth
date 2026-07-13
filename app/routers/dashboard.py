"""
Dashboard API — all endpoints consumed by the frontend at /dashboard.

Endpoints:
  GET /dashboard/                → serve index.html
  GET /dashboard/stats           → KPI cards
  GET /dashboard/sessions        → paginated sessions table
  GET /dashboard/funnel          → conversions by message number
  GET /dashboard/product-stats   → per-product aggregation
  GET /dashboard/daily           → sessions + conversions per day
  GET /dashboard/journey/stats   → journey KPI cards
  GET /dashboard/journey/leads   → paginated leads with search/filters
  GET /dashboard/journey/lead/{phone} → single lead deep view
  GET /dashboard/journey/daily   → journeys + messages per day
  GET /dashboard/journey/products → product distribution
  GET /dashboard/journey/insights → lead intelligence summary
"""

import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.database import get_supabase

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# All timestamps are stored in UTC (app writes datetime.now(timezone.utc)
# everywhere). The business — and everyone reading this dashboard — is in
# São Paulo, so "today" and every date-range filter/bucket must be computed
# in that timezone, not the server's (UTC on Railway). Getting this wrong
# means the last ~3h of each São Paulo day silently vanish from filters,
# and "hoje" shows empty for the last ~3h of every day.
SP_TZ = ZoneInfo("America/Sao_Paulo")


def _today_sp() -> date:
    return datetime.now(SP_TZ).date()


def _sp_day_start_utc_iso(d: date) -> str:
    """UTC instant corresponding to 00:00 on `d` in São Paulo time."""
    return datetime(d.year, d.month, d.day, tzinfo=SP_TZ).astimezone(timezone.utc).isoformat()


def _sp_day_end_utc_iso(d: date) -> str:
    """UTC instant corresponding to the start of the NEXT São Paulo day
    (exclusive upper bound) — i.e. 00:00 on d+1 in São Paulo time."""
    next_day = datetime(d.year, d.month, d.day, tzinfo=SP_TZ) + timedelta(days=1)
    return next_day.astimezone(timezone.utc).isoformat()


def _sp_day_str(iso_str: str) -> str:
    """Convert a stored UTC timestamp to its São Paulo calendar day (YYYY-MM-DD)."""
    if not iso_str:
        return ""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.astimezone(SP_TZ).date().isoformat()

# Serves the static shell (index.html) — kept on a separate, unauthenticated
# router because the browser's page navigation never carries the JWT bearer
# token; the page's own JS reads it from localStorage for the data calls below.
public_router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "static")


@public_router.get("/", include_in_schema=False)
async def serve_dashboard(key: str = Query(default=None)):
    # Optional: validate ?key=xxx in URL, store in page for AJAX calls
    # Page is read-only — no sensitive ops
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@public_router.get("/templates-view", include_in_schema=False)
async def serve_templates_view():
    """Manual de templates — same public-shell pattern as serve_dashboard;
    the page's own JS fetches /dashboard/templates with the JWT bearer."""
    return FileResponse(os.path.join(_STATIC_DIR, "templates.html"))


# ── helpers ────────────────────────────────────────────────────────────────

def _apply_base_filters(query, start_date, end_date, platform, product):
    if start_date:
        query = query.gte("created_at", _sp_day_start_utc_iso(start_date))
    if end_date:
        query = query.lt("created_at", _sp_day_end_utc_iso(end_date))
    if platform:
        query = query.eq("platform", platform)
    if product:
        query = query.eq("template_prefix", product)
    return query


def _default_start() -> date:
    # Default window is the current day (dashboard opens on "today").
    return _today_sp()


def _default_journey_start() -> date:
    # Journey views show the live pipeline/current state of all leads, not
    # "leads created today" — default to no lower bound instead of today.
    return date(2020, 1, 1)


async def _fetch_all(table, columns, sd, ed, platform, product, extra=None):
    """
    Fetch ALL matching rows, paginating past PostgREST's 1000-row cap.
    Without this, aggregations on busy periods (>1000 sessions) would be
    silently truncated and undercount.
    """
    db = await get_supabase()
    page_size = 1000
    offset = 0
    rows: list[dict] = []
    while True:
        query = db.table(table).select(columns)
        query = _apply_base_filters(query, sd, ed, platform, product)
        if extra is not None:
            query = extra(query)
        result = await query.range(offset, offset + page_size - 1).execute()
        batch = result.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        offset += page_size


# ── existing endpoints ─────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    platform: Optional[str] = Query(default=None),
    product: Optional[str] = Query(default=None),
):
    """Top-level KPI cards."""
    sd = start_date or _default_start()
    ed = end_date or _today_sp()

    sessions = await _fetch_all(
        "recovery_sessions", "status, messages_sent, amount_cents", sd, ed, platform, product
    )

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

    # Conversion rate over *resolved* sessions only — active sessions are still
    # in-flight and haven't had a chance to convert, so counting them in the
    # denominator understates the real rate.
    resolved = total - active

    return {
        "total_sessions": total,
        "converted": converted,
        "active": active,
        "exhausted": exhausted,
        "cancelled": cancelled,
        "resolved": resolved,
        "conversion_rate": round(converted / resolved * 100, 1) if resolved > 0 else 0.0,
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
    ed = end_date or _today_sp()

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
    sd = start_date or _default_start()
    ed = end_date or _today_sp()

    rows = await _fetch_all(
        "recovery_sessions", "messages_sent", sd, ed, platform, product,
        extra=lambda q: q.eq("status", "converted"),
    )

    funnel = {1: 0, 2: 0, 3: 0}
    for s in rows:
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
    sd = start_date or _default_start()
    ed = end_date or _today_sp()

    rows = await _fetch_all(
        "recovery_sessions", "template_prefix, product_name, status, amount_cents",
        sd, ed, platform, None,
    )

    stats: dict = {}
    for s in rows:
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
    sd = start_date or _default_start()
    ed = end_date or _today_sp()

    rows = await _fetch_all(
        "recovery_sessions", "created_at, status, amount_cents, messages_sent",
        sd, ed, platform, product,
    )

    daily: dict = defaultdict(lambda: {"sessions": 0, "converted": 0, "recovered_cents": 0, "messages_sent": 0})
    for s in rows:
        day = _sp_day_str(s.get("created_at") or "")
        if not day:
            continue
        daily[day]["sessions"] += 1
        daily[day]["messages_sent"] += s.get("messages_sent") or 0
        if s["status"] == "converted":
            daily[day]["converted"] += 1
            daily[day]["recovered_cents"] += s.get("amount_cents") or 0

    return sorted(
        [{"day": k, **v} for k, v in daily.items()],
        key=lambda x: x["day"],
    )


# ── journey helpers ────────────────────────────────────────────────────────

def _apply_journey_filters(query, start_date, end_date, entry_platform, entry_product):
    """Apply date/product/platform filters to a contact_journeys query."""
    if start_date:
        query = query.gte("created_at", _sp_day_start_utc_iso(start_date))
    if end_date:
        query = query.lt("created_at", _sp_day_end_utc_iso(end_date))
    if entry_platform:
        query = query.eq("entry_platform", entry_platform)
    if entry_product:
        query = query.eq("entry_product", entry_product)
    return query


async def _fetch_all_journeys(table, columns, sd, ed, entry_platform, entry_product, extra=None):
    """
    Fetch ALL matching rows from a journey-related table, paginating past
    PostgREST's 1000-row cap. Parallel to _fetch_all but uses column names
    from the contact_journeys schema.
    """
    db = await get_supabase()
    page_size = 1000
    offset = 0
    rows: list[dict] = []
    while True:
        query = db.table(table).select(columns)
        query = _apply_journey_filters(query, sd, ed, entry_platform, entry_product)
        if extra is not None:
            query = extra(query)
        result = await query.range(offset, offset + page_size - 1).execute()
        batch = result.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        offset += page_size


# ── journey endpoints ──────────────────────────────────────────────────────

@router.get("/journey/stats")
async def get_journey_stats(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    entry_platform: Optional[str] = Query(default=None),
    entry_product: Optional[str] = Query(default=None),
):
    """Journey KPI cards — status distribution and aggregate metrics."""
    sd = start_date or _default_journey_start()
    ed = end_date or _today_sp()

    try:
        rows = await _fetch_all_journeys(
            "contact_journeys", "status, messages_sent", sd, ed, entry_platform, entry_product,
        )
    except Exception:
        rows = []

    total = len(rows)
    active = sum(1 for r in rows if r.get("status") == "active")
    paused = sum(1 for r in rows if r.get("status") == "paused")
    completed = sum(1 for r in rows if r.get("status") == "completed")
    opted_out = sum(1 for r in rows if r.get("status") == "opted_out")
    suporte = sum(1 for r in rows if r.get("status") == "suporte")
    total_messages = sum(r.get("messages_sent") or 0 for r in rows)

    denominator = completed + opted_out
    completion_rate = round(completed / denominator * 100, 1) if denominator > 0 else 0.0

    return {
        "total_journeys": total,
        "active": active,
        "paused": paused,
        "completed": completed,
        "opted_out": opted_out,
        "suporte": suporte,
        "total_messages_sent": total_messages,
        "completion_rate": completion_rate,
    }


@router.get("/journey/leads")
async def get_journey_leads(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    entry_platform: Optional[str] = Query(default=None),
    entry_product: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    temperatura: Optional[str] = Query(default=None),
    ticket: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, le=1000),
):
    """
    Paginated leads — contact_journeys enriched with lead_insights by phone.
    Supports search (full_name / phone) and filters (state, temperatura, ticket).

    limit caps at 1000 (not the usual 100) because the dashboard's Kanban/KPI/
    alert cards fetch the full lead set in one page (limit=500/1000) to
    aggregate client-side — the dataset here is small (contact_journeys),
    unlike /sessions.
    """
    db = await get_supabase()

    sd = start_date or _default_journey_start()
    ed = end_date or _today_sp()
    offset = (page - 1) * limit

    # --- 1. Fetch paginated contact_journeys ---
    try:
        query = db.table("contact_journeys").select("*", count="exact")
        query = _apply_journey_filters(query, sd, ed, entry_platform, entry_product)

        if state:
            query = query.eq("current_state", state)
        if search:
            query = query.or_(f"full_name.ilike.*{search}*,phone.ilike.*{search}*")

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        result = await query.execute()
    except Exception:
        return {"data": [], "total": 0, "page": page, "pages": 0}

    total = result.count or 0
    rows = result.data or []

    # --- 2. Fetch lead_insights for every phone on this page ---
    phones = [r["phone"] for r in rows if r.get("phone")]
    insights_by_phone: dict[str, dict] = {}
    if phones:
        try:
            ins_result = await (
                db.table("lead_insights")
                .select("*")
                .in_("phone", phones)
                .execute()
            )
            for i in (ins_result.data or []):
                insights_by_phone[i["phone"]] = i
        except Exception:
            insights_by_phone = {}

    # --- 3. Merge ---
    data = []
    for r in rows:
        ins = insights_by_phone.get(r.get("phone"), {})

        # Apply temperatura/ticket filters client-side after merge
        if temperatura and ins.get("temperatura") != temperatura:
            continue
        if ticket and ins.get("ticket") != ticket:
            continue

        data.append({
            "id": r.get("id"),
            "phone": r.get("phone"),
            "full_name": r.get("full_name"),
            "current_state": r.get("current_state"),
            "current_stage": r.get("current_stage"),
            "tags": r.get("tags"),
            "purchased_products": r.get("purchased_products"),
            "day_offset": r.get("day_offset"),
            "messages_sent": r.get("messages_sent"),
            "status": r.get("status"),
            "temperatura": ins.get("temperatura"),
            "ticket": ins.get("ticket"),
            "estagio": ins.get("estagio"),
            "dores": ins.get("dores"),
            "ambicoes": ins.get("ambicoes"),
            "perfil": ins.get("perfil"),
            "last_response_at": r.get("last_response_at"),
            "created_at": r.get("created_at"),
        })

    return {
        "data": data,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // limit)),
    }


@router.get("/contacts")
async def get_contacts_without_journey(
    search: Optional[str] = Query(default=None),
    temperatura: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, le=100),
):
    """
    Contacts who have talked to Júlia but never completed a purchase — no
    contact_journeys row (that only gets created on a confirmed sale, see
    app/services/journey_engine.py::create_journey). Without this endpoint
    these contacts are recorded (app/routers/meta.py upserts one on every
    inbound message) but invisible anywhere in the dashboard.
    """
    db = await get_supabase()
    offset = (page - 1) * limit

    # Everyone who *does* have a journey — excluded below via NOT IN. Small
    # table (one row per confirmed sale), cheap to pull in full.
    try:
        journeys = await db.table("contact_journeys").select("phone").execute()
        journey_phones = [j["phone"] for j in (journeys.data or []) if j.get("phone")]
    except Exception:
        journey_phones = []

    try:
        query = db.table("contacts").select("*", count="exact")
        if journey_phones:
            query = query.not_.in_("phone", journey_phones)
        if search:
            query = query.or_(f"full_name.ilike.*{search}*,phone.ilike.*{search}*")
        query = query.order("updated_at", desc=True).range(offset, offset + limit - 1)
        result = await query.execute()
    except Exception:
        return {"data": [], "total": 0, "page": page, "pages": 0}

    total = result.count or 0
    rows = result.data or []

    # Enrich with lead_insights (temperatura/ticket/estagio/dores/...) —
    # these ARE generated for non-buyers too (analyze_lead only requires a
    # contact or journey to exist, see app/services/lead_analyzer.py).
    phones = [r["phone"] for r in rows if r.get("phone")]
    insights_by_phone: dict[str, dict] = {}
    if phones:
        try:
            ins_result = await db.table("lead_insights").select("*").in_("phone", phones).execute()
            for i in (ins_result.data or []):
                insights_by_phone[i["phone"]] = i
        except Exception:
            insights_by_phone = {}

    data = []
    for r in rows:
        ins = insights_by_phone.get(r.get("phone"), {})
        if temperatura and ins.get("temperatura") != temperatura:
            continue
        data.append({
            "phone": r.get("phone"),
            "full_name": r.get("full_name"),
            "email": r.get("email"),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "temperatura": ins.get("temperatura"),
            "ticket": ins.get("ticket"),
            "estagio": ins.get("estagio"),
            "dores": ins.get("dores"),
            "ambicoes": ins.get("ambicoes"),
            "perfil": ins.get("perfil"),
        })

    return {
        "data": data,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // limit)),
    }


@router.get("/journey/lead/{phone}")
async def get_journey_lead(phone: str):
    """
    Single lead deep view. Merges contact_journeys, lead_insights, contacts,
    and every dispatch (both scheduled_messages from the recovery funnel and
    journey_messages from the post-purchase journey) sent to this phone.
    """
    db = await get_supabase()

    profile: dict = {}

    # --- contact_journey ---
    try:
        jr = await db.table("contact_journeys").select("*").eq("phone", phone).limit(1).execute()
        journey = (jr.data or [None])[0]
        if journey:
            profile.update(journey)
    except Exception:
        pass

    # --- lead_insights ---
    try:
        ir = await db.table("lead_insights").select("*").eq("phone", phone).limit(1).execute()
        insights = (ir.data or [None])[0]
        if insights:
            for k, v in insights.items():
                if k not in ("id", "phone", "created_at", "updated_at"):
                    profile[k] = v
    except Exception:
        pass

    # --- contacts ---
    try:
        cr = await db.table("contacts").select("*").eq("phone", phone).limit(1).execute()
        contact = (cr.data or [None])[0]
        if contact:
            profile["email"] = contact.get("email")
            profile["contact_created_at"] = contact.get("created_at")
    except Exception:
        pass

    # --- dispatches: journey_messages (post-purchase, 37 templates) +
    #     scheduled_messages (recovery funnel, 3 templates) — everything
    #     ever sent (or scheduled) to this phone, unified into one timeline.
    dispatches: list[dict] = []
    try:
        jm = await (
            db.table("journey_messages")
            .select("template_name, message_number, status, scheduled_for, sent_at, whatsapp_message_id")
            .eq("phone", phone)
            .order("scheduled_for", desc=True)
            .limit(50)
            .execute()
        )
        for m in (jm.data or []):
            dispatches.append({**m, "source": "journey"})
    except Exception:
        pass

    try:
        sm = await (
            db.table("scheduled_messages")
            .select("template_name, message_number, status, scheduled_for, sent_at, whatsapp_message_id")
            .eq("phone", phone)
            .order("scheduled_for", desc=True)
            .limit(50)
            .execute()
        )
        for m in (sm.data or []):
            dispatches.append({**m, "source": "recovery"})
    except Exception:
        pass

    dispatches.sort(key=lambda m: m.get("scheduled_for") or "", reverse=True)
    profile["dispatches"] = dispatches
    profile["recent_messages"] = dispatches[:10]  # kept for backward compatibility

    profile["phone"] = phone
    return profile


@router.get("/journey/daily")
async def get_journey_daily(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    entry_platform: Optional[str] = Query(default=None),
    entry_product: Optional[str] = Query(default=None),
):
    """Journeys created + messages sent per day for the timeline chart."""
    sd = start_date or _default_journey_start()
    ed = end_date or _today_sp()

    try:
        rows = await _fetch_all_journeys(
            "contact_journeys", "created_at, messages_sent", sd, ed, entry_platform, entry_product,
        )
    except Exception:
        rows = []

    daily: dict = defaultdict(lambda: {"journeys_created": 0, "messages_sent": 0})
    for r in rows:
        day = _sp_day_str(r.get("created_at") or "")
        if not day:
            continue
        daily[day]["journeys_created"] += 1
        daily[day]["messages_sent"] += r.get("messages_sent") or 0

    return sorted(
        [{"day": k, **v} for k, v in daily.items()],
        key=lambda x: x["day"],
    )


@router.get("/journey/products")
async def get_journey_products(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    entry_platform: Optional[str] = Query(default=None),
):
    """
    Product distribution — counts journeys by entry_product AND
    aggregates distinct products across purchased_products arrays.
    """
    sd = start_date or _default_journey_start()
    ed = end_date or _today_sp()

    try:
        rows = await _fetch_all_journeys(
            "contact_journeys", "entry_product, purchased_products",
            sd, ed, entry_platform, None,
        )
    except Exception:
        rows = []

    entry_counts: dict[str, int] = defaultdict(int)
    purchase_counts: dict[str, int] = defaultdict(int)

    for r in rows:
        ep = r.get("entry_product")
        if ep:
            entry_counts[ep] += 1

        pp = r.get("purchased_products") or []
        for p in pp:
            if p:
                purchase_counts[p] += 1

    all_products = set(entry_counts.keys()) | set(purchase_counts.keys())
    result = sorted(
        [
            {
                "product": p,
                "journeys": entry_counts.get(p, 0),
                "purchases": purchase_counts.get(p, 0),
            }
            for p in all_products
        ],
        key=lambda x: x["journeys"] + x["purchases"],
        reverse=True,
    )

    return result


@router.get("/journey/insights")
async def get_journey_insights():
    """
    Lead intelligence summary — temperature and ticket distributions
    from the lead_insights table.
    """
    db = await get_supabase()

    try:
        result = await db.table("lead_insights").select("temperatura, ticket, estagio").execute()
        rows = result.data or []
    except Exception:
        rows = []

    temperatura = {"quente": 0, "morno": 0, "frio": 0}
    ticket = {"high": 0, "low": 0, "unknown": 0}
    estagio = {"consciencia": 0, "consideracao": 0, "decisao": 0, "cliente": 0}

    for r in rows:
        t = r.get("temperatura")
        if t in temperatura:
            temperatura[t] += 1

        tk = r.get("ticket")
        if tk in ticket:
            ticket[tk] += 1

        e = r.get("estagio")
        if e in estagio:
            estagio[e] += 1

    return {
        "temperatura": temperatura,
        "ticket": ticket,
        "estagio": estagio,
        "total_analyzed": len(rows),
    }


@router.get("/templates")
async def get_templates():
    """
    Full catalog of WhatsApp message templates approved on Meta — the
    actual copy (header/body/footer/buttons), not just the name. Pulled
    live from the Graph API so it's always in sync with what's actually
    approved and sendable. Powers the templates manual page.
    """
    import httpx

    from app.config import settings
    from app.services.journey_engine import TEMPLATES as JOURNEY_TEMPLATES
    from app.services.recovery import PRODUCT_TEMPLATE_MAP

    if not settings.meta_waba_id or not settings.meta_access_token:
        return {"templates": [], "total": 0}

    # Names the app actually sends today — everything else on Meta is a
    # leftover draft (older _v1/no-suffix iteration) kept around because
    # WhatsApp doesn't let you delete an approved template.
    in_use_names = set(JOURNEY_TEMPLATES.keys())
    for _keyword, prefix in PRODUCT_TEMPLATE_MAP:
        in_use_names.update(f"{prefix}{i}_v1" for i in (1, 2, 3))

    url = f"https://graph.facebook.com/{settings.meta_api_version}/{settings.meta_waba_id}/message_templates"
    params: dict | None = {"fields": "name,status,category,language,components", "limit": 200}
    headers = {"Authorization": f"Bearer {settings.meta_access_token}"}

    templates = []
    async with httpx.AsyncClient(timeout=30) as client:
        while url:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            for t in data.get("data", []):
                components = t.get("components", [])
                header = next((c for c in components if c.get("type") == "HEADER"), None)
                body = next((c.get("text", "") for c in components if c.get("type") == "BODY"), "")
                footer = next((c.get("text") for c in components if c.get("type") == "FOOTER"), None)
                buttons_comp = next((c for c in components if c.get("type") == "BUTTONS"), None)
                buttons = [b.get("text", "") for b in (buttons_comp.get("buttons", []) if buttons_comp else [])]

                templates.append({
                    "name": t.get("name"),
                    "status": t.get("status"),
                    "category": t.get("category"),
                    "language": t.get("language"),
                    "header_text": header.get("text") if header else None,
                    "header_format": header.get("format") if header else None,
                    "body": body,
                    "footer": footer,
                    "buttons": buttons,
                    "in_use": t.get("name") in in_use_names,
                })

            url = (data.get("paging") or {}).get("next")
            params = None  # the "next" URL already carries all query params

    templates.sort(key=lambda t: (not t["in_use"], t["name"] or ""))
    return {"templates": templates, "total": len(templates)}
