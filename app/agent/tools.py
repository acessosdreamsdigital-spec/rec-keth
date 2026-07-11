"""
LangChain tools for Júlia — consultative sales + customer care agent.

Tools:
- consultar_produto: product FAQ lookup
- enviar_checkout: send purchase link
- verificar_cliente: check what customer bought + journey status (DB)
- enviar_formulario / enviar_suporte: redirect links
"""

from __future__ import annotations

from langchain_core.tools import tool
import httpx

from app.agent.prompt import CHECKOUT_LINKS, FORMULARIO_DDI, PRODUCT_FAQ, SUPORTE_ALUNOS
from app.config import settings as _settings


def _supa_url() -> str:
    return _settings.supabase_url


def _supa_key() -> str:
    return _settings.supabase_key


def _supa(path: str) -> dict:
    """Sync helper to query Supabase REST API."""
    if not _supa_url() or not _supa_key():
        return {"error": "Database not configured"}
    url = f"{_supa_url()}/rest/v1/{path}"
    headers = {
        "apikey": _supa_key(),
        "Authorization": f"Bearer {_supa_key()}",
    }
    try:
        r = httpx.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json() if r.text else {}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
# Product & checkout tools (unchanged)
# ═══════════════════════════════════════════════════════════════

@tool
def consultar_produto(produto: str) -> str:
    """
    Busca informacoes detalhadas sobre um produto da The Differs Co.
    Use quando o lead pergunta sobre preco, conteudo, bonus, garantia,
    para quem e indicado, ou qualquer duvida especifica sobre um produto.

    Args:
        produto: Nome ou slug do produto. Opcoes:
                 capcut_wow, conteudo_wow, feed_wow, formacao_ddi,
                 manual_ddi, mpi, combo_wow, diagnostico, kasulo
    """
    produto = produto.lower().strip().replace(" ", "_").replace("ç", "c").replace("ã", "a").replace("õ", "o")

    slug_map = {
        "capcut": "capcut_wow", "capcut_wow": "capcut_wow",
        "conteudo": "conteudo_wow", "conteudo_wow": "conteudo_wow", "conteudos_wow": "conteudo_wow",
        "feed": "feed_wow", "feed_wow": "feed_wow",
        "formacao": "formacao_ddi", "formacao_ddi": "formacao_ddi", "ddi": "formacao_ddi",
        "manual": "manual_ddi", "manual_ddi": "manual_ddi", "kit": "manual_ddi",
        "mpi": "mpi", "meu_primeiro": "mpi", "meu_primeiro_infoproduto": "mpi", "infoproduto": "mpi",
        "combo": "combo_wow", "combo_wow": "combo_wow", "5x1": "combo_wow",
        "diagnostico": "diagnostico", "consultoria": "diagnostico",
        "kasulo": "kasulo", "mentoria": "kasulo",
    }

    key = slug_map.get(produto, produto)
    info = PRODUCT_FAQ.get(key)

    if not info:
        available = ", ".join(PRODUCT_FAQ.keys())
        return f"Produtos disponiveis: {available}. Qual desses o lead perguntou?"

    lines = [
        f"📦 {info['nome']}",
        f"🎯 Promessa: {info['promessa']}",
        f"💰 Preco: {info['preco']}",
        f"👤 Para quem: {info['para_quem']}",
    ]
    for field, label in [
        ("metodo", "🧠 Metodo"), ("pilares", "🏛️ Pilares"),
        ("entregaveis", "📦 Entregaveis"), ("ias", "🤖 IAs incluidas"),
        ("bonus", "🎁 Bonus"), ("acesso", "⏱️ Acesso"),
        ("time", "👥 Time"), ("prova_social", "📊 Prova social"),
        ("criadores", "👥 Criadores"),
    ]:
        if field in info:
            lines.append(f"{label}: {info[field]}")
    return "\n".join(lines)


