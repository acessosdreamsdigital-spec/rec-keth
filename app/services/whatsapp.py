import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def send_template(phone: str, template_name: str) -> dict:
    """
    Send a WhatsApp template message via Meta Cloud API.
    Returns the full API response dict.
    Raises httpx.HTTPStatusError on non-2xx responses.
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

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        logger.info(f"WhatsApp sent template={template_name} to={phone} id={data}")
        return data
