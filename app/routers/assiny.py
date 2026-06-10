"""
Assiny webhook router.

Endpoint: POST /webhooks/assiny

Event mapping:
  event == "abandoned_purchase"   → abandoned_cart    → recovery
  event == "pix_expired"          → waiting_payment   → recovery
  event == "bank_slip_generated"  → waiting_payment   → recovery
  event == "refused"              → payment_refused   → recovery
  event == "completed_purchase"
    + transaction.status == "paid" → purchase confirmed → stop sequence
"""

import json
import logging

from fastapi import APIRouter, Request, Response

from app.config import settings
from app.services.recovery import handle_purchase_approved, handle_recovery_event
from app.utils.security import verify_assiny

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_RECOVERY_EVENT_MAP = {
    "abandoned_purchase": "abandoned_cart",
    "pix_expired": "waiting_payment",
    "bank_slip_generated": "waiting_payment",
    "refused": "payment_refused",
}


@router.post("/assiny")
async def assiny_webhook(request: Request) -> Response:
    raw = await request.body()
    if not verify_assiny(request, raw, settings.assiny_webhook_token):
        return Response(status_code=401)
    body: dict = json.loads(raw or b"{}")

    event: str = body.get("event", "")
    data: dict = body.get("data") or {}
    offer: dict = data.get("offer") or {}
    product: dict = offer.get("product") or {}
    client: dict = data.get("client") or {}
    transaction: dict = data.get("transaction") or {}

    # ── Recovery trigger events ─────────────────────────────────────────────
    if event in _RECOVERY_EVENT_MAP:
        await handle_recovery_event(
            platform="assiny",
            platform_order_id=transaction.get("id"),
            platform_event_type=event,
            trigger_event=_RECOVERY_EVENT_MAP[event],
            product_id=product.get("id", ""),
            product_name=product.get("name", ""),
            amount_cents=transaction.get("amount"),
            phone_raw=client.get("phone", ""),
            full_name=client.get("full_name", ""),
            email=client.get("email", ""),
            raw_payload=body,
        )
        return Response(status_code=200)

    # ── Purchase approved → stop recovery sequence ──────────────────────────
    if event == "completed_purchase" and transaction.get("status") == "paid":
        await handle_purchase_approved(
            platform="assiny",
            platform_order_id=transaction.get("id"),
            product_name=product.get("name", ""),
            phone_raw=client.get("phone", ""),
            raw_payload=body,
        )
        return Response(status_code=200)

    logger.debug(f"Assiny: unhandled event={event!r}")
    return Response(status_code=200)
