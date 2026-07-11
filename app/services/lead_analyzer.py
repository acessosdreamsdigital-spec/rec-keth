"""
Lead Analyzer — background AI-powered lead profiling.

Collects all available data for a lead and calls GPT-4.1 Mini
to generate structured insights: temperature, ticket level,
pain points, ambitions, objections, and profile summary.

Results are stored in lead_insights table for Júlia + journey engine.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

from app.config import settings as _settings

ANALYSIS_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "lead_analysis",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "temperatura": {"type": "string", "enum": ["quente", "morno", "frio"]},
                "ticket": {"type": "string", "enum": ["high", "low", "unknown"]},
                "estagio": {"type": "string", "enum": ["consciencia", "consideracao", "decisao", "cliente"]},
                "dores": {"type": "array", "items": {"type": "string"}},
                "ambicoes": {"type": "array", "items": {"type": "string"}},
                "objecoes": {"type": "array", "items": {"type": "string"}},
                "produtos_interesse": {"type": "array", "items": {"type": "string"}},
                "resumo": {"type": "string"},
                "perfil": {"type": "string"},
            },
            "required": ["temperatura", "ticket", "estagio", "dores", "ambicoes", "objecoes", "produtos_interesse", "resumo", "perfil"],
            "additionalProperties": False,
        },
    },
}


async def analyze_lead(phone: str, force: bool = False) -> dict:
    """
    Collect all lead data and call GPT-4.1 Mini to profile the lead.
    Upserts results into lead_insights.

    Args:
        phone: E.164 phone number
        force: If True, re-analyze even if recently analyzed (< 24h ago)

    Returns the analysis dict or {"status": "skipped"}.
    """
    if not _settings.openai_api_key:
        logger.warning("_settings.openai_api_key not set — skipping lead analysis")
        return {"status": "skipped", "reason": "no_api_key"}

    # Collect all lead data
    context = await _collect_lead_data(phone)
    if not context:
        return {"status": "skipped", "reason": "no_data"}

    # Check if recently analyzed (skip if < 24h, unless forced)
    if not force:
        recent = context.get("insight", {})
        last = recent.get("ultima_analise", "")
        if last:
            try:
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
                if hours < 24:
                    return {"status": "skipped", "reason": f"analyzed {hours:.0f}h ago"}
            except (ValueError, TypeError):
                pass

    # Build prompt
    prompt = _build_analysis_prompt(context)

    # Call GPT-4.1 Mini with structured output
    try:
        analysis = await _call_openai(prompt)
    except Exception as exc:
        logger.error(f"OpenAI analysis failed for {phone}: {exc}")
        return {"status": "error", "reason": str(exc)}

    # Upsert to lead_insights
    await _upsert_insight(phone, analysis)

    logger.info(f"Lead analysis complete for {phone}: temp={analysis.get('temperatura')} ticket={analysis.get('ticket')}")
    return {"status": "analyzed", **analysis}


async def _collect_lead_data(phone: str) -> dict | None:
    """Collect all available data about a lead from Supabase + Redis."""
    if not _settings.supabase_url or not _settings.supabase_key:
        return None

    headers = {
        "apikey": _settings.supabase_key,
        "Authorization": f"Bearer {_settings.supabase_key}",
    }

    data: dict = {}

    async def fetch(path: str, label: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{_settings.supabase_url}/rest/v1/{path}", headers=headers)
                if r.status_code == 200 and r.text:
                    result = r.json()
                    data[label] = result[0] if isinstance(result, list) and result else result
        except Exception as exc:
            logger.debug(f"Error fetching {label}: {exc}")
            data[label] = {}

    # Fetch from all tables in parallel
    await asyncio.gather(
        fetch(f"contacts?phone=eq.{phone}&select=*&limit=1", "contact"),
        fetch(f"leads?whatsapp=eq.{phone}&select=*&limit=1", "lead"),
        fetch(f"contact_journeys?phone=eq.{phone}&select=*&limit=1&order=updated_at.desc", "journey"),
        fetch(f"lead_insights?phone=eq.{phone}&select=*&limit=1", "insight"),
    )

    # Also fetch recent recovery sessions
    contact_id = (data.get("contact") or {}).get("id")
    if contact_id:
        await fetch(
            f"recovery_sessions?contact_id=eq.{contact_id}&select=product_name,status,amount_cents,platform,created_at&order=created_at.desc&limit=20",
            "purchases",
        )

    # Fetch recent journey messages
    journey_id = (data.get("journey") or {}).get("id")
    if journey_id:
        await fetch(
            f"journey_messages?journey_id=eq.{journey_id}&select=template_name,status,state_at_send,sent_at&order=created_at.desc&limit=20",
            "messages",
        )

    # Try to get Redis conversation
    try:
        import redis.asyncio as aioredis
        redis_url = _settings.redis_url
        r = aioredis.from_url(redis_url)
        session_key = f"julia:session:{phone}"
        msgs = await r.lrange(session_key, 0, -1)
        if msgs:
            data["conversation"] = [json.loads(m) for m in msgs[-20:]]  # last 20 messages
        await r.aclose()
    except Exception:
        data["conversation"] = []

    if not data.get("contact") and not data.get("lead") and not data.get("journey"):
        return None

    return data


def _build_analysis_prompt(data: dict) -> str:
    """Build a structured prompt for GPT-4.1 Mini to analyze the lead."""
    contact = data.get("contact") or {}
    lead = data.get("lead") or {}
    journey = data.get("journey") or {}
    purchases = data.get("purchases") or {}
    messages = data.get("messages") or {}
    conversation = data.get("conversation") or []

    name = contact.get("full_name") or lead.get("nome") or journey.get("full_name") or "Desconhecido"
    products_bought = journey.get("purchased_products") or []
    tags = journey.get("tags") or []
    state = journey.get("current_state") or "?"
    day = journey.get("day_offset") or 0
    msgs_sent = journey.get("messages_sent") or 0
    last_response = journey.get("last_response_text") or ""
    last_button = journey.get("last_response_button") or ""

    # Purchases
    purch_lines = []
    if isinstance(purchases, list):
        for p in purchases[:10]:
            purch_lines.append(f"  - {p.get('product_name','?')} ({p.get('status','?')}) R${(p.get('amount_cents',0) or 0)/100:.0f} via {p.get('platform','?')}")
    elif isinstance(purchases, dict) and purchases.get("product_name"):
        purch_lines.append(f"  - {purchases.get('product_name','?')} ({purchases.get('status','?')})")

    # Messages
    msg_lines = []
    if isinstance(messages, list):
        for m in messages[:10]:
            msg_lines.append(f"  - {m.get('template_name','?')} ({m.get('status','?')}) state={m.get('state_at_send','?')}")

    # Conversation
    conv_lines = []
    for m in conversation[-10:]:
        if isinstance(m, dict):
            role = m.get("type") or m.get("role") or "?"
            text = str(m.get("content") or m.get("data") or "")[:200]
            conv_lines.append(f"  [{role}] {text}")

    return f"""Analise este lead da The Differs Co. e classifique-o.

