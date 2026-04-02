from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Meta WhatsApp Cloud API
    meta_phone_number_id: str
    meta_access_token: str
    meta_api_version: str = "v19.0"

    # Supabase
    supabase_url: str
    supabase_key: str

    # Background scheduler poll interval (seconds)
    scheduler_interval_seconds: int = 30


settings = Settings()
