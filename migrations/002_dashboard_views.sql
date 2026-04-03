-- =============================================================
-- Dashboard Views
-- =============================================================

-- Main view: joins contacts + sessions for dashboard queries
-- Enables filtering by email, phone, name alongside session data
CREATE OR REPLACE VIEW v_recovery_overview AS
SELECT
    rs.id,
    rs.created_at,
    rs.updated_at,
    rs.platform,
    rs.trigger_event,
    rs.platform_event_type,
    rs.product_name,
    rs.template_prefix,
    rs.status,
    rs.messages_sent,
    rs.amount_cents,
    rs.converted_at,
    rs.converted_order_id,
    c.id   AS contact_id,
    c.phone,
    c.full_name,
    c.email
FROM recovery_sessions rs
JOIN contacts c ON c.id = rs.contact_id;
