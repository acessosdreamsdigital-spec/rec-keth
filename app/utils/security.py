"""
Webhook authenticity checks — opt-in.

Verification is only enforced when the corresponding secret is configured. With
no secret set the request is accepted (preserves current behaviour so enabling
this on a live deploy never silently drops real Kiwify/Assiny traffic).
"""

import hashlib
import hmac
import logging

from fastapi import Request

logger = logging.getLogger(__name__)


def _hmac_hex(secret: str, body: bytes, algo: str) -> str:
    return hmac.new(secret.encode(), body, algo).hexdigest()


def verify_kiwify(request: Request, body: bytes, secret: str) -> bool:
    """
    Kiwify signs the raw body with HMAC-SHA1 using the account token and sends
    it as the `signature` query parameter. Returns True when no secret is set.
    """
    if not secret:
        return True
    signature = request.query_params.get("signature", "")
    if not signature:
        logger.warning("Kiwify webhook missing signature")
        return False
    expected = _hmac_hex(secret, body, hashlib.sha1)
    return hmac.compare_digest(signature, expected)


def verify_assiny(request: Request, body: bytes, secret: str) -> bool:
    """
    Assiny does not document a fixed signing scheme, so we accept either:
      - a shared token in the `x-assiny-token` header or `token` query param, or
      - an HMAC-SHA256 hex of the body in `x-assiny-signature`.
    Returns True when no secret is set.
    """
    if not secret:
        return True

    token = request.headers.get("x-assiny-token") or request.query_params.get("token", "")
    if token and hmac.compare_digest(token, secret):
        return True

    signature = request.headers.get("x-assiny-signature", "")
    if signature:
        expected = _hmac_hex(secret, body, hashlib.sha256)
        if hmac.compare_digest(signature, expected):
            return True

    logger.warning("Assiny webhook failed verification")
    return False
