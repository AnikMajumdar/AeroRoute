from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Always load .env from apps/api/, even if the command is run from repo root
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    clerk_secret_key: str = ""
    clerk_jwks_url: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    copilot_enabled: bool = False
    api_cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"

    # Cache TTLs (seconds)
    cache_metar_ttl: int = 300
    cache_taf_ttl: int = 900
    cache_wind_ttl: int = 1800
    cache_nas_status_ttl: int = 300
    cache_diversion_ttl: int = 1800
    async_route_calc: bool = False

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


settings = Settings()
