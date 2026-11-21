from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.geo.utils import destination_point, haversine_nm, initial_bearing_deg
from app.planning_constraints import FORECAST_HORIZON_DAYS
from app.services.cache import cache_service
from app.services.wind_altitude import (
    crosswind_component_kt,
    cruise_altitude_to_pressure_level_hpa,
    interpolate_wind,
    pressure_levels_around,
    uv_to_wind,
    wind_components_kt,
    wind_to_uv,
)

logger = logging.getLogger(__name__)

OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

# Pressure levels supported by Open-Meteo standard forecast API
AVAILABLE_LEVELS_HPA = [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200]

# Open-Meteo returns whole UTC days starting today at 00:00. A departure may be up to FORECAST_HORIZON_DAYS
# from now, which falls on day number FORECAST_HORIZON_DAYS (counting today as day 0), so one more day than
# the horizon has to be requested to cover the whole allowed departure window.
OPEN_METEO_FORECAST_DAYS = FORECAST_HORIZON_DAYS + 1

# A leg is cut into parts of at most this length and the wind is sampled once per part (it used to be one sample
# per leg, e.g. a single sample for 2,000 NM); the cap bounds the number of Open-Meteo requests for very long legs.
WIND_SAMPLE_SPACING_NM = 200.0
MAX_WIND_SAMPLES_PER_LEG = 20

# The forecast grid is 0.25 degrees; snapping requests to it lets nearby points, routes and users share one request.
WIND_GRID_DEG = 0.25


def _snap_to_grid(value: float) -> float:
    return round(value / WIND_GRID_DEG) * WIND_GRID_DEG


def wind_quality_from_segments(segments: list[dict[str, Any]]) -> str:
    """Classify how the legs of a route were wind-sampled.

    ``pressure_level`` / ``surface_fallback``: every leg has wind from that source.
    ``mixed``: every leg has wind, from both sources.
    ``partial``: some legs have no wind at all (they are planned with zero wind).
    ``unavailable``: no leg has wind data.
    """
    sources = [segment.get("wind_source") for segment in segments]
    sampled = {source for source in sources if source}
    if not sampled:
        return "unavailable"
    if not all(sources):
        return "partial"
    if sampled == {"pressure_level"}:
        return "pressure_level"
    if sampled == {"surface_fallback"}:
        return "surface_fallback"
    return "mixed"


def _mean_wind(winds: list[dict[str, Any]]) -> tuple[float, float]:
    """Vector-mean (speed, direction the wind blows from) of several winds."""
    vectors = [wind_to_uv(w["wind_speed_kt"], w["wind_direction_deg"]) for w in winds]
    u = sum(vec[0] for vec in vectors) / len(vectors)
    v = sum(vec[1] for vec in vectors) / len(vectors)
    return uv_to_wind(u, v, float(winds[0]["wind_direction_deg"]))


def _value_at(series: list[Any] | None, index: int) -> float | None:
    if not series or index >= len(series) or series[index] is None:
        return None
    return float(series[index])


