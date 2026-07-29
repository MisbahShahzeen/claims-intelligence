from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "claims-api"
    environment: str = "local"
    database_url: str

    cors_origins: list[str] = ["http://localhost:4200"]
    storage_root: str = "../../storage/documents"
    max_upload_bytes: int = 10 * 1024 * 1024

    kafka_bootstrap_servers: str = "localhost:9092"

    login_rate_limit: int = 10
    login_rate_window_seconds: int = 300

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
