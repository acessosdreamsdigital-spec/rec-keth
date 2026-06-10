import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class WhatsAppSendError(Exception):
    """
    Raised when a send fails. `transient` tells the scheduler whether it is
    worth retrying (network blip / 5xx / 429) or permanent (bad template,
    invalid number, auth — 4xx) and should go straight to 'failed'.
    """

    def __init__(self, message: str, *, transient: bool):
        super().__init__(message)
        self.transient = transient


# Meta/HTTP statuses that are worth retrying.
_TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}


async def send_template(phone: str, template_name: str) -> dict:
    """
    Send a WhatsApp template message via Meta Cloud API.
    Returns the full API response dict.
    Raises WhatsAppSendError (with .transient) on failure.
    """
    url = (
        f"https://graph.facebook.com/{settings.meta_api_version}"
        f"/{settings.meta_phone_number_id}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "pt_BR"},
        },
    }
    headers = {
        "Authorization": f"Bearer {settings.meta_access_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        transient = status in _TRANSIENT_STATUSES
        body = exc.response.text[:500]
        raise WhatsAppSendError(f"HTTP {status}: {body}", transient=transient) from exc
    except httpx.TransportError as exc:
        # Connection/timeout/DNS — always worth retrying.
        raise WhatsAppSendError(f"transport error: {exc}", transient=True) from exc

    logger.info(f"WhatsApp sent template={template_name} to={phone} id={data}")
    return data
