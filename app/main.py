import asyncio
import logging
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import get_supabase
from app.routers import admin, agent, assiny, chatwoot, dashboard, kiwify, meta
from app.services.meta_analytics import sync_costs
from app.services.scheduler import run_cost_sync, run_scheduler
from app.utils.auth import verify_api_key

# Railway colore stderr de vermelho — manda tudo pra stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Simple in-memory rate limiter (no extra deps)
# ═══════════════════════════════════════════════════════════════

_RATE_WINDOW = 60  # 1 minute window
_rate_buckets: dict[str, list[float]] = defaultdict(list)


def _clean_old(bucket: list[float], window: float) -> None:
    """Remove timestamps older than the window."""
    cutoff = time.monotonic() - window
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)


def _check_rate(key: str, limit: int, window: int = _RATE_WINDOW) -> bool:
    """Return True if within rate limit, False if exceeded."""
    if not settings.rate_limit_enabled:
        return True
    bucket = _rate_buckets[key]
    _clean_old(bucket, window)
    if len(bucket) >= limit:
        return False
    bucket.append(time.monotonic())
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [
        asyncio.create_task(run_scheduler(settings.scheduler_interval_seconds)),
        asyncio.create_task(run_cost_sync(settings.cost_sync_interval_seconds)),
    ]
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("Background tasks stopped")


app = FastAPI(
    title="Sales Recovery API — rec-keth",
    description="WhatsApp recovery + journey + Júlia AI agent",
    version="2.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Apply rate limits based on route prefix."""
    path = request.url.path
    client_ip = request.client.host if request.client else "unknown"

    if path == "/health":
        limit, window = 1000, 60
    elif path.startswith("/webhooks/"):
        limit, window = int(settings.rate_limit_webhooks.split("/")[0]), 60
    elif path.startswith("/admin/") or path.startswith("/dashboard/") or path == "/cost":
        limit, window = int(settings.rate_limit_admin.split("/")[0]), 60
    elif path.startswith("/agent/") or path.startswith("/journey/"):
        limit, window = int(settings.rate_limit_agent.split("/")[0]), 60
    else:
        limit, window = 60, 60

    key = f"{client_ip}:{path.split('/')[1] if '/' in path else path}"
    if not _check_rate(key, limit, window):
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Slow down."},
            headers={"Retry-After": str(window)},
        )

    return await call_next(request)


# CORS — allow Chatwoot and dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://chatwoot-keth.itbtqc.easypanel.host",
        "https://rec-keth-production.up.railway.app",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ── Public routes (no auth) ──
app.include_router(kiwify.router)
app.include_router(assiny.router)
app.include_router(meta.router)
app.include_router(chatwoot.router)  # Chatwoot forwards messages here

# ── Protected routes (API key required) ──
app.include_router(admin.router, dependencies=[Depends(verify_api_key)])
app.include_router(agent.router, dependencies=[Depends(verify_api_key)])
app.include_router(dashboard.router, dependencies=[Depends(verify_api_key)])


@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok"}


@app.get("/cost", tags=["infra"])
async def cost(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    _key: str = Depends(verify_api_key),
):
    """
    Reconciled Meta cost from meta_cost_daily — what Meta actually charged (USD).
    Account-wide (Meta does not attribute cost per product/platform).
    """
    db = await get_supabase()
    query = db.table("meta_cost_daily").select(
        "day, pricing_category, currency, cost, volume"
    )
    if start_date:
        query = query.gte("day", start_date.isoformat())
    if end_date:
        query = query.lte("day", end_date.isoformat())
    result = await query.order("day", desc=True).limit(1000).execute()

    rows = result.data or []
    total = sum(float(r["cost"]) for r in rows)
    volume = sum(int(r["volume"]) for r in rows)
    currency = next((r["currency"] for r in rows if r.get("currency")), "USD")

    by_day: dict[str, float] = {}
    for r in rows:
        by_day[r["day"]] = round(by_day.get(r["day"], 0.0) + float(r["cost"]), 4)

    return {
        "currency": currency,
        "total_cost": round(total, 2),
        "total_volume": volume,
        "usd_brl_rate": settings.usd_brl_rate,
        "total_cost_brl": round(total * settings.usd_brl_rate, 2),
        "by_day": by_day,
        "rows": rows,
    }


@app.post("/cost/sync", tags=["infra"])
async def cost_sync_now(_key: str = Depends(verify_api_key)):
    """Trigger a cost sync on demand (e.g. right after setting META_WABA_ID)."""
    written = await sync_costs()
    return {"status": "ok", "rows_written": written}
