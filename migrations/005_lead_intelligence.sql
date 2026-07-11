-- 005_lead_intelligence.sql
-- Lead intelligence layer — AI-powered profiling for journey + Júlia agent.
-- Stores classification, pain points, ambitions, and conversation summaries.

CREATE TABLE IF NOT EXISTS lead_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone TEXT UNIQUE NOT NULL,

    -- Classification
    temperatura TEXT DEFAULT 'frio',          -- quente, morno, frio
    ticket TEXT DEFAULT 'low',                -- high, low, unknown
    estagio TEXT,                             -- consciencia, consideracao, decisao, cliente

    -- Signals
    produtos_interesse TEXT[] DEFAULT '{}',    -- products lead showed interest in
    dores TEXT[] DEFAULT '{}',                 -- pain points extracted from conversation
    ambicoes TEXT[] DEFAULT '{}',              -- goals/aspirations
    objecoes TEXT[] DEFAULT '{}',              -- objections raised

    -- Summary
    resumo_conversa TEXT,                      -- latest AI-generated conversation summary
    perfil TEXT,                               -- lead persona description

    -- Metrics (auto-updated by trigger or analyzer)
    total_compras INTEGER DEFAULT 0,
    total_gasto_cents INTEGER DEFAULT 0,
    total_mensagens_recebidas INTEGER DEFAULT 0,
    total_mensagens_enviadas INTEGER DEFAULT 0,
    ultima_analise TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lead_insights_phone ON lead_insights(phone);
CREATE INDEX IF NOT EXISTS idx_lead_insights_temp ON lead_insights(temperatura);
CREATE INDEX IF NOT EXISTS idx_lead_insights_ticket ON lead_insights(ticket);
