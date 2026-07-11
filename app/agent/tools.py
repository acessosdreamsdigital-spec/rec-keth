"""
LangChain tools for Júlia — WhatsApp sales recovery agent.

Tools:
- consultar_produto: look up detailed product info from the embedded FAQ
- enviar_checkout: send a checkout link to the lead
"""

from __future__ import annotations

from langchain_core.tools import tool

from app.agent.prompt import CHECKOUT_LINKS, FORMULARIO_DDI, PRODUCT_FAQ, SUPORTE_ALUNOS


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

    # Fuzzy match
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
        return (
            f"Nao encontrei esse produto especifico. "
            f"Os produtos disponiveis sao: {available}. "
            f"Tenta me falar de outro jeito qual produto o lead perguntou?"
        )

    lines = [
        f"📦 {info['nome']}",
        f"🎯 Promessa: {info['promessa']}",
        f"💰 Preco: {info['preco']}",
        f"👤 Para quem: {info['para_quem']}",
    ]

    if "metodo" in info:
        lines.append(f"🧠 Metodo: {info['metodo']}")
    if "pilares" in info:
        lines.append(f"🏛️ Pilares: {info['pilares']}")
    if "entregaveis" in info:
        lines.append(f"📦 Entregaveis: {info['entregaveis']}")
    if "ias" in info:
        lines.append(f"🤖 IAs incluidas: {info['ias']}")
    if "bonus" in info:
        lines.append(f"🎁 Bonus: {info['bonus']}")
    if "acesso" in info:
        lines.append(f"⏱️ Acesso: {info['acesso']}")
    if "time" in info:
        lines.append(f"👥 Time: {info['time']}")
    if "prova_social" in info:
        lines.append(f"📊 Prova social: {info['prova_social']}")
    if "criadores" in info:
        lines.append(f"👥 Criadores: {info['criadores']}")

    return "\n".join(lines)


@tool
def enviar_checkout(produto: str, tipo: str = "kiwify") -> str:
    """
    Envia o link de checkout para o lead. Use APENAS quando o lead
    demonstrar interesse claro em comprar ou pedir explicitamente o link.
    Envie UMA UNICA VEZ por produto.

    Args:
        produto: Slug do produto (capcut_wow, conteudo_wow, feed_wow,
                 formacao_ddi, manual_ddi, mpi, combo_wow)
        tipo: "kiwify" (padrao, prioridade) ou "assiny" (backup, se lead
              reportar problema com Kiwify) ou "pagina" (pagina de vendas,
              se lead quiser ver mais antes de comprar)
    """
    links = CHECKOUT_LINKS.get(produto.lower())
    if not links:
        return f"Nao tenho o link de checkout para '{produto}'. Produtos com link: {', '.join(CHECKOUT_LINKS.keys())}"

    if tipo == "pagina" and "pagina" in links:
        return f"LINK_PAGINA_VENDAS: {links['pagina']}"

    if tipo == "assiny" and "assiny" in links:
        return f"LINK_CHECKOUT: {links['assiny']}"

    if tipo == "kiwify" and "kiwify" in links:
        return f"LINK_CHECKOUT: {links['kiwify']}"

    # Fallback: return whatever is available
    for fallback in ("kiwify", "assiny", "pagina"):
        if fallback in links:
            return f"LINK_CHECKOUT: {links[fallback]}"

    return f"Link nao disponivel para {produto}"


@tool
def enviar_formulario() -> str:
    """
    Envia o link do formulario The Differs Co. para quando o lead:
    - Nao sabe qual produto e ideal pra ele
    - Quer orientacao personalizada
    - Pergunta sobre mentoria/consultoria
    - Precisa de analise individual do perfil
    """
    return f"LINK_FORMULARIO: {FORMULARIO_DDI}"


@tool
def enviar_suporte() -> str:
    """
    Envia o link do suporte de alunos. Use SOMENTE quando o lead
    JA FOR aluno e tiver problema tecnico (acesso, login, plataforma).
    Julia NAO faz suporte tecnico.
    """
    return f"LINK_SUPORTE: {SUPORTE_ALUNOS}"
