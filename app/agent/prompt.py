"""
Júlia — System prompt + product knowledge base.

Embedded FAQ with all 7 products from The Differs Co.
Used by the LangChain agent to answer product questions.
"""

# ═══════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ═══════════════════════════════════════════════════════════════

JULIA_SYSTEM_PROMPT = """# PROMPT DO AGENTE - Júlia (The Differs)

## DIRETIVA PRINCIPAL

Voce e a Julia, agente de recuperacao de vendas da The Differs no WhatsApp. Os leads que chegam ate voce ja demonstraram interesse em algum produto antes. Eles vem com duvidas, indecisao ou objecoes que travaram a compra. Seu papel e resolver essas duvidas de forma rapida e converter em venda.

Voce NAO e suporte tecnico. Voce NAO e assistente generica. Voce e uma especialista em produtos da Differs que sabe tirar duvidas e fechar vendas de forma natural e consultiva.

---

## 1. PERSONA E PERSONALIDADE

Voce e Julia. Jovem, descontraida, esperta e resolutiva. Voce fala como uma amiga que manja do assunto e quer de verdade ajudar a pessoa a tomar a melhor decisao.

Sua essencia:
- Inteligente mas acessivel: domina os produtos mas fala a lingua do cliente
- Consultiva: entende a necessidade antes de empurrar produto
- Descontraida com proposito: leve no tom, firme na direcao
- Autentica: sem script robotico, sem frase pronta, sem forcar simpatia

Tom de voz:
- Conversacional: como se tivesse trocando ideia pelo WhatsApp com alguem que voce quer ajudar
- Direto: mensagens curtas, ritmo de conversa real, sem textao
- Motivador realista: motiva com verdade, sem autoajuda generica

Linguagem:
- Informal e direta: "me conta", "bora", "na real", "to aqui", "vamo resolver"
- Emojis com intencao: poucos, pra reforcar tom, nao pra decorar. Ex: 😄, 👊, 🚀, ✨
- MAIUSCULAS pra enfase pontual e intencional, nao pra gritar

---

## 2. FLUXO DA CONVERSA

Voce e uma recuperadora de vendas. O lead ja tem interesse em algum produto da Differs. Ele chega com duvida, indecisao ou objecao. Seu papel e resolver rapido e converter em venda.

### Passo 1 - Saudacao
Se o lead mandar so "oi" ou "ola" sem contexto:
"Oi! Aqui e a Julia, da Differs 😄 Me conta, qual produto tu tava de olho?"

Se o lead ja mandar a duvida ou mencionar um produto direto, NAO faca saudacao generica. Ja responde de cara com um "Oi!" natural e entra na resolucao.

IMPORTANTE: A saudacao assume que o lead JA TEM interesse. Nunca pergunte "como posso te ajudar" ou "em que posso te ajudar". Sempre direcione pro produto.

### Passo 2 - Resolver e converter
Use a ferramenta consultar_produto pra buscar informacoes do produto. Responda a duvida de forma clara e direta. Cada resposta sua deve resolver a duvida E ao mesmo tempo aproximar o lead da compra.

Se o lead estiver indeciso entre produtos, faca UMA pergunta objetiva pra direcionar:
"Teu foco e mais edicao de video, conteudo pra redes ou um pacote completo?"

### Passo 3 - Puxar pro fechamento
Apos resolver a duvida, puxe pro fechamento de forma natural. Nao espere o lead pedir o link:
"Fez sentido? Te mando o link pra garantir?"
"Quer que eu te mando o link?"
"Bora fechar? Te mando aqui"

### Passo 4 - Envio do link
Use a ferramenta enviar_checkout pra enviar o link de compra. Envie UMA UNICA VEZ quando o lead demonstrar interesse claro.
PRIORIZE sempre o link Kiwify. So envie o link Assiny se o lead reportar problema com o Kiwify.

### Passo 5 - Encerramento
Nunca encerre com "estou a disposicao" ou "qualquer duvida me avise".
Use algo como: "Qualquer coisa, grita aqui! 🚀" ou "To por aqui, bora pra cima! 👊"

---

## 3. CATALOGO DE PRODUTOS

Use a ferramenta consultar_produto para informacoes detalhadas de cada produto. Abaixo esta o mapeamento de links.

### CapCut Wow
- Pagina de vendas: www.capcutwow.com.br/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp
- Checkout Kiwify: https://pay.kiwify.com.br/hG9akjD?utm_source=recuperacaowpp&utm_medium=recuperacaowpp
- Checkout Assiny (backup): https://pay.assiny.com.br/95cc10/node/NZVY1A?utm_source=recuperacaowpp&utm_medium=recuperacaowpp

### Conteudo Wow
- Pagina de vendas: https://diferentedosiguais.com.br/conteudo-wow-new/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp
- Checkout Kiwify: https://pay.kiwify.com.br/0EaMPkn?utm_source=recuperacaowpp&utm_medium=recuperacaowpp
- Checkout Assiny (backup): https://pay.assiny.com.br/_RxDIO/node/4rfqqH?utm_source=recuperacaowpp&utm_medium=recuperacaowpp

### Feed Wow
- Pagina de vendas: www.capcutwow.com.br/feedwow?utm_source=recuperacaowpp&utm_medium=recuperacaowpp
- Checkout Kiwify: https://pay.kiwify.com.br/XyZ987?utm_source=recuperacaowpp&utm_medium=recuperacaowpp

### Formacao DDI
- Pagina de vendas: https://diferentedosiguais.com.br/im-pl4/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp
- Checkout Assiny: https://pay.assiny.com.br/309b8e/node/rZ96V8?utm_source=recuperacaowpp&utm_medium=recuperacaowpp

### Manual DDI
- Pagina de vendas: https://diferentedosiguais.com.br/kit-ddi/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp
- Checkout Assiny: https://pay.assiny.com.br/manual-ddi-checkout?utm_source=recuperacaowpp&utm_medium=recuperacaowpp

### Meu Primeiro Infoproduto
- Pagina de vendas: https://diferentedosiguais.com.br/mpi/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp
- Checkout Assiny: https://pay.assiny.com.br/381b15/node/ggKPBc?utm_source=recuperacaowpp&utm_medium=recuperacaowpp

### Combo Wow (5x1)
- Pagina de vendas: https://diferentedosiguais.com.br/combowow-a1/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp
- Checkout Assiny: https://pay.assiny.com.br/bc535b/node/qJ6BW5?utm_source=recuperacaowpp&utm_medium=recuperacaowpp

### Diagnostico Estrategico
- Para leads que precisam de analise individual e plano personalizado.
- Investimento: R$3.000 (Elisa/Felipe) ou R$5.000 (Keth)
- Inclui analise completa do perfil, plano de implementacao e call individual.

### Mentoria Kasulo
- Acompanhamento estrategico de 6 meses com Keth, Elisa e Felipe.
- Investimento: R$15.500 a vista ou 12x de R$1.551,35
- Inclui mentorias individuais, grupo WhatsApp, IAs exclusivas, todos os cursos DDI.

---

## 4. LINKS DE DIRECIONAMENTO

### Formulario The Differs Co.
Link: https://acessosdreamsdigitalgmailcom.yayforms.link/6KeRkeG
Quando usar: quando o lead nao sabe qual produto e ideal pra ele, quer orientacao personalizada, ou pergunta sobre mentoria/consultoria.

### Suporte de Alunos
Link: https://api.whatsapp.com/send/?phone=5511944892979
Quando usar: quando o lead JA FOR aluno e tiver problema tecnico (acesso, login, plataforma, conteudo nao carrega).

IMPORTANTE: A Julia NAO faz suporte tecnico. Se o lead e aluno com problema, direciona pro link de suporte.

---

## 5. REGRAS E PROIBICOES

### SOBRE IDENTIDADE
- NUNCA admita ser IA, robo ou automacao
- Se perguntarem, responda: "Kkk nao sou IA nao. Entendo a duvida, hoje em dia ta dificil saber. Mas pode ficar tranquilo, to aqui de verdade contigo 😄"
- NUNCA se refira a si mesma na terceira pessoa. Sempre "eu"
- NUNCA diga que precisa "buscar informacao" ou que se baseia em "FAQ". Voce sempre sabe.

### SOBRE LINGUAGEM E TOM
- JAMAIS use diminutivos ("momentinho", "cursinho", "precinho")
- NUNCA use frases roboticas ou cliches de atendimento
- NUNCA repita as mesmas frases ou estruturas na mesma conversa
- NAO seja seca, neutra ou passiva
- MODERE emojis. Maximo 1-2 por mensagem

### SOBRE FORMATO
- JAMAIS use Markdown, asteriscos, hifens, bullet points ou qualquer formatacao especial
- NUNCA envie o link de compra mais de uma vez por produto
- SEMPRE faca uma pergunta por vez
- Mensagens curtas. Nada de textao. Ritmo de WhatsApp real
- NUNCA mencione Kiwify ou Assiny. Envie o link sem citar o nome da plataforma

### SOBRE PROCESSO
- NAO desvie o assunto
- NAO faca investigacao longa sobre o negocio do lead
- NAO empurre produto. Entenda a duvida primeiro, resolva, depois direcione
- Se o lead perguntar sobre algo que nao e produto da Differs, diga: "Isso foge um pouco do que a gente trabalha aqui, mas qualquer coisa sobre nossos produtos, to aqui!"

---

## 6. GUIA DE CENARIOS

### Lead indeciso entre produtos
"Me conta um pouco do que tu precisa resolver hoje. Edicao de video? Conteudo pra redes? Ou quer um pacote completo? Assim eu te indico o que faz mais sentido pra tua realidade"

### Lead acha caro
"Entendo total. Mas pensa assim: o retorno que isso traz pro teu conteudo e pro teu posicionamento paga o investimento rapidinho. E o acesso e por bastante tempo, entao tu aproveita no teu ritmo"

### Lead sumiu e voltou
"Eee voltou! 😄 Fico feliz. Me conta, o que te travou da ultima vez? Bora resolver isso de vez"

### Lead com duvida tecnica (ja e aluno)
"Pra essa parte mais tecnica, o time de suporte vai te resolver na hora! Chama eles aqui: https://api.whatsapp.com/send/?phone=5511944892979"

### Lead quer mentoria/consultoria ou nao sabe qual produto escolher
"Pra gente te indicar o caminho ideal, preenche esse formulario rapidinho: https://acessosdreamsdigitalgmailcom.yayforms.link/6KeRkeG. Nosso time analisa teu perfil e te direciona pro que faz mais sentido 😄"

### Lead pagou e nao recebeu acesso
"Fica tranquilo que a gente resolve isso agora. Me manda o e-mail que tu usou na compra? Vou acionar o time interno e eles liberam rapidinho. So aguarda um pouquinho que ja te dao retorno 👊"

---

## 7. TOOLS DISPONIVEIS

- consultar_produto: use pra buscar informacoes detalhadas sobre qualquer produto quando o lead fizer perguntas especificas
- enviar_checkout: use pra enviar o link de compra quando o lead estiver pronto
"""

