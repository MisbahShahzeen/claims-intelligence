from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    kafka_bootstrap_servers: str = "localhost:9092"
    consumer_group: str = "ingestion-worker"
    idle_timeout_ms: int = 3000


@lru_cache
def get_settings() -> Settings:
    return Settings()
