from __future__ import annotations

import base64
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always load .env from apps/api/, even if the command is run from repo root
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def clerk_frontend_api_host(publishable_key: str) -> str | None:
    """Decode the Frontend API host that Clerk embeds in a publishable key (pk_test_/pk_live_ + base64(host$))."""
    parts = publishable_key.strip().split("_", 2)
    if len(parts) != 3 or parts[0] != "pk":
        return None
    encoded = parts[2].replace("-", "+").replace("_", "/")
    try:
        host = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8").rstrip("$").strip()
    except (ValueError, UnicodeDecodeError):
        return None
    return host or None


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
    # Same value as the web app's NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY; lets the API derive the JWKS URL.
    clerk_publishable_key: str = Field(
        default="",
        validation_alias=AliasChoices("clerk_publishable_key", "next_public_clerk_publishable_key"),
    )
    # Local-development shortcut: trust the X-User-Id header. Never honoured in production or when JWKS is configured.
    allow_dev_auth_header: bool = False
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

    @field_validator("copilot_enabled", "allow_dev_auth_header", mode="before")
    @classmethod
    def parse_bool_flag(cls, value: object) -> bool:
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

    @property
    def effective_clerk_jwks_url(self) -> str:
        """Explicit CLERK_JWKS_URL, else the URL derived from the Clerk publishable key (empty if neither)."""
        explicit = self.clerk_jwks_url.strip()
        if explicit:
            return explicit
        host = clerk_frontend_api_host(self.clerk_publishable_key)
        return f"https://{host}/.well-known/jwks.json" if host else ""


settings = Settings()
