"""
Journey Engine — State Machine for Ana | CapCut Wow.

Maps all 37 templates to a deterministic state machine. Called by:
1. recovery.py on purchase_approved → create_journey()
2. meta.py webhook on incoming message → process_response()
3. scheduler.py after each message sent → schedule_next()
4. scheduler.py for time-based checkpoints → evaluate_journey()

State flow (simplified):

  purchase ──▶ ativacao (D+1: template 01)
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
    engajada    fria      suporte
        │         │
   D+5,D+10,   D+3→D+120
   D+17,D+31,  (13 templates)
   D+38

Any response in fria → engajada.
Any text response (Option C) → stays on default engajada path.
Purchase of new product → closes current journey, starts new one.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Optional

from app.database import get_supabase

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Template Registry
# ═══════════════════════════════════════════════════════════════

@dataclass
class Template:
    name: str
    num: int                          # 1-37
    state: str                        # state this template belongs to
    day: int                          # day offset (D+1, D+5, etc.)
    has_buttons: bool = False
    buttons: list[str] = field(default_factory=list)
    is_open_question: bool = False    # text response expected

# All 37 templates in journey order
TEMPLATES: dict[str, Template] = {
    # ── Bloco 1: Ativação ──
    "ana_capcut_ativacao_d01_acesso_v2": Template(
        name="ana_capcut_ativacao_d01_acesso_v2", num=1,
        state="ativacao", day=1, has_buttons=True,
        buttons=["Acesso certo", "Preciso de ajuda"],
    ),
    # ── Bloco 2: Engajada ──
    "ana_capcut_engajada_d05_primeiro_video_v2": Template(
        name="ana_capcut_engajada_d05_primeiro_video_v2", num=2,
        state="engajada", day=5, has_buttons=True,
        buttons=["Já editei", "Ainda não comecei", "Preciso de ajuda"],
    ),
    "ana_capcut_engajada_d10_diagnostico_v2": Template(
        name="ana_capcut_engajada_d10_diagnostico_v2", num=3,
        state="engajada", day=10, has_buttons=False,
        is_open_question=True,
    ),
    "ana_capcut_engajada_d17_virada_identidade_v2": Template(
        name="ana_capcut_engajada_d17_virada_identidade_v2", num=4,
        state="engajada", day=17, has_buttons=True,
        buttons=["Quero entender"],
    ),
    "ana_capcut_engajada_d31_oferta_conteudo_v2": Template(
        name="ana_capcut_engajada_d31_oferta_conteudo_v2", num=5,
        state="engajada", day=31, has_buttons=True,
        buttons=["Quero conhecer", "Agora não"],
    ),
    "ana_capcut_engajada_d38_followup_conteudo_v2": Template(
        name="ana_capcut_engajada_d38_followup_conteudo_v2", num=6,
        state="engajada", day=38, has_buttons=True,
        buttons=["Quero saber mais", "Agora não"],
    ),
    # ── Bloco 3: Acelerada — Feed Wow ──
    "ana_capcut_acel_feed_d11_contexto_v2": Template(
        name="ana_capcut_acel_feed_d11_contexto_v2", num=7,
        state="acel_feed", day=11, has_buttons=True,
        buttons=["Quero entender", "Agora não"],
    ),
    "ana_capcut_acel_feed_d13_oferta_v2": Template(
        name="ana_capcut_acel_feed_d13_oferta_v2", num=8,
        state="acel_feed", day=13, has_buttons=True,
        buttons=["Quero o Feed Wow", "Agora não"],
    ),
    # ── Bloco 4: Acelerada — Conteúdo Wow ──
    "ana_capcut_acel_conteudo_d11_contexto_v2": Template(
        name="ana_capcut_acel_conteudo_d11_contexto_v2", num=9,
        state="acel_conteudo", day=11, has_buttons=True,
        buttons=["Quero entender", "Agora não"],
    ),
    "ana_capcut_acel_conteudo_d13_oferta_v2": Template(
        name="ana_capcut_acel_conteudo_d13_oferta_v2", num=10,
        state="acel_conteudo", day=13, has_buttons=True,
        buttons=["Quero os detalhes", "Agora não"],
    ),
    # ── Bloco 5: Acelerada — Meu Primeiro Infoproduto ──
    "ana_capcut_acel_mpi_d11_contexto_v2": Template(
        name="ana_capcut_acel_mpi_d11_contexto_v2", num=11,
        state="acel_mpi", day=11, has_buttons=True,
        buttons=["Quero entender", "Agora não"],
    ),
    "ana_capcut_acel_mpi_d13_oferta_v2": Template(
        name="ana_capcut_acel_mpi_d13_oferta_v2", num=12,
        state="acel_mpi", day=13, has_buttons=True,
        buttons=["Quero o acesso", "Agora não"],
    ),
    # ── Bloco 6: Acelerada — Manual DDI ──
    "ana_capcut_acel_manual_ddi_d11_contexto_v2": Template(
        name="ana_capcut_acel_manual_ddi_d11_contexto_v2", num=13,
        state="acel_manual_ddi", day=11, has_buttons=True,
        buttons=["Quero entender", "Agora não"],
    ),
    "ana_capcut_acel_manual_ddi_d13_oferta_v2": Template(
        name="ana_capcut_acel_manual_ddi_d13_oferta_v2", num=14,
        state="acel_manual_ddi", day=13, has_buttons=True,
        buttons=["Quero conhecer", "Agora não"],
    ),
    # ── Bloco 7: Acelerada — Formação DDI ──
    "ana_capcut_acel_formacao_ddi_d11_contexto_v2": Template(
        name="ana_capcut_acel_formacao_ddi_d11_contexto_v2", num=15,
        state="acel_formacao_ddi", day=11, has_buttons=True,
        buttons=["Quero entender", "Agora não"],
    ),
    "ana_capcut_acel_formacao_ddi_d13_oferta_v2": Template(
        name="ana_capcut_acel_formacao_ddi_d13_oferta_v2", num=16,
        state="acel_formacao_ddi", day=13, has_buttons=True,
        buttons=["Quero conversar", "Agora não"],
    ),
    # ── Bloco 8: Acelerada — Diagnóstico ──
    "ana_capcut_acel_diagnostico_d11_contexto_v2": Template(
        name="ana_capcut_acel_diagnostico_d11_contexto_v2", num=17,
        state="acel_diagnostico", day=11, has_buttons=True,
        buttons=["Quero entender", "Agora não"],
    ),
    "ana_capcut_acel_diagnostico_d13_oferta_v2": Template(
        name="ana_capcut_acel_diagnostico_d13_oferta_v2", num=18,
        state="acel_diagnostico", day=13, has_buttons=True,
        buttons=["Quero entender", "Agora não"],
    ),
    # ── Bloco 9: Acelerada — Kasulo ──
    "ana_capcut_acel_kasulo_d11_contexto_v2": Template(
        name="ana_capcut_acel_kasulo_d11_contexto_v2", num=19,
        state="acel_kasulo", day=11, has_buttons=True,
        buttons=["Quero entender", "Agora não"],
    ),
    "ana_capcut_acel_kasulo_d13_oferta_v2": Template(
        name="ana_capcut_acel_kasulo_d13_oferta_v2", num=20,
        state="acel_kasulo", day=13, has_buttons=True,
        buttons=["Quero conversar", "Agora não"],
    ),
    # ── Bloco 10: Fria (reativação) ──
    "ana_capcut_fria_d03_reenvio_acesso_v2": Template(
        name="ana_capcut_fria_d03_reenvio_acesso_v2", num=21,
        state="fria", day=3, has_buttons=True,
        buttons=["Enviar acesso", "Já consegui", "Preciso de ajuda"],
    ),
    "ana_capcut_fria_d05_confirmacao_acesso_v2": Template(
        name="ana_capcut_fria_d05_confirmacao_acesso_v2", num=22,
        state="fria", day=5, has_buttons=True,
        buttons=["Deu certo", "Preciso de ajuda"],
    ),
    "ana_capcut_fria_d07_inicio_curso_v2": Template(
        name="ana_capcut_fria_d07_inicio_curso_v2", num=23,
        state="fria", day=7, has_buttons=True,
        buttons=["Já comecei", "Ainda não comecei", "Preciso de ajuda"],
    ),
    "ana_capcut_fria_d10_dificuldade_v2": Template(
        name="ana_capcut_fria_d10_dificuldade_v2", num=24,
        state="fria", day=10, has_buttons=False,
        is_open_question=True,
    ),
    "ana_capcut_fria_d14_nivel_edicao_v2": Template(
        name="ana_capcut_fria_d14_nivel_edicao_v2", num=25,
        state="fria", day=14, has_buttons=True,
        buttons=["Iniciante", "Intermediário", "Avançado"],
    ),
    "ana_capcut_fria_d22_motivacao_compra_v2": Template(
        name="ana_capcut_fria_d22_motivacao_compra_v2", num=26,
        state="fria", day=22, has_buttons=False,
        is_open_question=True,
    ),
    "ana_capcut_fria_d28_bloqueio_inicio_v2": Template(
        name="ana_capcut_fria_d28_bloqueio_inicio_v2", num=27,
        state="fria", day=28, has_buttons=True,
        buttons=["Falta de tempo", "Dificuldade técnica", "Outro motivo"],
    ),
    "ana_capcut_fria_d35_uso_capcut_v2": Template(
        name="ana_capcut_fria_d35_uso_capcut_v2", num=28,
        state="fria", day=35, has_buttons=True,
        buttons=["Uso hoje", "Ainda não uso", "Preciso de ajuda"],
    ),
    "ana_capcut_fria_d52_objetivo_30_dias_v2": Template(
        name="ana_capcut_fria_d52_objetivo_30_dias_v2", num=29,
        state="fria", day=52, has_buttons=False,
        is_open_question=True,
    ),
    "ana_capcut_fria_d65_referencia_criador_v2": Template(
        name="ana_capcut_fria_d65_referencia_criador_v2", num=30,
        state="fria", day=65, has_buttons=False,
        is_open_question=True,
    ),
    "ana_capcut_fria_d80_reativacao_acesso_v2": Template(
        name="ana_capcut_fria_d80_reativacao_acesso_v2", num=31,
        state="fria", day=80, has_buttons=True,
        buttons=["Quero continuar", "Sem tempo agora", "Não quero mais"],
    ),
    "ana_capcut_fria_d100_gatilho_inicio_v2": Template(
        name="ana_capcut_fria_d100_gatilho_inicio_v2", num=32,
        state="fria", day=100, has_buttons=False,
        is_open_question=True,
    ),
    "ana_capcut_fria_d120_reativacao_final_v2": Template(
        name="ana_capcut_fria_d120_reativacao_final_v2", num=33,
        state="fria", day=120, has_buttons=True,
        buttons=["Quero aprender", "Parar mensagens"],
    ),
    # ── Bloco 11: Follow-ups Diagnóstico ──
    "ana_diagnostico_followup_01_v2": Template(
        name="ana_diagnostico_followup_01_v2", num=34,
        state="diagnostico_followup", day=0, has_buttons=True,
        buttons=["Tenho uma dúvida", "Quero avançar", "Agora não"],
    ),
    "ana_diagnostico_followup_02_v2": Template(
        name="ana_diagnostico_followup_02_v2", num=35,
        state="diagnostico_followup", day=0, has_buttons=True,
        buttons=["Pode chamar", "Prefiro não"],
    ),
    # ── Bloco 12: Follow-ups Kasulo ──
    "ana_kasulo_followup_01_v2": Template(
        name="ana_kasulo_followup_01_v2", num=36,
        state="kasulo_followup", day=0, has_buttons=True,
        buttons=["Tenho uma dúvida", "Quero avançar", "Agora não"],
    ),
    "ana_kasulo_followup_02_v2": Template(
        name="ana_kasulo_followup_02_v2", num=37,
        state="kasulo_followup", day=0, has_buttons=True,
        buttons=["Pode chamar", "Prefiro não"],
    ),
}

# ═══════════════════════════════════════════════════════════════
# State Flow Definition
# ═══════════════════════════════════════════════════════════════

# For each state, the ordered sequence of templates and what
# happens after each one is sent (or after a response).
#
# Format:
#   (template_name, condition_to_send, on_success_next, on_silence_template)
#
# "on_success_next" can be:
#   - a template name (schedule this next)
#   - None (end of this state's sequence)
#   - a dict mapping button text → template name

# Default fria sequence — any response breaks out to engajada
FRIA_SEQUENCE = [
    "ana_capcut_fria_d03_reenvio_acesso_v2",       # D+3
    "ana_capcut_fria_d05_confirmacao_acesso_v2",    # D+5
    "ana_capcut_fria_d07_inicio_curso_v2",          # D+7
    "ana_capcut_fria_d10_dificuldade_v2",           # D+10
    "ana_capcut_fria_d14_nivel_edicao_v2",          # D+14
    "ana_capcut_fria_d22_motivacao_compra_v2",      # D+22
    "ana_capcut_fria_d28_bloqueio_inicio_v2",       # D+28
    "ana_capcut_fria_d35_uso_capcut_v2",             # D+35
    "ana_capcut_fria_d52_objetivo_30_dias_v2",      # D+52
    "ana_capcut_fria_d65_referencia_criador_v2",     # D+65
    "ana_capcut_fria_d80_reativacao_acesso_v2",     # D+80
    "ana_capcut_fria_d100_gatilho_inicio_v2",        # D+100
    "ana_capcut_fria_d120_reativacao_final_v2",     # D+120
]

# Default engajada sequence
ENGAJADA_SEQUENCE = [
    "ana_capcut_engajada_d05_primeiro_video_v2",    # D+5
    "ana_capcut_engajada_d10_diagnostico_v2",       # D+10
    "ana_capcut_engajada_d17_virada_identidade_v2", # D+17 (only if no response to D+10)
    "ana_capcut_engajada_d31_oferta_conteudo_v2",   # D+31
    "ana_capcut_engajada_d38_followup_conteudo_v2", # D+38
]

# Accelerated sequences (context + offer pairs)
ACEL_SEQUENCES = {
    "acel_feed": [
        "ana_capcut_acel_feed_d11_contexto_v2",
        "ana_capcut_acel_feed_d13_oferta_v2",
    ],
    "acel_conteudo": [
        "ana_capcut_acel_conteudo_d11_contexto_v2",
        "ana_capcut_acel_conteudo_d13_oferta_v2",
    ],
    "acel_mpi": [
        "ana_capcut_acel_mpi_d11_contexto_v2",
        "ana_capcut_acel_mpi_d13_oferta_v2",
    ],
    "acel_manual_ddi": [
        "ana_capcut_acel_manual_ddi_d11_contexto_v2",
        "ana_capcut_acel_manual_ddi_d13_oferta_v2",
    ],
    "acel_formacao_ddi": [
        "ana_capcut_acel_formacao_ddi_d11_contexto_v2",
        "ana_capcut_acel_formacao_ddi_d13_oferta_v2",
    ],
    "acel_diagnostico": [
        "ana_capcut_acel_diagnostico_d11_contexto_v2",
        "ana_capcut_acel_diagnostico_d13_oferta_v2",
    ],
    "acel_kasulo": [
        "ana_capcut_acel_kasulo_d11_contexto_v2",
        "ana_capcut_acel_kasulo_d13_oferta_v2",
    ],
}

# Product names → state mapping
PRODUCT_STATE_MAP = {
    "capcut_wow": "ativacao",
    "feed_wow": "acel_feed",
    "conteudo_wow": "acel_conteudo",
    "meu_primeiro_infoproduto": "acel_mpi",
    "manual_ddi": "acel_manual_ddi",
    "formacao_ddi": "acel_formacao_ddi",
    "diagnostico": "acel_diagnostico",
    "kasulo": "acel_kasulo",
    "combo_wow": "ativacao",
}

PRODUCT_TAG_MAP = {
    "combo wow": "combo_wow",
    "capcut wow": "capcut_wow",
    "feed wow": "feed_wow",
    "conteúdo wow": "conteudo_wow",
    "conteudo wow": "conteudo_wow",
    "meu primeiro infoproduto": "meu_primeiro_infoproduto",
    "manual ddi": "manual_ddi",
    "formação ddi": "formacao_ddi",
    "formacao ddi": "formacao_ddi",
    "diagnóstico": "diagnostico",
    "diagnostico": "diagnostico",
    "kasulo": "kasulo",
}

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _resolve_product_tag(product_name: str) -> str:
    name = product_name.lower()
    for keyword, tag in PRODUCT_TAG_MAP.items():
        if keyword in name:
            return tag
    return "unknown"

def _get_template(template_name: str) -> Optional[Template]:
    return TEMPLATES.get(template_name)

def _next_fria_template(current_template: str) -> Optional[str]:
    """Return the next template in the fria sequence, or None if at the end."""
    try:
        idx = FRIA_SEQUENCE.index(current_template)
        if idx + 1 < len(FRIA_SEQUENCE):
            return FRIA_SEQUENCE[idx + 1]
    except ValueError:
        pass
    return None

def _next_engajada_template(current_template: str) -> Optional[str]:
    """Return the next template in the engajada sequence, or None if at the end."""
    try:
        idx = ENGAJADA_SEQUENCE.index(current_template)
        if idx + 1 < len(ENGAJADA_SEQUENCE):
            return ENGAJADA_SEQUENCE[idx + 1]
    except ValueError:
        pass
    return None

def _next_acel_template(state: str, current_template: str) -> Optional[str]:
    """Return the next template in an accelerated sequence."""
    seq = ACEL_SEQUENCES.get(state, [])
    try:
        idx = seq.index(current_template)
        if idx + 1 < len(seq):
            return seq[idx + 1]
    except ValueError:
        pass
    return None

def _days_until(target_day: int, from_day: int) -> int:
    """How many days from `from_day` to reach `target_day`."""
    return max(1, target_day - from_day)


# ═══════════════════════════════════════════════════════════════
# Core Journey Functions
# ═══════════════════════════════════════════════════════════════

async def create_journey(
    contact_id: str,
    phone: str,
    full_name: str,
    product_name: str,
    platform: str,
    platform_order_id: Optional[str],
    amount_cents: Optional[int],
) -> dict:
    """
    Called on purchase_approved. Creates a new journey or updates
    an existing one with the purchased product.
    """
    db = await get_supabase()
    product_tag = _resolve_product_tag(product_name)
    now = _now()

    # Check for existing active journey for this phone
    existing = await (
        db.table("contact_journeys")
        .select("*")
        .eq("phone", phone)
        .eq("status", "active")
        .execute()
    )

    tags = [product_tag, "ativo"]
    purchased = [product_tag]

    if existing.data:
        journey = existing.data[0]
        # Merge purchased products
        existing_products = journey.get("purchased_products") or []
        for p in existing_products:
            if p not in purchased:
                purchased.append(p)
        # Merge tags
        existing_tags = journey.get("tags") or []
        for t in existing_tags:
            if t not in tags and t not in ("frio",):  # remove frio on new purchase
                tags.append(t)

        await (
            db.table("contact_journeys")
            .update({
                "current_state": "ativacao",
                "current_stage": "ativacao",
                "tags": tags,
                "purchased_products": purchased,
                "day_offset": 0,
                "entry_product": product_tag,
                "entry_platform": platform,
                "entry_order_id": platform_order_id,
                "amount_cents": amount_cents,
                "status": "active",
                "last_template": None,
                "last_response_at": None,
                "last_response_text": None,
                "last_response_button": None,
                "updated_at": now.isoformat(),
            })
            .eq("id", journey["id"])
            .execute()
        )
        journey_id = journey["id"]
        logger.info(f"Journey UPDATED: {journey_id} for {phone} product={product_tag}")

        # Cancel any pending journey messages from previous journey
        await (
            db.table("journey_messages")
            .update({"status": "cancelled"})
            .eq("journey_id", journey_id)
            .eq("status", "pending")
            .execute()
        )
    else:
        result = await (
            db.table("contact_journeys")
            .insert({
                "contact_id": contact_id,
                "phone": phone,
                "full_name": full_name,
                "current_state": "ativacao",
                "current_stage": "ativacao",
                "tags": tags,
                "purchased_products": purchased,
                "day_offset": 0,
                "entry_product": product_tag,
                "entry_platform": platform,
                "entry_order_id": platform_order_id,
                "amount_cents": amount_cents,
                "status": "active",
            })
            .execute()
        )
        journey_id = result.data[0]["id"]
        logger.info(f"Journey CREATED: {journey_id} for {phone} product={product_tag}")

    # Schedule first template (D+1)
    await _schedule_journey_message(
        journey_id=journey_id,
        contact_id=contact_id,
        phone=phone,
        template_name="ana_capcut_ativacao_d01_acesso_v2",
        message_number=1,
        state="ativacao",
        scheduled_for=now + timedelta(days=1),
    )

    return {"status": "journey_started", "journey_id": journey_id, "product": product_tag}


async def _schedule_journey_message(
    journey_id: str,
    contact_id: str,
    phone: str,
    template_name: str,
    message_number: int,
    state: str,
    scheduled_for: datetime,
) -> str:
    """Insert a message into journey_messages and return its ID."""
    db = await get_supabase()
    result = await (
        db.table("journey_messages")
        .insert({
            "journey_id": journey_id,
            "contact_id": contact_id,
            "phone": phone,
            "template_name": template_name,
            "message_number": message_number,
            "state_at_send": state,
            "status": "pending",
            "scheduled_for": scheduled_for.isoformat(),
        })
        .execute()
    )
    msg_id = result.data[0]["id"]
    logger.info(f"Scheduled journey msg {msg_id}: {template_name} for {scheduled_for.isoformat()}")
    return msg_id


async def process_response(
    phone: str,
    button_text: Optional[str] = None,
    text_body: Optional[str] = None,
) -> dict:
    """
    Called by the Meta webhook when an incoming message/button arrives.
    Evaluates the response against the current journey state and transitions.
    """
    db = await get_supabase()

    # Find active journey
    result = await (
        db.table("contact_journeys")
        .select("*")
        .eq("phone", phone)
        .eq("status", "active")
        .execute()
    )

    if not result.data:
        logger.info(f"No active journey for {phone} — ignoring response")
        return {"status": "no_active_journey"}

    journey = result.data[0]
    state = journey["current_state"]
    last_template = journey.get("last_template")
    tags = list(journey.get("tags") or [])
    now = _now()

    update_data = {
        "last_response_at": now.isoformat(),
        "last_response_text": text_body,
        "last_response_button": button_text,
        "updated_at": now.isoformat(),
    }

    # ── Handle "Preciso de ajuda" / "Parar mensagens" / "Não quero mais" ──
    stop_buttons = {"Preciso de ajuda", "Parar mensagens", "Não quero mais", "Prefiro não"}
    if button_text in stop_buttons:
        new_state = "suporte" if button_text == "Preciso de ajuda" else "opted_out"
        update_data["current_state"] = new_state
        update_data["status"] = new_state if new_state == "opted_out" else "active"
        if new_state == "opted_out":
            update_data["completed_reason"] = "user_opted_out"

        await db.table("contact_journeys").update(update_data).eq("id", journey["id"]).execute()

        # Cancel pending messages
        await (
            db.table("journey_messages")
            .update({"status": "cancelled"})
            .eq("journey_id", journey["id"])
            .eq("status", "pending")
            .execute()
        )

        return {"status": "ok", "transition": f"→ {new_state}", "action": "stop"}

    # ── Fria: any response → engajada ──
    if state == "fria":
        # Remove 'frio' tag, add 'ativo', transition to engajada
        if "frio" in tags:
            tags.remove("frio")
        if "ativo" not in tags:
            tags.append("ativo")

        update_data["current_state"] = "engajada"
        update_data["current_stage"] = "engajada"
        update_data["tags"] = tags

        await db.table("contact_journeys").update(update_data).eq("id", journey["id"]).execute()

        # Cancel pending fria messages
        await (
            db.table("journey_messages")
            .update({"status": "cancelled"})
            .eq("journey_id", journey["id"])
            .eq("status", "pending")
            .execute()
        )

        # Schedule engajada sequence starting from template 02 at D+5
        await _schedule_journey_message(
            journey_id=journey["id"],
            contact_id=journey["contact_id"],
            phone=phone,
            template_name="ana_capcut_engajada_d05_primeiro_video_v2",
            message_number=journey["messages_sent"] + 1,
            state="engajada",
            scheduled_for=now + timedelta(days=5),
        )

        return {"status": "ok", "transition": "fria → engajada", "action": "schedule_engajada"}

    # ── Ativacao: response defines next step ──
    if state == "ativacao":
        if button_text == "Acesso certo":
            update_data["current_state"] = "engajada"
            update_data["current_stage"] = "engajada"

            await db.table("contact_journeys").update(update_data).eq("id", journey["id"]).execute()

            await (
                db.table("journey_messages")
                .update({"status": "cancelled"})
                .eq("journey_id", journey["id"])
                .eq("status", "pending")
                .execute()
            )

            await _schedule_journey_message(
                journey_id=journey["id"],
                contact_id=journey["contact_id"],
                phone=phone,
                template_name="ana_capcut_engajada_d05_primeiro_video_v2",
                message_number=journey["messages_sent"] + 1,
                state="engajada",
                scheduled_for=now + timedelta(days=5),
            )

            return {"status": "ok", "transition": "ativacao → engajada"}

    # ── Engajada: process response ──
    if state == "engajada":
        if last_template == "ana_capcut_engajada_d10_diagnostico_v2":
            # Open question answered — skip template 04, schedule template 05
            new_day = 31
            await db.table("contact_journeys").update({
                **update_data,
                "day_offset": new_day,
            }).eq("id", journey["id"]).execute()

            await (
                db.table("journey_messages")
                .update({"status": "cancelled"})
                .eq("journey_id", journey["id"])
                .eq("status", "pending")
                .execute()
            )

            await _schedule_journey_message(
                journey_id=journey["id"],
                contact_id=journey["contact_id"],
                phone=phone,
                template_name="ana_capcut_engajada_d31_oferta_conteudo_v2",
                message_number=journey["messages_sent"] + 1,
                state="engajada",
                scheduled_for=now + timedelta(days=max(1, 31 - (journey.get("day_offset") or 0))),
            )

            return {"status": "ok", "transition": "engajada: skip 04 → 05"}

        if last_template in (
            "ana_capcut_engajada_d31_oferta_conteudo_v2",
            "ana_capcut_engajada_d38_followup_conteudo_v2",
        ):
            if button_text in ("Quero conhecer", "Quero saber mais"):
                # Positive response — Ana handles manually (or future AI)
                return {"status": "ok", "transition": "interest_shown", "action": "human_handoff"}

    # ── Accelerated: process offer response ──
    if state.startswith("acel_"):
        positive_buttons = {
            "Quero o Feed Wow", "Quero os detalhes", "Quero o acesso",
            "Quero conhecer", "Quero conversar", "Quero entender",
        }
        if button_text in positive_buttons:
            return {"status": "ok", "transition": "offer_accepted", "action": "human_handoff"}
        elif button_text == "Agora não":
            # End accelerated route, go to engajada default
            update_data["current_state"] = "engajada"
            update_data["current_stage"] = "engajada"
            await db.table("contact_journeys").update(update_data).eq("id", journey["id"]).execute()

            await (
                db.table("journey_messages")
                .update({"status": "cancelled"})
                .eq("journey_id", journey["id"])
                .eq("status", "pending")
                .execute()
            )

            await _schedule_journey_message(
                journey_id=journey["id"],
                contact_id=journey["contact_id"],
                phone=phone,
                template_name="ana_capcut_engajada_d31_oferta_conteudo_v2",
                message_number=journey["messages_sent"] + 1,
                state="engajada",
                scheduled_for=now + timedelta(days=1),  # next reasonable time
            )

            return {"status": "ok", "transition": "acel → engajada (recusou)"}

    # ── Default: any response = ATIVO ──
    if "ativo" not in tags:
        tags.append("ativo")
    update_data["tags"] = tags
    await db.table("contact_journeys").update(update_data).eq("id", journey["id"]).execute()

    return {"status": "ok", "transition": "response_registered", "action": "continue_flow"}


async def schedule_next(journey_id: str, sent_template_name: str) -> dict:
    """
    Called by the scheduler after successfully sending a journey message.
    Determines the next template to send and schedules it.
    """
    db = await get_supabase()

    result = await (
        db.table("contact_journeys")
        .select("*")
        .eq("id", journey_id)
        .eq("status", "active")
        .execute()
    )

    if not result.data:
        return {"status": "journey_not_active"}

    journey = result.data[0]
    state = journey["current_state"]
    tags = list(journey.get("tags") or [])
    now = _now()

    template = _get_template(sent_template_name)
    if not template:
        logger.warning(f"Unknown template: {sent_template_name}")
        return {"status": "unknown_template"}

    new_day = template.day
    next_template: Optional[str] = None
    next_day: int = new_day

    # ── Ativacao → wait for response or timeout to fria ──
    if state == "ativacao":
        # Template 01 sent. If student responds, process_response handles it.
        # If no response after 48h, transition to fria.
        # For now, just update the journey and let the scheduler handle silence.
        next_template = None  # no auto-schedule; timeout logic handles it

    # ── Engajada ──
    elif state == "engajada":
        next_template = _next_engajada_template(sent_template_name)
        if next_template:
            next_t = _get_template(next_template)
            next_day = next_t.day if next_t else new_day + 1

    # ── Accelerated ──
    elif state.startswith("acel_"):
        next_template = _next_acel_template(state, sent_template_name)
        if next_template:
            next_t = _get_template(next_template)
            next_day = next_t.day if next_t else new_day + 1
        elif sent_template_name.endswith("_oferta_v2"):
            # Offer sent — no more auto messages. Response or human handles.
            pass

    # ── Fria ──
    elif state == "fria":
        next_template = _next_fria_template(sent_template_name)
        if next_template:
            next_t = _get_template(next_template)
            next_day = next_t.day if next_t else new_day + 1
        # If last fria template → journey completes

    # ── Follow-ups ──
    elif state == "diagnostico_followup":
        if sent_template_name == "ana_diagnostico_followup_01_v2":
            next_template = "ana_diagnostico_followup_02_v2"
            next_day = new_day + 3  # 72h after first followup
        # After followup_02 → end

    elif state == "kasulo_followup":
        if sent_template_name == "ana_kasulo_followup_01_v2":
            next_template = "ana_kasulo_followup_02_v2"
            next_day = new_day + 3
        # After followup_02 → end

    # ── Update journey ──
    update_data = {
        "day_offset": new_day,
        "last_template": sent_template_name,
        "last_message_sent_at": now.isoformat(),
        "messages_sent": journey["messages_sent"] + 1,
        "updated_at": now.isoformat(),
    }

    # Mark journey as completed if end of sequence
    if next_template is None:
        if state == "fria" and sent_template_name == "ana_capcut_fria_d120_reativacao_final_v2":
            update_data["status"] = "completed"
            update_data["completed_reason"] = "d120_exhausted"
        elif state == "engajada" and sent_template_name == "ana_capcut_engajada_d38_followup_conteudo_v2":
            update_data["status"] = "completed"
            update_data["completed_reason"] = "engajada_route_done"
        elif state in ("diagnostico_followup", "kasulo_followup"):
            if sent_template_name.endswith("_followup_02_v2"):
                update_data["status"] = "completed"
                update_data["completed_reason"] = f"{state}_route_done"

    await db.table("contact_journeys").update(update_data).eq("id", journey_id).execute()

    # ── Schedule next message ──
    if next_template:
        # Calculate when: new_day from entry
        days_ahead = max(1, next_day - journey.get("day_offset", 0))
        scheduled_for = now + timedelta(days=days_ahead)

        await _schedule_journey_message(
            journey_id=journey_id,
            contact_id=journey["contact_id"],
            phone=journey["phone"],
            template_name=next_template,
            message_number=journey["messages_sent"] + 2,
            state=state,
            scheduled_for=scheduled_for,
        )
        return {
            "status": "scheduled",
            "next_template": next_template,
            "scheduled_for": scheduled_for.isoformat(),
            "days_ahead": days_ahead,
        }

    return {"status": "end_of_sequence", "state": state}


async def evaluate_silence(journey_id: str) -> dict:
    """
    Called periodically to check if a journey is stalled (no response
    for 48h+). Transitions from ativacao/engajada → fria when appropriate.
    """
    db = await get_supabase()

    result = await (
        db.table("contact_journeys")
        .select("*")
        .eq("id", journey_id)
        .eq("status", "active")
        .execute()
    )

    if not result.data:
        return {"status": "not_found"}

    journey = result.data[0]
    state = journey["current_state"]
    last_response = journey.get("last_response_at")
    last_message = journey.get("last_message_sent_at")
    tags = list(journey.get("tags") or [])
    now = _now()

    # Need at least one sent message to evaluate
    if not last_message:
        return {"status": "no_messages_sent"}

    last_msg_dt = datetime.fromisoformat(last_message) if isinstance(last_message, str) else last_message
    silence_hours = (now - last_msg_dt).total_seconds() / 3600

    # Only transition to fria if 48h+ of silence
    if silence_hours < 48:
        return {"status": "ok", "silence_hours": round(silence_hours, 1)}

    # If already fria, no change
    if state == "fria":
        return {"status": "already_fria"}

    # If the student has responded after the last message, don't mark as fria
    if last_response:
        last_resp_dt = datetime.fromisoformat(last_response) if isinstance(last_response, str) else last_response
        if last_resp_dt > last_msg_dt:
            return {"status": "has_response", "action": "skip"}

    # Transition to fria
    if "ativo" in tags:
        tags.remove("ativo")
    if "frio" not in tags:
        tags.append("frio")

    # Cancel pending messages
    await (
        db.table("journey_messages")
        .update({"status": "cancelled"})
        .eq("journey_id", journey_id)
        .eq("status", "pending")
        .execute()
    )

    # Schedule first fria message
    fria_template = "ana_capcut_fria_d03_reenvio_acesso_v2"
    await _schedule_journey_message(
        journey_id=journey_id,
        contact_id=journey["contact_id"],
        phone=journey["phone"],
        template_name=fria_template,
        message_number=journey["messages_sent"] + 1,
        state="fria",
        scheduled_for=now + timedelta(hours=1),  # almost immediate
    )

    await (
        db.table("contact_journeys")
        .update({
            "current_state": "fria",
            "current_stage": "fria",
            "tags": tags,
            "updated_at": now.isoformat(),
        })
        .eq("id", journey_id)
        .execute()
    )

    logger.info(f"Journey {journey_id}: transitioned to fria after {silence_hours:.0f}h silence")
    return {"status": "transitioned_to_fria", "silence_hours": round(silence_hours, 1)}
