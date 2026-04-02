-- =============================================================
-- Sales Recovery System — Initial Schema
-- =============================================================

-- contacts: one record per unique phone number
CREATE TABLE IF NOT EXISTS contacts (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    phone       TEXT        UNIQUE NOT NULL,
    full_name   TEXT,
    email       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- recovery_sessions: one per recovery attempt
-- status flow: active → converted | exhausted | cancelled
CREATE TABLE IF NOT EXISTS recovery_sessions (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id           UUID        NOT NULL REFERENCES contacts(id),
    platform             TEXT        NOT NULL CHECK (platform IN ('kiwify', 'assiny')),
    platform_order_id    TEXT,
    platform_event_type  TEXT        NOT NULL,
    trigger_event        TEXT        NOT NULL CHECK (trigger_event IN ('abandoned_cart', 'waiting_payment', 'payment_refused')),
    product_id           TEXT        NOT NULL,
    product_name         TEXT        NOT NULL,
    template_prefix      TEXT        NOT NULL,   -- e.g. rec_combo_wow
    amount_cents         INTEGER,
    status               TEXT        NOT NULL DEFAULT 'active'
                                     CHECK (status IN ('active', 'converted', 'exhausted', 'cancelled')),
    messages_sent        INTEGER     NOT NULL DEFAULT 0,
    converted_at         TIMESTAMPTZ,
    converted_order_id   TEXT,
    raw_payload          JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- scheduled_messages: message queue — one row per message per session
-- status flow: pending → sent | failed | cancelled
CREATE TABLE IF NOT EXISTS scheduled_messages (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    recovery_session_id  UUID        NOT NULL REFERENCES recovery_sessions(id),
    contact_id           UUID        NOT NULL REFERENCES contacts(id),
    message_number       INTEGER     NOT NULL CHECK (message_number IN (1, 2, 3)),
    template_name        TEXT        NOT NULL,   -- e.g. rec_combo_wow1
    phone                TEXT        NOT NULL,
    scheduled_for        TIMESTAMPTZ NOT NULL,
    status               TEXT        NOT NULL DEFAULT 'pending'
                                     CHECK (status IN ('pending', 'sent', 'failed', 'cancelled')),
    sent_at              TIMESTAMPTZ,
    whatsapp_message_id  TEXT,
    error_message        TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================
-- Indexes
-- =============================================================

-- Dedup check: is there an active session for this contact + template?
CREATE INDEX IF NOT EXISTS idx_recovery_sessions_active_dedup
    ON recovery_sessions(contact_id, template_prefix)
    WHERE status = 'active';

-- Lookup sessions by platform order id (for purchase approval matching)
CREATE INDEX IF NOT EXISTS idx_recovery_sessions_platform_order
    ON recovery_sessions(platform, platform_order_id);

-- Scheduler polling: find pending messages that are due
CREATE INDEX IF NOT EXISTS idx_scheduled_messages_due
    ON scheduled_messages(scheduled_for)
    WHERE status = 'pending';

-- Cancel pending messages when session closes
CREATE INDEX IF NOT EXISTS idx_scheduled_messages_session
    ON scheduled_messages(recovery_session_id)
    WHERE status = 'pending';

-- Phone lookup for purchase approval
CREATE INDEX IF NOT EXISTS idx_contacts_phone
    ON contacts(phone);
