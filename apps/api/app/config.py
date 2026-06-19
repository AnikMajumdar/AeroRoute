from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
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
    clerk_issuer: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    copilot_enabled: bool = False
    api_cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"
    app_env: str = "development"

    # Reserved for future FAA / aviation weather integrations (currently disabled in code)
    aviation_weather_enabled: bool = False
    faa_integrations_enabled: bool = False
    aviation_weather_api_base_url: str = ""
    faa_nas_status_url: str = ""

    # NOTAM provider (disabled)
    notam_provider_mode: str = "disabled"
    faa_nms_api_base_url: str = ""
    faa_nms_api_key: str = ""
    faa_nms_client_id: str = ""
    faa_nms_client_secret: str = ""

    # Cache TTLs (seconds)
    cache_metar_ttl: int = 300
    cache_taf_ttl: int = 900
    cache_wind_ttl: int = 1800
    cache_nas_status_ttl: int = 300
    cache_tfr_ttl: int = 300
    cache_notam_ttl: int = 600
    cache_sigmet_ttl: int = 600
    cache_pirep_ttl: int = 600
    cache_diversion_ttl: int = 1800
    async_route_calc: bool = False
    route_calc_timeout_sec: float = 15.0

    @field_validator("copilot_enabled", mode="before")
    @classmethod
    def parse_copilot_enabled(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in ("production", "prod")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


settings = Settings()
