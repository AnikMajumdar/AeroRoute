from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.aviation_weather import INTEGRATION_DISABLED_MESSAGE
from app.services.live_data.types import DataSourceMeta, ProviderResult

SOURCE_NAME = "AviationWeather.gov (disabled)"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _disabled_meta(endpoint: str) -> DataSourceMeta:
    return DataSourceMeta(
        source_name=SOURCE_NAME,
        source_url=None,
        fetched_at=_now_iso(),
        available=False,
        error=INTEGRATION_DISABLED_MESSAGE,
    )


class AviationWeatherProvider:
    """Stub — no AviationWeather.gov API calls."""

    async def get_metar(self, icao: str) -> ProviderResult:
        return ProviderResult(data=None, meta=_disabled_meta("metar"))

    async def get_taf(self, icao: str) -> ProviderResult:
        return ProviderResult(data=None, meta=_disabled_meta("taf"))

    async def get_route_hazards(
        self,
        route_path: list[dict[str, float]] | list[tuple[float, float]],
        bbox: tuple[float, float, float, float] | None = None,
    ) -> ProviderResult:
        return ProviderResult(data=[], meta=_disabled_meta("hazards"))


aviation_weather_provider = AviationWeatherProvider()
