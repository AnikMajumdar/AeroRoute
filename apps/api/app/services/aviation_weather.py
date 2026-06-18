from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# AviationWeather.gov integration is disabled in this build (no external API calls).
INTEGRATION_DISABLED_MESSAGE = (
    "AviationWeather.gov integration is not connected. "
    "Verify METAR, TAF, PIREPs, SIGMETs, and AIRMETs through official briefings "
    "(1800WXBRIEF, ForeFlight/Garmin)."
)


class AviationWeatherClient:
    """Stub client — METAR/TAF fetching disabled."""

    async def get_metar(self, icao: str) -> dict[str, Any] | None:
        if not icao:
            return None
        logger.debug("Aviation weather METAR disabled for %s", icao)
        return None

    async def get_taf(self, icao: str) -> dict[str, Any] | None:
        if not icao:
            return None
        logger.debug("Aviation weather TAF disabled for %s", icao)
        return None


aviation_weather_client = AviationWeatherClient()
