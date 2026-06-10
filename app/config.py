from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Meta WhatsApp Cloud API
    meta_phone_number_id: str
    meta_access_token: str
    meta_api_version: str = "v19.0"
    # WhatsApp Business Account id — needed for cost (pricing_analytics) sync.
    # Found in WhatsApp Manager → Configurações da conta. Cost sync is skipped
    # while this is empty.
    meta_waba_id: str = ""

    # Supabase
    supabase_url: str
    supabase_key: str

    # Background scheduler poll interval (seconds)
    scheduler_interval_seconds: int = 30
    # How many due messages a single claim grabs per cycle
    scheduler_batch_size: int = 50

    # Retry policy for transient send failures (5xx / timeouts / 429)
    message_max_attempts: int = 3
    message_retry_base_minutes: int = 5  # backoff = base * 2**(attempt-1)

    # Cost sync (Meta pricing_analytics) interval — daily by default
    cost_sync_interval_seconds: int = 86_400
    cost_sync_lookback_days: int = 7
    # USD→BRL rate used only to show the real (USD) Meta cost alongside the
    # BRL revenue in the dashboard. Adjustable; not used for billing.
    usd_brl_rate: float = 5.40

    # Webhook signature verification (opt-in — enforced only when set).
    # Leave empty to keep accepting all webhooks (current behaviour).
    kiwify_webhook_token: str = ""
    assiny_webhook_token: str = ""


settings = Settings()
