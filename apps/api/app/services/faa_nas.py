from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from app.planning_constraints import FORECAST_HORIZON_DAYS
from app.services.cache import cache_service
from app.services.faa_nas_parser import parse_faa_airport_status

logger = logging.getLogger(__name__)

NAS_STATUS_URL = "https://nasstatus.faa.gov/api/airport-status-information"


class FAANasStatusClient:
    def __init__(self) -> None:
        self.timeout = httpx.Timeout(10.0, connect=5.0)

    async def get_airport_status(self, icao: str, supabase: Any | None = None) -> dict[str, Any]:
        if not icao:
            return parse_faa_airport_status("", None).to_dict()
        icao = icao.upper()
        cache_key = f"nas_status:{icao}"
        cached = cache_service.get(cache_key)
        if cached is not None:
            return cached

        default = parse_faa_airport_status(icao, None).to_dict()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(NAS_STATUS_URL, params={"airportCode": icao})
                if response.status_code == 404:
                    parsed = parse_faa_airport_status(icao, {})
                    result = parsed.to_dict()
                    cache_service.set(cache_key, result, settings.cache_nas_status_ttl)
                    return result
                response.raise_for_status()
                text = response.text.strip()
                if not text:
                    raise ValueError("empty FAA NAS response body")
                data = response.json()
                parsed = parse_faa_airport_status(icao, data if isinstance(data, dict) else {})
                result = parsed.to_dict()
                if supabase is not None:
                    try:
                        supabase.table("airport_status_snapshots").insert(
                            {
                                "icao": icao,
                                "status": parsed.status,
                                "delay_minutes": parsed.delay_minutes,
                                "is_closed": parsed.is_closed,
                                "ground_stop": parsed.ground_stop,
                                "raw_payload": parsed.raw_payload,
                                "parsed_payload": result,
                                "fetched_at": parsed.fetched_at,
                            }
                        ).execute()
                    except Exception as exc:
                        logger.debug("Could not persist FAA snapshot: %s", exc)
                cache_service.set(cache_key, result, settings.cache_nas_status_ttl)
                return result
        except httpx.TimeoutException:
            logger.warning("FAA NAS status request timed out for %s", icao)
            result = parse_faa_airport_status(icao, None).to_dict()
            result["warnings"] = [f"{icao}: Status unavailable (timeout)"]
            return result
        except Exception as exc:
            logger.warning("FAA NAS status fetch failed for %s: %s", icao, exc)
            result = parse_faa_airport_status(icao, None).to_dict()
            result["warnings"] = [f"{icao}: Status unavailable"]
            return result


faa_nas_client = FAANasStatusClient()
