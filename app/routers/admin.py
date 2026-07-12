"""Admin endpoints — debug, manual triggers, lead analysis."""

from fastapi import APIRouter, Query

from app.services.lead_analyzer import analyze_lead
from app.utils.phone import normalize_phone

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/analyze/{phone}")
async def analyze_lead_endpoint(phone: str, force: bool = Query(default=False)):
    """Manually trigger lead analysis for a phone number."""
    phone_norm = normalize_phone(phone)
    result = await analyze_lead(phone_norm, force=force)
    return result