# ═══════════════════════════════════════════════════════════════
# PRODUCT FAQ — Embedded knowledge base
# ═══════════════════════════════════════════════════════════════

PRODUCT_FAQ = {
    "capcut_wow": {
        "nome": "CapCut Wow",
        "promessa": "Dominar o CapCut em menos de 2 horas, criando vídeos profissionais que retêm atenção, aumentam visualizações e desflopam o perfil.",
        "metodo": "Aulas 100% práticas sobre CapCut: correção de erros de fala, melhoria de imagem (cores/luz), efeitos e transições, trilhas sonoras, retoque de pele, estabilização e legendagem com identidade própria.",
        "bonus": "Aula de Aesthetic, tipografias exclusivas, efeitos sonoros, aula de Storytelling com Felipe Oliver, e-book completo.",
        "acesso": "12 meses.",
        "preco": "De R$297 por R$79 à vista ou 3x de R$28,19.",
        "checkout_kiwify": "https://pay.kiwify.com.br/hG9akjD?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "checkout_assiny": "https://pay.assiny.com.br/95cc10/node/NZVY1A?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "pagina_vendas": "www.capcutwow.com.br/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "para_quem": "Quem quer aprender a editar vídeos profissionais no CapCut do zero, em menos de 2 horas.",
    },
    "conteudo_wow": {
        "nome": "Conteúdo Wow",
        "promessa": "Tirar o perfil do anonimato e se tornar referência no nicho, criando Conteúdos WOW com apenas 1h por semana — sem crise de criatividade, sem depender de tendências.",
        "metodo": "Método FLOW com 4 pilares: Fundamento e Identidade (Eu Nicho), Linguagem (tom de voz), Organização (clareza e fluxo), WOW Factor (experiência visual e impacto).",
        "ias": "Differson (assistente criativo 24h treinado no método da Keth) e Mila (especialista em roteiros).",
        "bonus": "Mapa de Formatos WOW, Notion de Planejamento, 30 Ganchos validados, Differ Club (tendências diárias).",
        "preco": "De R$2.249 por R$297 à vista ou 12x de R$30.",
        "checkout_kiwify": "https://pay.kiwify.com.br/0EaMPkn?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "checkout_assiny": "https://pay.assiny.com.br/_RxDIO/node/4rfqqH?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "pagina_vendas": "https://diferentedosiguais.com.br/conteudo-wow-new/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "para_quem": "Quem já edita mas não sabe o que postar, quando postar, ou como transformar edição em conteúdo estratégico.",
        "prova_social": "Mais de 2.500 profissionais e produtoras já passaram pelo método. Mais de 2 milhões de visualizações geradas.",
    },
    "feed_wow": {
        "nome": "Feed Wow",
        "promessa": "Construir um feed WOW em menos de 2 horas — encontrar um visual diferente dos iguais que transmite autoridade, aumenta percepção de valor e transforma seguidores em clientes.",
        "entregaveis": "Aesthetic única, tipografias/cores/filtros, criação de capas na prática, encontrar seu tempero WOW.",
        "bonus": "Pack Pinterest de referências, aula de Narrativas com Felipe Oliver, 130+ elementos PNG, 4 presets Lightroom.",
        "preco": "De R$397 por R$97 à vista ou 2x de R$50.",
        "checkout_kiwify": "https://pay.kiwify.com.br/XyZ987?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "pagina_vendas": "www.capcutwow.com.br/feedwow?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "para_quem": "Quem precisa de identidade visual consistente no feed — cores, capas, tipografias — e quer autoridade visual.",
    },
    "formacao_ddi": {
        "nome": "Formação Diferente dos Iguais",
        "promessa": "Levar você de criador de conteúdo a um negócio digital com marca forte e rentável, combinando método, comunidade, networking e IAs.",
        "entregaveis": "Aulas gravadas (5 fases), comunidade Discord+WhatsApp, banco de referências, mentorias em grupo trimestrais com Elisa e Felipe, aulas mensais com Keth.",
        "time": "Ketherin Kaffka (fundadora), Elisa Armour (ex-Facebook), Felipe Oliver (CMO/copywriter).",
        "preco": "R$ 2.997 à vista ou 12x de R$ 310,27 (1 ano de acesso).",
        "checkout_assiny": "https://pay.assiny.com.br/309b8e/node/rZ96V8?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "pagina_vendas": "https://diferentedosiguais.com.br/im-pl4/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "para_quem": "Quem já produz conteúdo, quer negócio estruturado, demonstrando maturidade e capacidade de investimento.",
    },
    "manual_ddi": {
        "nome": "Manual Diferente dos Iguais (Kit DDI)",
        "promessa": "Construir uma marca pessoal icônica — kit virtual com todas as ferramentas para criar uma marca pessoal única, icônica e impossível de ser ignorada.",
        "metodo": "4 etapas: mergulhar no universo pessoal, criar posicionamento autêntico, criar conexões genuínas, insights para impulsionar resultados.",
        "entregaveis": "Manual PDF, 2 aulas gravadas com Keth, template Canva, moodboard, templates Valores/Visão/Objetivos/Golden Circle.",
        "bonus": "Masterclass Ousadamente, aula Criando Marca com ChatGPT, aula Aesthetic, Cronograma Creator do Futuro (Trello), voucher R$200.",
        "preco": "De R$697 por R$497 à vista ou 12x de R$49,90.",
        "checkout_assiny": "https://pay.assiny.com.br/manual-ddi-checkout?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "pagina_vendas": "https://diferentedosiguais.com.br/kit-ddi/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "para_quem": "Quem precisa de posicionamento e marca pessoal mas não está pronto para o investimento da Formação DDI.",
    },
    "mpi": {
        "nome": "Meu Primeiro Infoproduto",
        "promessa": "Em 7 dias você terá seu primeiro infoproduto no ar — escolher ideia, criar produto, montar oferta, publicar e fazer a primeira venda.",
        "metodo": "Checklist diário de 7 dias, aulas curtas e práticas, IA que cria infoprodutos (módulos, oferta, copies), estratégia para primeira venda.",
        "bonus": "Estruturas de copies prontas, aula 15 tendências 2026 com Keth, aula Como Escalar da 1ª Venda a R$100k/mês.",
        "preco": "R$49 à vista ou 12x de R$5,07.",
        "checkout_assiny": "https://pay.assiny.com.br/381b15/node/ggKPBc?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "pagina_vendas": "https://diferentedosiguais.com.br/mpi/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "para_quem": "Quem quer monetizar conhecimento — transformar uma ideia em infoproduto, sem precisar de audiência ou experiência prévia.",
        "criadores": "Elisa Armour, Felipe Oliver e Ketherin Kaffka — +100 mil vendas online, +R$7 milhões em 2025.",
    },
    "combo_wow": {
        "nome": "Combo Wow (5x1)",
        "promessa": "5 treinamentos num lugar só para sair do caos de criar conteúdo e transformar o Instagram em canal de vendas real.",
        "entregaveis": "CapCut Wow + Conteúdo Wow + Feed Wow + Meu Primeiro Infoproduto + Bônus Exclusivos.",
        "preco": "De R$997 por R$197 à vista. 6 meses de acesso.",
        "checkout_assiny": "https://pay.assiny.com.br/bc535b/node/qJ6BW5?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "pagina_vendas": "https://diferentedosiguais.com.br/combowow-a1/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "para_quem": "Quem quer o pacote completo: edição + conteúdo + feed + infoproduto, com melhor custo-benefício.",
    },
    "diagnostico": {
        "nome": "Diagnóstico Estratégico",
        "promessa": "Análise individual do perfil, organização de prioridades e entrega de plano prático de implementação com call individual.",
        "entregaveis": "Análise completa do perfil, plano de implementação personalizado, call individual de 1h.",
        "preco": "R$ 3.000 (com Elisa ou Felipe) ou R$ 5.000 (com Keth).",
        "para_quem": "Quem já atua no digital, tem situação específica e precisa de direcionamento individual — não um curso genérico.",
    },
    "kasulo": {
        "nome": "Mentoria Kasulo",
        "promessa": "Transformar sua marca pessoal ou jurídica em 6 meses com acompanhamento estratégico personalizado dos 3 sócios.",
        "pilares": "Posicionamento, marca forte, estratégia de conteúdo, alavancagem do negócio no digital.",
        "entregaveis": "Onboarding individual, mentorias com Keth/Elisa/Felipe, grupo WhatsApp 6 meses, hotseats quinzenais, IAs exclusivas (Mila, Differson, Edy, Ana Lise, Cora), todos os cursos DDI, CS dedicado.",
        "preco": "R$ 15.500 à vista ou 12x de R$ 1.551,35 (44% off sobre R$ 27.473 dos entregáveis separados).",
        "para_quem": "Quem já executa, quer acelerar com acompanhamento próximo e tem desafios amplos de negócio.",
    },
}

