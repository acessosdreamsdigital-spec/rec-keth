import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, Query

from app.config import settings
from app.database import get_supabase
from app.routers import assiny, dashboard, kiwify, meta
from app.services.meta_analytics import sync_costs
from app.services.scheduler import run_cost_sync, run_scheduler

# Railway colore stderr de vermelho — manda tudo pra stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


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
    title="Sales Recovery API",
    description="Webhook receiver + WhatsApp recovery sequences for Kiwify and Assiny",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(kiwify.router)
app.include_router(assiny.router)
app.include_router(meta.router)
app.include_router(dashboard.router)


@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok"}


@app.get("/cost", tags=["infra"])
async def cost(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
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

    # Real cost per calendar day (summing categories), for the dashboard chart.
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
async def cost_sync_now():
    """Trigger a cost sync on demand (e.g. right after setting META_WABA_ID)."""
    written = await sync_costs()
    return {"status": "ok", "rows_written": written}
