"""
Júlia — LangChain agent engine.

GPT-4.1 + Redis session memory + Supabase persistence.
Handles WhatsApp conversations for sales recovery at The Differs Co.
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_community.chat_message_histories import RedisChatMessageHistory

from app.agent.prompt import JULIA_SYSTEM_PROMPT
from app.agent.tools import (
    classificar_lead,
    consultar_produto,
    enviar_checkout,
    enviar_formulario,
    enviar_suporte,
    verificar_cliente,
)
from app.config import settings

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Agent setup (singleton — reused across requests)
# ═══════════════════════════════════════════════════════════════

TOOLS = [consultar_produto, enviar_checkout, enviar_formulario, enviar_suporte, verificar_cliente, classificar_lead]

_llm: Optional[ChatOpenAI] = None
_agent_executor: Optional[AgentExecutor] = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model="gpt-4.1",
            temperature=0.7,
            api_key=settings.openai_api_key,
            verbose=False,
        )
    return _llm


def _get_agent() -> AgentExecutor:
    global _agent_executor
    if _agent_executor is None:
        llm = _get_llm()

        prompt = ChatPromptTemplate.from_messages([
            ("system", JULIA_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

        agent = create_tool_calling_agent(llm, TOOLS, prompt)
        _agent_executor = AgentExecutor(
            agent=agent,
            tools=TOOLS,
            verbose=False,
            max_iterations=5,
            handle_parsing_errors=True,
        )

    return _agent_executor


# ═══════════════════════════════════════════════════════════════
# Session memory (Redis-backed)
# ═══════════════════════════════════════════════════════════════

def _redis_url() -> str:
    return settings.redis_url


def _session_key(phone: str) -> str:
    return f"julia:session:{phone}"


def _get_memory(phone: str) -> RedisChatMessageHistory:
    return RedisChatMessageHistory(
        session_id=_session_key(phone),
        url=_redis_url(),
        ttl=3600 * 24 * 7,  # 7 days TTL
    )


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

async def julia_reply(phone: str, message: str, full_name: str = "") -> dict:
    """
    Process an incoming WhatsApp message and return Júlia's response.

    Args:
        phone: E.164 phone number (session key)
        message: The student's message text
        full_name: Optional name for personalization

    Returns:
        dict with keys:
            - reply: Júlia's text response
            - link_type: "checkout" | "formulario" | "suporte" | None
            - link_url: the extracted link or None
    """
    memory = _get_memory(phone)
    agent = _get_agent()

    # Build input — include name context if available
    agent_input = message
    if full_name:
        agent_input = f"[Lead: {full_name}] {message}"

    try:
        result = await agent.ainvoke(
            {"input": agent_input, "chat_history": memory.messages},
            config={"configurable": {"session_id": _session_key(phone)}},
        )
    except Exception as exc:
        logger.error(f"Agent invoke error for {phone}: {exc}")
        return {
            "reply": "Opa, deu uma travada aqui! Tenta de novo? 😅",
            "link_type": None,
            "link_url": None,
        }

    reply = result.get("output", "")

    # Extract special link markers from tool outputs
    link_type: Optional[str] = None
    link_url: Optional[str] = None

    for marker, ltype in [
        ("LINK_CHECKOUT:", "checkout"),
        ("LINK_PAGINA_VENDAS:", "pagina_vendas"),
        ("LINK_FORMULARIO:", "formulario"),
        ("LINK_SUPORTE:", "suporte"),
    ]:
        if marker in reply:
            # Extract URL and remove marker from reply
            parts = reply.split(marker, 1)
            url_part = parts[1].strip().split("\n")[0].strip()
            link_url = url_part
            link_type = ltype
            # Clean up the reply text
            reply = (parts[0] + parts[1].replace(url_part, "", 1).strip()).strip()
            break

    # Save to memory
    memory.add_user_message(message)
    memory.add_ai_message(reply)

    logger.info(
        f"Júlia replied to {phone}: {reply[:80]}... "
        f"link={link_type}"
    )

    return {
        "reply": reply,
        "link_type": link_type,
        "link_url": link_url,
    }


async def clear_session(phone: str) -> None:
    """Clear Júlia's conversation history for a phone number."""
    try:
        memory = _get_memory(phone)
        memory.clear()
        logger.info(f"Session cleared for {phone}")
    except Exception as exc:
        logger.warning(f"Could not clear session for {phone}: {exc}")
