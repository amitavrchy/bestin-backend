from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'postgresql+psycopg://bestin:bestin@localhost:5432/bestin'
    db_fallback_sqlite: bool = True
    storage_dir: str = 'data/storage'
    max_upload_mb: int = 50
    jwt_secret: str = 'change-this-development-secret'
    jwt_expire_minutes: int = 1440
    admin_email: str = 'admin@bestin.local'
    admin_password: str = 'admin12345'
    ai_url: str = 'http://localhost:8001'
    ai_internal_token: str = 'dev-internal-token'
    ai_timeout: float = 30
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    status_poll_seconds: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