class OpenMeteoClient:
    def __init__(self) -> None:
        self.timeout = httpx.Timeout(15.0, connect=5.0)

    @staticmethod
    def _hour_index(times: list[str], forecast_time: datetime | None) -> int | None:
        """Index of the first forecast hour at or after ``forecast_time`` (rounded down to the hour; now if omitted).

        Returns None when the time lies after the last returned hour, so the caller reports the wind as
        unavailable instead of silently using a different hour.
        """
        target = (forecast_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
        target = target.replace(minute=0, second=0, microsecond=0)
        for idx, raw in enumerate(times):
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= target:
                return idx
        return None

    def _pressure_level_hourly_vars(self, level_hpa: int) -> str:
        return f"windspeed_{level_hpa}hPa,winddirection_{level_hpa}hPa"

    async def get_wind_at_point(
        self,
        lat: float,
        lon: float,
        cruise_altitude_ft: int = 10000,
        forecast_time: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Wind at a point and altitude, interpolated between the two pressure levels around the altitude."""
        lower, upper, weight = pressure_levels_around(cruise_altitude_ft)
        lat, lon = _snap_to_grid(lat), _snap_to_grid(lon)
        effective_time = (forecast_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
        # The cache holds the raw winds of both levels, so aircraft at different altitudes share an entry.
        cache_key = f"wind:{lat:.2f}:{lon:.2f}:{lower[0]}:{upper[0]}:{effective_time:%Y-%m-%dT%H}"
        raw = cache_service.get(cache_key)
        if raw is None:
            raw = await self._fetch_raw_winds(lat, lon, sorted({lower[0], upper[0]}), forecast_time, effective_time)
            if raw is None:
                return None
            cache_service.set(cache_key, raw, settings.cache_wind_ttl)
        return self._wind_from_raw(raw, lower, upper, weight, cruise_altitude_ft)

    async def _fetch_raw_winds(
        self,
        lat: float,
        lon: float,
        levels_hpa: list[int],
        forecast_time: datetime | None,
        effective_time: datetime,
    ) -> dict[str, Any] | None:
        """Winds of the given pressure levels (and the surface) for one forecast hour, or None if unavailable."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                hourly_vars = ",".join(self._pressure_level_hourly_vars(level) for level in levels_hpa)
                response = await client.get(
                    OPEN_METEO_BASE,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "hourly": f"{hourly_vars},windspeed_10m,winddirection_10m",
                        "windspeed_unit": "kn",
                        "forecast_days": OPEN_METEO_FORECAST_DAYS,
                        "timezone": "UTC",
                    },
                )
                response.raise_for_status()
                hourly = response.json().get("hourly", {})
                times = hourly.get("time", [])
                idx = self._hour_index(times, forecast_time)
                if idx is None:
                    logger.warning(
                        "Open-Meteo forecast for %s,%s does not cover %s (last hour %s)",
                        lat,
                        lon,
                        effective_time.isoformat(),
                        times[-1] if times else None,
                    )
                    return None

                def wind_at(speed_key: str, direction_key: str) -> dict[str, float] | None:
                    speed = _value_at(hourly.get(speed_key), idx)
                    direction = _value_at(hourly.get(direction_key), idx)
                    return {"speed": speed, "direction": direction} if speed is not None and direction is not None else None

                raw = {
                    "levels": {
                        str(level): wind_at(f"windspeed_{level}hPa", f"winddirection_{level}hPa") for level in levels_hpa
                    },
                    "surface": wind_at("windspeed_10m", "winddirection_10m"),
                }
                if raw["surface"] is None and not any(raw["levels"].values()):
                    return None
                return raw
        except httpx.TimeoutException:
            logger.warning("Open-Meteo wind request timed out at %s,%s", lat, lon)
            return None
        except Exception as exc:
            logger.warning("Open-Meteo wind fetch failed at %s,%s: %s", lat, lon, exc)
            return None

    @staticmethod
    def _wind_from_raw(
        raw: dict[str, Any],
        lower: tuple[int, int],
        upper: tuple[int, int],
        weight: float,
        cruise_altitude_ft: int,
    ) -> dict[str, Any] | None:
        levels = raw.get("levels") or {}
        lower_wind, upper_wind = levels.get(str(lower[0])), levels.get(str(upper[0]))
        if lower_wind and upper_wind:
            speed, direction = interpolate_wind(
                (lower_wind["speed"], lower_wind["direction"]), (upper_wind["speed"], upper_wind["direction"]), weight
            )
            return {
                "wind_speed_kt": speed,
                "wind_direction_deg": direction,
                "wind_altitude_ft": int(round(cruise_altitude_ft)),
                "wind_pressure_level_hpa": cruise_altitude_to_pressure_level_hpa(cruise_altitude_ft)[0],
                "wind_source": "pressure_level",
            }
        surface = raw.get("surface")
        if not surface:
            return None
        return {
            "wind_speed_kt": surface["speed"],
            "wind_direction_deg": surface["direction"],
            "wind_altitude_ft": 10,
            "wind_pressure_level_hpa": None,
            "wind_source": "surface_fallback",
        }

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
        cruise_speed_kt: float | None = None,
        spacing_nm: float = WIND_SAMPLE_SPACING_NM,
    ) -> tuple[list[dict[str, Any]], str]:
        """Sample the winds along every leg; returns one summary per leg and the overall wind_data_quality.

        A leg is cut into equal parts of at most ``spacing_nm``. The wind is fetched at the great-circle midpoint of
        each part, for the time the aircraft is expected to be there (``forecast_time`` plus the distance flown at
        ``cruise_speed_kt``). The leg summary holds the mean wind; ``samples`` (not stored) keeps the per-part
        components so the groundspeed can be computed part by part.
        """
        legs: list[dict[str, Any]] = []
        tasks = []
        flown_nm = 0.0
        for i in range(len(waypoints) - 1):
            lat1, lon1 = waypoints[i]
            lat2, lon2 = waypoints[i + 1]
            leg_nm = haversine_nm(lat1, lon1, lat2, lon2)
            bearing = initial_bearing_deg(lat1, lon1, lat2, lon2)
            count = max(1, min(MAX_WIND_SAMPLES_PER_LEG, math.ceil(leg_nm / spacing_nm)))
            part_nm = leg_nm / count
            parts = []
            for k in range(count):
                mid_nm = (k + 0.5) * part_nm
                lat, lon = destination_point(lat1, lon1, bearing, mid_nm) if leg_nm > 0 else (lat1, lon1)
                when = forecast_time
                if forecast_time is not None and cruise_speed_kt:
                    when = forecast_time + timedelta(hours=(flown_nm + mid_nm) / cruise_speed_kt)
                parts.append({"start_nm": k * part_nm, "end_nm": (k + 1) * part_nm, "lat": lat, "lon": lon})
                tasks.append(
                    self.get_wind_at_point(lat, lon, cruise_altitude_ft=cruise_altitude_ft, forecast_time=when)
                )
            legs.append({"index": i, "start": (lat1, lon1), "end": (lat2, lon2), "bearing": bearing, "parts": parts})
            flown_nm += leg_nm

        results = list(await asyncio.gather(*tasks))
        segments: list[dict[str, Any]] = []
        for leg in legs:
            winds, results = results[: len(leg["parts"])], results[len(leg["parts"]) :]
            segments.append(self._summarise_leg(leg, winds))
        return segments, wind_quality_from_segments(segments)

    @staticmethod
    def _summarise_leg(leg: dict[str, Any], winds: list[dict[str, Any] | None]) -> dict[str, Any]:
        (lat1, lon1), (lat2, lon2) = leg["start"], leg["end"]
        summary: dict[str, Any] = {
            "segment_index": leg["index"],
            "start_lat": lat1,
            "start_lon": lon1,
            "end_lat": lat2,
            "end_lon": lon2,
            "bearing_deg": leg["bearing"],
            "wind_speed_kt": None,
            "wind_direction_deg": None,
            "headwind_component_kt": None,
            "tailwind_component_kt": None,
            "crosswind_component_kt": None,
            "wind_altitude_ft": None,
            "wind_pressure_level_hpa": None,
            "wind_source": None,
        }
        available = [(k, wind) for k, wind in enumerate(winds) if wind]
        if len(available) < len(winds):
            logger.warning(
                "Wind unavailable for %d of %d samples on leg %d", len(winds) - len(available), len(winds), leg["index"]
            )
        if not available:
            return summary

        components: dict[int, tuple[float, float]] = {}
        for k, wind in available:
            part = leg["parts"][k]
            track = initial_bearing_deg(part["lat"], part["lon"], lat2, lon2)
            signed, _, _ = wind_components_kt(wind["wind_speed_kt"], wind["wind_direction_deg"], track)
            components[k] = (signed, crosswind_component_kt(wind["wind_speed_kt"], wind["wind_direction_deg"], track))
        mean_headwind = sum(c[0] for c in components.values()) / len(components)
        mean_crosswind = sum(c[1] for c in components.values()) / len(components)

        # Parts whose wind could not be fetched take the average of the others so the whole leg is covered.
        samples = []
        for k, part in enumerate(leg["parts"]):
            headwind, crosswind = components.get(k, (mean_headwind, mean_crosswind))
            samples.append(
                {
                    "start_nm": part["start_nm"],
                    "end_nm": part["end_nm"],
                    "headwind_component_kt": headwind,
                    "crosswind_component_kt": crosswind,
                }
            )

        speed, direction = _mean_wind([wind for _, wind in available])
        first = available[0][1]
        summary.update(
            {
                "wind_speed_kt": speed,
                "wind_direction_deg": direction,
                "headwind_component_kt": round(mean_headwind, 2),
                "tailwind_component_kt": round(max(0.0, -mean_headwind), 2),
                "crosswind_component_kt": round(mean_crosswind, 2),
                "wind_altitude_ft": first.get("wind_altitude_ft"),
                "wind_pressure_level_hpa": first.get("wind_pressure_level_hpa"),
                "wind_source": (
                    "surface_fallback"
                    if any(wind.get("wind_source") == "surface_fallback" for _, wind in available)
                    else "pressure_level"
                ),
                "samples": samples,
            }
        )
        return summary


open_meteo_client = OpenMeteoClient()