DADOS DO LEAD:
Nome: {name}
Telefone: {contact.get('phone', '?')}
Email: {contact.get('email', 'N/A')}

PRODUTOS COMPRADOS: {', '.join(products_bought) if products_bought else 'Nenhum'}
COMPRAS:
{chr(10).join(purch_lines) if purch_lines else '  Nenhuma'}

JORNADA:
Estado: {state}
Dia: D+{day}
Tags: {', '.join(tags) if tags else 'Nenhuma'}
Mensagens enviadas: {msgs_sent}
Última resposta: "{last_response}"
Último botão: "{last_button}"

ÚLTIMAS MENSAGENS:
{chr(10).join(msg_lines) if msg_lines else '  Nenhuma'}

CONVERSA RECENTE:
{chr(10).join(conv_lines) if conv_lines else '  Nenhuma'}

INSTRUÇÕES:
1. temperatura: "quente" se comprou recentemente E responde ativamente; "morno" se comprou mas está frio; "frio" se nunca comprou ou sumiu há mais de 30 dias
2. ticket: "high" se comprou produtos acima de R$500 ou demonstra interesse em Formação/Kasulo/Diagnóstico; "low" se comprou apenas produtos de entrada (R$49-R$297); "unknown" se nunca comprou
3. estagio: "cliente" se já comprou; "decisao" se pediu link/fechamento; "consideracao" se fez perguntas sobre produtos; "consciencia" se só deu oi
4. Extraia dores, ambições e objeções. Se não houver dados suficientes, use listas vazias.
5. resumo: 2 frases sobre o momento atual do lead
6. perfil: 3-4 frases descrevendo quem é esse lead"""


async def _call_openai(prompt: str) -> dict:
    """Call GPT-4.1 Mini with structured output."""
    headers = {
        "Authorization": f"Bearer {_settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-4.1-mini",
        "messages": [
            {"role": "system", "content": "Voce e um analista de leads da The Differs Co. Classifique leads com precisao baseado nos dados fornecidos. Responda APENAS com o JSON estruturado."},
            {"role": "user", "content": prompt},
        ],
        "response_format": ANALYSIS_SCHEMA,
        "temperature": 0.2,
        "max_tokens": 1000,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        result = resp.json()

    content = result["choices"][0]["message"]["content"]
    return json.loads(content)


async def _upsert_insight(phone: str, analysis: dict) -> None:
    """Insert or update lead_insights table."""
    if not _settings.supabase_url or not _settings.supabase_key:
        return

    headers = {
        "apikey": _settings.supabase_key,
        "Authorization": f"Bearer {_settings.supabase_key}",
    }

    # Check if exists
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{_settings.supabase_url}/rest/v1/lead_insights?phone=eq.{phone}&select=id&limit=1",
                headers=headers,
            )
            existing = r.json() if r.text else []
    except Exception:
        existing = []

    now = datetime.now(timezone.utc).isoformat()
    row = {
        "temperatura": analysis.get("temperatura", "frio"),
        "ticket": analysis.get("ticket", "low"),
        "estagio": analysis.get("estagio", "consciencia"),
        "dores": analysis.get("dores", []),
        "ambicoes": analysis.get("ambicoes", []),
        "objecoes": analysis.get("objecoes", []),
        "produtos_interesse": analysis.get("produtos_interesse", []),
        "resumo_conversa": analysis.get("resumo", ""),
        "perfil": analysis.get("perfil", ""),
        "ultima_analise": now,
        "updated_at": now,
    }

    headers["Content-Type"] = "application/json"
    headers["Prefer"] = "return=minimal"

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            if isinstance(existing, list) and existing:
                rid = existing[0]["id"]
                await c.patch(
                    f"{_settings.supabase_url}/rest/v1/lead_insights?id=eq.{rid}",
                    headers=headers, json=row,
                )
            else:
                row["phone"] = phone
                await c.post(
                    f"{_settings.supabase_url}/rest/v1/lead_insights",
                    headers=headers, json=row,
                )
    except Exception as exc:
        logger.error(f"Failed to upsert lead_insights for {phone}: {exc}")


def analyze_lead_background(phone: str, force: bool = False) -> None:
    """Fire-and-forget: analyze lead in background."""
    asyncio.create_task(analyze_lead(phone, force=force))
