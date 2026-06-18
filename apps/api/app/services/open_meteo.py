from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.geo.utils import initial_bearing_deg
from app.planning_constraints import FORECAST_HORIZON_DAYS
from app.services.cache import cache_service
from app.services.wind_altitude import (
    cruise_altitude_to_pressure_level_hpa,
    wind_components_kt,
)

logger = logging.getLogger(__name__)

OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

# Pressure levels supported by Open-Meteo standard forecast API
AVAILABLE_LEVELS_HPA = [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200]


class OpenMeteoClient:
    def __init__(self) -> None:
        self.timeout = httpx.Timeout(15.0, connect=5.0)

    @staticmethod
    def _hour_index(times: list[str], forecast_time: datetime | None) -> int:
        if not times:
            return 0
        if forecast_time is None:
            return 0
        target = forecast_time.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        parsed = []
        for raw in times:
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                parsed.append(dt)
            except ValueError:
                parsed.append(None)
        for idx, dt in enumerate(parsed):
            if dt and dt >= target:
                return idx
        return min(len(times) - 1, 0)

    def _pressure_level_hourly_vars(self, level_hpa: int) -> str:
        return f"windspeed_{level_hpa}hPa,winddirection_{level_hpa}hPa"

    async def get_wind_at_point(
        self,
        lat: float,
        lon: float,
        cruise_altitude_ft: int = 10000,
        forecast_time: datetime | None = None,
    ) -> dict[str, Any] | None:
        level_hpa, wind_altitude_ft = cruise_altitude_to_pressure_level_hpa(cruise_altitude_ft)
        time_key = forecast_time.isoformat() if forecast_time else "now"
        cache_key = f"wind:{lat:.2f}:{lon:.2f}:{level_hpa}:{time_key[:13]}"
        cached = cache_service.get(cache_key)
        if cached is not None:
            return cached

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                hourly_vars = self._pressure_level_hourly_vars(level_hpa)
                response = await client.get(
                    OPEN_METEO_BASE,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "hourly": f"{hourly_vars},windspeed_10m,winddirection_10m",
                        "windspeed_unit": "kn",
                        "forecast_days": FORECAST_HORIZON_DAYS,
                        "timezone": "UTC",
                    },
                )
                response.raise_for_status()
                data = response.json()
                hourly = data.get("hourly", {})
                times = hourly.get("time", [])
                idx = self._hour_index(times, forecast_time)

                speed_key = f"windspeed_{level_hpa}hPa"
                dir_key = f"winddirection_{level_hpa}hPa"
                speeds = hourly.get(speed_key, [])
                directions = hourly.get(dir_key, [])

                wind_source = "pressure_level"
                if speeds and directions and idx < len(speeds) and speeds[idx] is not None:
                    speed = float(speeds[idx])
                    direction = float(directions[idx])
                else:
                    speeds_10 = hourly.get("windspeed_10m", [])
                    dirs_10 = hourly.get("winddirection_10m", [])
                    if not speeds_10 or not dirs_10:
                        return None
                    idx = min(idx, len(speeds_10) - 1, len(dirs_10) - 1)
                    speed = float(speeds_10[idx])
                    direction = float(dirs_10[idx])
                    wind_source = "surface_fallback"
                    wind_altitude_ft = 10
                    level_hpa = 0

                result = {
                    "wind_speed_kt": speed,
                    "wind_direction_deg": direction,
                    "wind_altitude_ft": wind_altitude_ft,
                    "wind_pressure_level_hpa": level_hpa if level_hpa else None,
                    "wind_source": wind_source,
                }
                cache_service.set(cache_key, result, settings.cache_wind_ttl)
                return result
        except httpx.TimeoutException:
            logger.warning("Open-Meteo wind request timed out at %s,%s", lat, lon)
            return None
        except Exception as exc:
            logger.warning("Open-Meteo wind fetch failed at %s,%s: %s", lat, lon, exc)
            return None

    @staticmethod
    def headwind_component_kt(
        wind_speed_kt: float, wind_direction_deg: float, track_bearing_deg: float
    ) -> float:
        """Positive = headwind, negative = tailwind."""
        angle_rad = math.radians(wind_direction_deg - track_bearing_deg)
        return wind_speed_kt * math.cos(angle_rad)

    async def sample_route_winds(
        self,
        waypoints: list[tuple[float, float]],
        cruise_altitude_ft: int = 10000,
        forecast_time: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """Fetch wind data for each leg; returns segments and overall wind_data_quality."""
        segments: list[dict[str, Any]] = []
        used_fallback = False
        used_pressure = False

        leg_params: list[tuple[int, float, float, float, float, float]] = []
        for i in range(len(waypoints) - 1):
            lat1, lon1 = waypoints[i]
            lat2, lon2 = waypoints[i + 1]
            mid_lat = (lat1 + lat2) / 2
            mid_lon = (lon1 + lon2) / 2
            bearing = initial_bearing_deg(lat1, lon1, lat2, lon2)
            leg_params.append((i, lat1, lon1, lat2, lon2, mid_lat, mid_lon, bearing))

        wind_tasks = [
            self.get_wind_at_point(
                p[5], p[6], cruise_altitude_ft=cruise_altitude_ft, forecast_time=forecast_time
            )
            for p in leg_params
        ]
        winds = await asyncio.gather(*wind_tasks)

        for (i, lat1, lon1, lat2, lon2, _mid_lat, _mid_lon, bearing), wind in zip(leg_params, winds):
            signed_hw = None
            headwind = None
            tailwind = None
            if wind:
                signed_hw, headwind, tailwind = wind_components_kt(
                    wind["wind_speed_kt"], wind["wind_direction_deg"], bearing
                )
                if wind.get("wind_source") == "surface_fallback":
                    used_fallback = True
                else:
                    used_pressure = True

            segments.append(
                {
                    "segment_index": i,
                    "start_lat": lat1,
                    "start_lon": lon1,
                    "end_lat": lat2,
                    "end_lon": lon2,
                    "bearing_deg": bearing,
                    "wind_speed_kt": wind["wind_speed_kt"] if wind else None,
                    "wind_direction_deg": wind["wind_direction_deg"] if wind else None,
                    "headwind_component_kt": round(signed_hw, 2) if signed_hw is not None else None,
                    "tailwind_component_kt": round(tailwind, 2) if tailwind is not None else None,
                    "wind_altitude_ft": wind.get("wind_altitude_ft") if wind else None,
                    "wind_pressure_level_hpa": wind.get("wind_pressure_level_hpa") if wind else None,
                    "wind_source": wind.get("wind_source") if wind else None,
                }
            )

        if used_fallback and not used_pressure:
            quality = "surface_fallback"
        elif used_fallback:
            quality = "mixed"
        elif used_pressure:
            quality = "pressure_level"
        else:
            quality = "unavailable"
        return segments, quality


open_meteo_client = OpenMeteoClient()
