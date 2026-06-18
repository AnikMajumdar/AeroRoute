from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from app.services.cache import cache_service

logger = logging.getLogger(__name__)

AVIATION_WEATHER_BASE = "https://aviationweather.gov/api/data"


class AviationWeatherClient:
    def __init__(self) -> None:
        self.timeout = httpx.Timeout(10.0, connect=5.0)

    async def get_metar(self, icao: str) -> dict[str, Any] | None:
        if not icao:
            return None
        icao = icao.upper()
        cache_key = f"metar:{icao}"
        cached = cache_service.get(cache_key)
        if cached is not None:
            return cached

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{AVIATION_WEATHER_BASE}/metar",
                    params={"ids": icao, "format": "json"},
                )
                response.raise_for_status()
                data = response.json()
                if not data:
                    return None
                metar = data[0] if isinstance(data, list) else data
                raw_category = metar.get("fltcat") or metar.get("flightCategory")
                category = None
                if raw_category is not None:
                    category = str(raw_category).strip().upper() or None
                result = {
                    "icao": icao,
                    "raw": metar.get("rawOb") or metar.get("raw_text"),
                    "temp_c": metar.get("temp"),
                    "wind_dir": metar.get("wdir"),
                    "wind_speed_kt": metar.get("wspd"),
                    "visibility": metar.get("visib"),
                    "flight_category": category,
                    "obs_time": metar.get("obsTime") or metar.get("observation_time"),
                }
                cache_service.set(cache_key, result, settings.cache_metar_ttl)
                return result
        except httpx.TimeoutException:
            logger.warning("METAR request timed out for %s", icao)
            return None
        except Exception as exc:
            logger.warning("METAR fetch failed for %s: %s", icao, exc)
            return None

    async def get_taf(self, icao: str) -> dict[str, Any] | None:
        if not icao:
            return None
        icao = icao.upper()
        cache_key = f"taf:{icao}"
        cached = cache_service.get(cache_key)
        if cached is not None:
            return cached

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{AVIATION_WEATHER_BASE}/taf",
                    params={"ids": icao, "format": "json"},
                )
                response.raise_for_status()
                data = response.json()
                if not data:
                    return None
                taf = data[0] if isinstance(data, list) else data
                result = {
                    "icao": icao,
                    "raw": taf.get("rawTAF") or taf.get("raw_text"),
                    "issue_time": taf.get("issueTime") or taf.get("issue_time"),
                    "valid_from": taf.get("validTimeFrom"),
                    "valid_to": taf.get("validTimeTo"),
                }
                cache_service.set(cache_key, result, settings.cache_taf_ttl)
                return result
        except httpx.TimeoutException:
            logger.warning("TAF request timed out for %s", icao)
            return None
        except Exception as exc:
            logger.warning("TAF fetch failed for %s: %s", icao, exc)
            return None


aviation_weather_client = AviationWeatherClient()
