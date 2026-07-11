-- 004_journey.sql
-- Jornada completa Ana | CapCut Wow — state machine para 37 templates
-- Substitui o modelo linear de 3 msgs por jornada dinâmica com estados e tags.

-- ============================================================
-- Tabela: contact_journeys
-- Uma entrada por contato. Reutilizada entre jornadas (atualizada
-- a cada nova compra). Estado atual define qual template disparar.
-- ============================================================
CREATE TABLE IF NOT EXISTS contact_journeys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID REFERENCES contacts(id) ON DELETE CASCADE,
    phone TEXT NOT NULL,
    full_name TEXT NOT NULL,                          -- para variável {{1}} nos templates

    -- Estado atual da máquina de estados
    current_state TEXT NOT NULL DEFAULT 'ativacao',   -- ativacao, engajada, acel_feed, fria, suporte, etc.
    current_stage TEXT,                               -- bloco: ativacao, engajada, acelerada, fria, followup

    -- Tags acumuladas (produtos comprados, flags comportamentais)
    tags TEXT[] DEFAULT '{}',                         -- ex: {capcut_wow, ativo, feed_interesse}

    -- Produtos comprados (acumulativo: cada compra adiciona)
    purchased_products TEXT[] DEFAULT '{}',           -- ex: {capcut_wow, conteudo_wow}

    -- Dia na jornada do produto de entrada (D+1, D+5, etc.)
    day_offset INTEGER DEFAULT 0,

    -- Produto que originou a jornada atual
    entry_product TEXT NOT NULL,
    entry_platform TEXT,                              -- kiwify | assiny
    entry_order_id TEXT,
    amount_cents INTEGER,

    -- Último template enviado (para evitar duplicidade)
    last_template TEXT,
    last_message_sent_at TIMESTAMPTZ,

    -- Última interação do aluno (resposta ou clique)
    last_response_at TIMESTAMPTZ,
    last_response_text TEXT,                          -- texto da última resposta aberta
    last_response_button TEXT,                        -- texto do último botão clicado

    -- Controle
    messages_sent INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',                     -- active, completed, opted_out, suporte
    completed_reason TEXT,                            -- 'comprou_{product}', 'opt_out', 'd120_exhausted'

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_journeys_phone ON contact_journeys(phone);
CREATE INDEX IF NOT EXISTS idx_journeys_status ON contact_journeys(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_journeys_contact ON contact_journeys(contact_id);

-- ============================================================
-- Tabela: journey_messages
-- Histórico de mensagens enviadas na jornada (auditoria + debug)
-- ============================================================
CREATE TABLE IF NOT EXISTS journey_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    journey_id UUID REFERENCES contact_journeys(id) ON DELETE CASCADE,
    contact_id UUID REFERENCES contacts(id),
    phone TEXT NOT NULL,
    template_name TEXT NOT NULL,
    message_number INTEGER,                            -- ordem na jornada (1, 2, 3...)
    state_at_send TEXT,                                -- estado quando enviou
    status TEXT DEFAULT 'pending',                     -- pending, sent, failed, delivered, read
    scheduled_for TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    whatsapp_message_id TEXT,
    error_message TEXT,
    attempts INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_journey_msgs_journey ON journey_messages(journey_id);
CREATE INDEX IF NOT EXISTS idx_journey_msgs_due ON journey_messages(scheduled_for) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_journey_msgs_wa_id ON journey_messages(whatsapp_message_id) WHERE whatsapp_message_id IS NOT NULL;

-- ============================================================
-- Função: claim_due_journey_messages
-- Atômica (SKIP LOCKED) — mesma lógica da claim_due_messages
-- mas para journey_messages. Usada pelo scheduler.
-- ============================================================
CREATE OR REPLACE FUNCTION claim_due_journey_messages(
    p_limit INTEGER DEFAULT 50,
    p_stale_minutes INTEGER DEFAULT 5
) RETURNS SETOF journey_messages AS $$
BEGIN
    -- Reclaim stale processing messages
    UPDATE journey_messages
    SET status = 'pending', claimed_at = NULL
    WHERE status = 'processing'
      AND claimed_at < NOW() - (p_stale_minutes || ' minutes')::INTERVAL;

    -- Claim pending messages atomically
    RETURN QUERY
    WITH claimed AS (
        SELECT id
        FROM journey_messages
        WHERE status = 'pending'
          AND scheduled_for <= NOW()
        ORDER BY scheduled_for
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE journey_messages jm
    SET status = 'processing', claimed_at = NOW()
    FROM claimed
    WHERE jm.id = claimed.id
    RETURNING jm.*;
END;
$$ LANGUAGE plpgsql;

-- Coluna auxiliar para o claim atômico
ALTER TABLE journey_messages ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;

-- ============================================================
-- Trigger: updated_at automático
-- ============================================================
CREATE OR REPLACE FUNCTION update_journey_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_journey_updated_at ON contact_journeys;
CREATE TRIGGER trg_journey_updated_at
    BEFORE UPDATE ON contact_journeys
    FOR EACH ROW EXECUTE FUNCTION update_journey_updated_at();
