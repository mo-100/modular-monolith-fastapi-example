from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration.

    One database DSN is used because this is a single deployable. Each module
    still owns its schema and would receive its own DSN/credentials when
    extracted into a service.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:55432/modular_monolith"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
