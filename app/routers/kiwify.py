"""
Kiwify webhook router.

Endpoint: POST /webhooks/kiwify

Event mapping:
  webhook_event_type == "pix_created"     → waiting_payment  → recovery
  webhook_event_type == "billet_created"  → waiting_payment  → recovery
  webhook_event_type == "order_rejected"  → payment_refused  → recovery
  body.status == "abandoned"              → abandoned_cart    → recovery  (different schema)
  webhook_event_type == "order_approved"  → purchase confirmed → stop sequence
"""

import logging

from fastapi import APIRouter, Request, Response

from app.services.recovery import handle_purchase_approved, handle_recovery_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_RECOVERY_EVENT_MAP = {
    "pix_created": "waiting_payment",
    "billet_created": "waiting_payment",
    "order_rejected": "payment_refused",
}


@router.post("/kiwify")
async def kiwify_webhook(request: Request) -> Response:
    body: dict = await request.json()

    event_type: str = body.get("webhook_event_type", "")
    order_status: str = body.get("order_status", "") or body.get("status", "")

    # ── Abandoned cart (flat schema, no webhook_event_type) ────────────────
    if order_status == "abandoned":
        await handle_recovery_event(
            platform="kiwify",
            platform_order_id=body.get("id"),
            platform_event_type="abandoned",
            trigger_event="abandoned_cart",
            product_id=body.get("product_id", ""),
            product_name=body.get("product_name", ""),
            amount_cents=None,
            phone_raw=body.get("phone", ""),
            full_name=body.get("name", ""),
            email=body.get("email", ""),
            raw_payload=body,
        )
        return Response(status_code=200)

    # ── Recovery trigger events ─────────────────────────────────────────────
    if event_type in _RECOVERY_EVENT_MAP:
        product = body.get("Product") or {}
        customer = body.get("Customer") or {}
        commissions = body.get("Commissions") or {}

        await handle_recovery_event(
            platform="kiwify",
            platform_order_id=body.get("order_id"),
            platform_event_type=event_type,
            trigger_event=_RECOVERY_EVENT_MAP[event_type],
            product_id=product.get("product_id", ""),
            product_name=product.get("product_name", ""),
            amount_cents=commissions.get("charge_amount"),
            phone_raw=customer.get("mobile", ""),
            full_name=customer.get("full_name", ""),
            email=customer.get("email", ""),
            raw_payload=body,
        )
        return Response(status_code=200)

    # ── Purchase approved → stop recovery sequence ──────────────────────────
    if event_type == "order_approved":
        product = body.get("Product") or {}
        customer = body.get("Customer") or {}

        await handle_purchase_approved(
            platform="kiwify",
            platform_order_id=body.get("order_id"),
            product_name=product.get("product_name", ""),
            phone_raw=customer.get("mobile", ""),
            raw_payload=body,
        )
        return Response(status_code=200)

    # Unknown / unhandled event — always return 200 to avoid Kiwify retries
    logger.debug(f"Kiwify: unhandled event_type={event_type!r} order_status={order_status!r}")
    return Response(status_code=200)
