import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import get_supabase
from app.routers import assiny, dashboard, kiwify
from app.services.meta_analytics import sync_costs
from app.services.scheduler import run_cost_sync, run_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
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
app.include_router(dashboard.router)


@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok"}


@app.get("/cost", tags=["infra"])
async def cost():
    """Reconciled Meta cost from meta_cost_daily — what Meta actually charged (USD)."""
    db = await get_supabase()
    result = (
        await db.table("meta_cost_daily")
        .select("day, pricing_category, currency, cost, volume")
        .order("day", desc=True)
        .limit(500)
        .execute()
    )
    rows = result.data or []
    total = sum(float(r["cost"]) for r in rows)
    currency = next((r["currency"] for r in rows if r.get("currency")), "USD")
    return {"currency": currency, "total_cost": round(total, 2), "rows": rows}


@app.post("/cost/sync", tags=["infra"])
async def cost_sync_now():
    """Trigger a cost sync on demand (e.g. right after setting META_WABA_ID)."""
    written = await sync_costs()
    return {"status": "ok", "rows_written": written}