@tool
def enviar_checkout(produto: str, tipo: str = "kiwify") -> str:
    """
    Envia o link de checkout para o lead. Use APENAS quando o lead
    demonstrar interesse claro em comprar ou pedir explicitamente o link.
    Envie UMA UNICA VEZ por produto.

    Args:
        produto: capcut_wow, conteudo_wow, feed_wow, formacao_ddi,
                 manual_ddi, mpi, combo_wow
        tipo: "kiwify" (padrao), "assiny" (backup), "pagina" (pagina de vendas)
    """
    links = CHECKOUT_LINKS.get(produto.lower())
    if not links:
        return f"Sem link para '{produto}'. Disponiveis: {', '.join(CHECKOUT_LINKS.keys())}"
    if tipo == "pagina" and "pagina" in links:
        return f"LINK_PAGINA_VENDAS: {links['pagina']}"
    if tipo == "assiny" and "assiny" in links:
        return f"LINK_CHECKOUT: {links['assiny']}"
    if tipo == "kiwify" and "kiwify" in links:
        return f"LINK_CHECKOUT: {links['kiwify']}"
    for fallback in ("kiwify", "assiny", "pagina"):
        if fallback in links:
            return f"LINK_CHECKOUT: {links[fallback]}"
    return f"Link nao disponivel para {produto}"


@tool
def enviar_formulario() -> str:
    """Envia o link do formulario quando o lead precisa de orientacao personalizada."""
    return f"LINK_FORMULARIO: {FORMULARIO_DDI}"


@tool
def enviar_suporte() -> str:
    """Envia o link do suporte de alunos (problemas tecnicos). Julia NAO faz suporte."""
    return f"LINK_SUPORTE: {SUPORTE_ALUNOS}"


# ═══════════════════════════════════════════════════════════════
# Database tools — customer context + intelligence
# ═══════════════════════════════════════════════════════════════

@tool
def verificar_cliente(whatsapp: str) -> str:
    """
    Verifica tudo sobre o cliente no banco: quais produtos comprou,
    em que etapa da jornada esta, ultima interacao, status.
    Use sempre que iniciar uma conversa pra entender o contexto do lead.
    Tambem use quando o lead perguntar "qual produto eu comprei?" ou
    "como esta meu acesso?".

    Args:
        whatsapp: Numero do WhatsApp do lead (ex: 5521984103779)
    """
    # Normalize phone
    phone = whatsapp.strip().replace("+", "").replace("-", "").replace(" ", "")
    if not phone.startswith("55"):
        phone = "55" + phone

    # 1. Check leads table
    leads = _supa(f"leads?whatsapp=eq.{phone}&select=*&limit=1")
    lead = leads[0] if isinstance(leads, list) and leads else {}

    # 2. Check contacts
    contacts = _supa(f"contacts?phone=eq.{phone}&select=*&limit=1")
    contact = contacts[0] if isinstance(contacts, list) and contacts else {}

    # 3. Check journey
    journeys = _supa(
        f"contact_journeys?phone=eq.{phone}"
        f"&status=in.(active,paused)&select=current_state,current_stage,tags,"
        f"purchased_products,full_name,day_offset,status,messages_sent,last_response_at&limit=1"
    )
    journey = journeys[0] if isinstance(journeys, list) and journeys else {}

    # 4. Check recovery sessions (converted = comprou)
    sessions = _supa(
        f"recovery_sessions?select=product_name,status,created_at&contact_id=eq."
        f"{contact.get('id', '00000000-0000-0000-0000-000000000000')}"
        f"&status=eq.converted&order=created_at.desc&limit=10"
    )
    purchases = []
    if isinstance(sessions, list):
        seen = set()
        for s in sessions:
            pn = s.get("product_name", "")
            if pn and pn not in seen:
                purchases.append(pn)
                seen.add(pn)

    # Build context
    nome = (
        lead.get("nome")
        or contact.get("full_name")
        or journey.get("full_name")
        or "Cliente"
    )

    parts = [f"👤 Nome: {nome}"]

    if purchases:
        parts.append(f"🛒 Produtos comprados: {', '.join(purchases)}")
    elif journey.get("purchased_products"):
        prods = journey["purchased_products"]
        parts.append(f"🛒 Produtos: {', '.join(prods) if isinstance(prods, list) else prods}")

    if journey:
        state_map = {
            "ativacao": "Acabou de comprar (ativação)",
            "engajada": "Engajada com o curso",
            "acel_feed": "Interesse em Feed Wow",
            "acel_conteudo": "Interesse em Conteúdo Wow",
            "acel_mpi": "Interesse em Meu Primeiro Infoproduto",
            "acel_manual_ddi": "Interesse em Manual DDI",
            "acel_formacao_ddi": "Interesse em Formação DDI",
            "acel_diagnostico": "Interesse em Diagnóstico",
            "acel_kasulo": "Interesse em Kasulo",
            "fria": "Trilha fria (sem interação recente)",
            "paused": "Jornada pausada (conversando com humano)",
            "suporte": "Foi para suporte",
        }
        state_name = state_map.get(journey.get("current_state", ""), journey.get("current_state", "?"))
        status = journey.get("status", "?")
        status_label = "🟢 Ativa" if status == "active" else "🟡 Pausada" if status == "paused" else status
        parts.append(f"📍 Jornada: {state_name} ({status_label})")
        parts.append(f"📅 Dia na jornada: D+{journey.get('day_offset', 0)}")
        parts.append(f"✉️ Mensagens enviadas: {journey.get('messages_sent', 0)}")

    if lead.get("last_interaction"):
        parts.append(f"🕐 Última interação: {lead['last_interaction']}")

    # 5. Check lead_insights
    insights = _supa(f"lead_insights?phone=eq.{phone}&select=*&limit=1")
    insight = insights[0] if isinstance(insights, list) and insights else {}
    if insight:
        temp = insight.get("temperatura", "frio")
        tick = insight.get("ticket", "low")
        parts.append(f"🌡️ Temperatura: {temp} | Ticket: {tick}")
        if insight.get("dores"):
            dores = insight["dores"]
            parts.append(f"💢 Dores: {', '.join(dores) if isinstance(dores, list) else dores}")
        if insight.get("ambicoes"):
            ambs = insight["ambicoes"]
            parts.append(f"🎯 Ambições: {', '.join(ambs) if isinstance(ambs, list) else ambs}")
        if insight.get("perfil"):
            parts.append(f"📝 Perfil: {insight['perfil']}")

    return "\n".join(parts)