# ═══════════════════════════════════════════════════════════════
# CHECKOUT LINKS — ordered by priority
# ═══════════════════════════════════════════════════════════════

CHECKOUT_LINKS = {
    "capcut_wow": {
        "kiwify": "https://pay.kiwify.com.br/hG9akjD?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "assiny": "https://pay.assiny.com.br/95cc10/node/NZVY1A?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "pagina": "www.capcutwow.com.br/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
    },
    "conteudo_wow": {
        "kiwify": "https://pay.kiwify.com.br/0EaMPkn?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "assiny": "https://pay.assiny.com.br/_RxDIO/node/4rfqqH?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "pagina": "https://diferentedosiguais.com.br/conteudo-wow-new/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
    },
    "feed_wow": {
        "kiwify": "https://pay.kiwify.com.br/XyZ987?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "pagina": "www.capcutwow.com.br/feedwow?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
    },
    "formacao_ddi": {
        "assiny": "https://pay.assiny.com.br/309b8e/node/rZ96V8?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "pagina": "https://diferentedosiguais.com.br/im-pl4/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
    },
    "manual_ddi": {
        "assiny": "https://pay.assiny.com.br/manual-ddi-checkout?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "pagina": "https://diferentedosiguais.com.br/kit-ddi/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
    },
    "mpi": {
        "assiny": "https://pay.assiny.com.br/381b15/node/ggKPBc?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "pagina": "https://diferentedosiguais.com.br/mpi/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
    },
    "combo_wow": {
        "assiny": "https://pay.assiny.com.br/bc535b/node/qJ6BW5?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
        "pagina": "https://diferentedosiguais.com.br/combowow-a1/?utm_source=recuperacaowpp&utm_medium=recuperacaowpp",
    },
}

# Links diretos
FORMULARIO_DDI = "https://acessosdreamsdigitalgmailcom.yayforms.link/6KeRkeG"
SUPORTE_ALUNOS = "https://api.whatsapp.com/send/?phone=5511944892979"
