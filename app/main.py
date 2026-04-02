import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.routers import assiny, kiwify
from app.services.scheduler import run_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_scheduler(settings.scheduler_interval_seconds))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Scheduler stopped")


app = FastAPI(
    title="Sales Recovery API",
    description="Webhook receiver + WhatsApp recovery sequences for Kiwify and Assiny",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(kiwify.router)
app.include_router(assiny.router)


@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok"}