@tool
def classificar_lead(whatsapp: str, temperatura: str = "", ticket: str = "", estagio: str = "") -> str:
    """
    Atualiza a classificacao do lead no banco. Use quando identificar
    mudancas no perfil durante a conversa — ex: lead demonstrou urgencia
    (marcar quente), lead tem budget alto (ticket high).

    Args:
        whatsapp: Numero do WhatsApp do lead
        temperatura: "quente", "morno", ou "frio" (deixe vazio se nao mudou)
        ticket: "high" ou "low" (deixe vazio se nao mudou)
        estagio: "consciencia", "consideracao", "decisao", ou "cliente" (deixe vazio se nao mudou)
    """
    phone = whatsapp.strip().replace("+", "").replace("-", "").replace(" ", "")
    if not phone.startswith("55"):
        phone = "55" + phone

    updates = {}
    if temperatura and temperatura in ("quente", "morno", "frio"):
        updates["temperatura"] = temperatura
    if ticket and ticket in ("high", "low"):
        updates["ticket"] = ticket
    if estagio and estagio in ("consciencia", "consideracao", "decisao", "cliente"):
        updates["estagio"] = estagio

    if not updates:
        return "Nenhuma classificacao valida fornecida. Use quente/morno/frio, high/low, ou um estagio valido."

    from datetime import datetime, timezone
    updates["ultima_analise"] = datetime.now(timezone.utc).isoformat()
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Upsert
    existing = _supa(f"lead_insights?phone=eq.{phone}&select=id&limit=1")
    if isinstance(existing, list) and existing:
        # Update
        url = f"{_supa_url()}/rest/v1/lead_insights?id=eq.{existing[0]['id']}"
        headers = {
            "apikey": _supa_key(),
            "Authorization": f"Bearer {_supa_key()}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }
        try:
            httpx.patch(url, headers=headers, json=updates, timeout=10)
        except Exception:
            pass
    else:
        updates["phone"] = phone
        url = f"{_supa_url()}/rest/v1/lead_insights"
        headers = {
            "apikey": _supa_key(),
            "Authorization": f"Bearer {_supa_key()}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }
        try:
            httpx.post(url, headers=headers, json=updates, timeout=10)
        except Exception:
            pass

    campos = ", ".join(f"{k}={v}" for k, v in updates.items() if k not in ("ultima_analise", "updated_at"))
    return f"Lead {phone} atualizado: {campos}"
