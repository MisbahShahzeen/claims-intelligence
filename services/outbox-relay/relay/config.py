from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    kafka_bootstrap_servers: str = "localhost:9092"
    poll_interval_seconds: float = 1.0
    batch_size: int = 100
    max_attempts: int = 5
    metrics_port: int = 9101


@lru_cache
def get_settings() -> Settings:
    return Settings()
