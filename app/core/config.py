from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    app_name: str = "Arcscrow API"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite+aiosqlite:///./arcscrow.db"
    redis_url: str = "redis://localhost:6379/0"
    session_secret: str = "development-only-session-secret-change-me"
    frontend_url: str = "http://localhost:5173"
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    cookie_secure: bool = False
    ai_provider: str = "development"
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    circle_api_key: str = ""
    circle_entity_secret: str = ""
    circle_wallet_set_id: str = ""
    arc_chain_id: int = 5_042_002
    arc_rpc_url: str = "https://rpc.testnet.arc.network"
    arc_ws_url: str = "wss://rpc.testnet.arc.network"
    arc_explorer_url: str = "https://testnet.arcscan.app"
    arc_usdc_address: str = "0x3600000000000000000000000000000000000000"
    arcscrow_escrow_address: str = ""
    metrics_enabled: bool = True

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
