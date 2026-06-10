-- =============================================================
-- 002 — Meta cost sync + atomic message claim + retry support
-- =============================================================

-- ── #1 Cost reconciliation: daily snapshot from Meta pricing_analytics ──
-- One row per (day, pricing_category, pricing_type). Upserted on each sync.
CREATE TABLE IF NOT EXISTS meta_cost_daily (
    day               DATE        NOT NULL,
    pricing_category  TEXT        NOT NULL DEFAULT 'UNKNOWN',
    pricing_type      TEXT        NOT NULL DEFAULT 'UNKNOWN',
    currency          TEXT,
    cost              NUMERIC(12, 4) NOT NULL DEFAULT 0,  -- valor cobrado pela Meta (USD)
    volume            INTEGER     NOT NULL DEFAULT 0,     -- nº de mensagens/conversas cobradas
    raw               JSONB,
    fetched_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (day, pricing_category, pricing_type)
);

CREATE INDEX IF NOT EXISTS idx_meta_cost_daily_day ON meta_cost_daily(day);

-- ── #3 / #5 Atomic claim + retry columns on scheduled_messages ──
ALTER TABLE scheduled_messages
    ADD COLUMN IF NOT EXISTS attempts   INTEGER     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;

-- Allow the transient 'processing' state used while a worker holds the row.
ALTER TABLE scheduled_messages DROP CONSTRAINT IF EXISTS scheduled_messages_status_check;
ALTER TABLE scheduled_messages
    ADD CONSTRAINT scheduled_messages_status_check
    CHECK (status IN ('pending', 'processing', 'sent', 'failed', 'cancelled'));

-- ── #3 Atomic claim function ──
-- Claims up to p_limit due messages for a single worker, flipping them to
-- 'processing' under FOR UPDATE SKIP LOCKED so concurrent scheduler replicas
-- never grab the same row (no double-send). Also reclaims rows stuck in
-- 'processing' for longer than p_stale_minutes (worker crashed mid-send).
CREATE OR REPLACE FUNCTION claim_due_messages(
    p_limit         INTEGER DEFAULT 50,
    p_stale_minutes INTEGER DEFAULT 5
)
RETURNS SETOF scheduled_messages
LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    UPDATE scheduled_messages sm
    SET status     = 'processing',
        claimed_at = NOW()
    WHERE sm.id IN (
        SELECT id
        FROM scheduled_messages
        WHERE (status = 'pending'    AND scheduled_for <= NOW())
           OR (status = 'processing' AND claimed_at < NOW() - make_interval(mins => p_stale_minutes))
        ORDER BY scheduled_for
        FOR UPDATE SKIP LOCKED
        LIMIT p_limit
    )
    RETURNING sm.*;
END;
$$;
