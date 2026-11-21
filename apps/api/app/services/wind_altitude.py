from __future__ import annotations

import math

# Standard atmosphere approximations: pressure level (hPa) -> altitude (ft MSL)
PRESSURE_LEVELS_HPA: list[tuple[int, int]] = [
    (1000, 0),
    (925, 2500),
    (850, 5000),
    (700, 10000),
    (600, 14000),
    (500, 18000),
    (400, 24000),
    (300, 30000),
    (250, 34000),
    (200, 39000),
]

NM_TO_M = 1852.0


def cruise_altitude_to_pressure_level_hpa(cruise_altitude_ft: int) -> tuple[int, int]:
    """Map cruise altitude to nearest Open-Meteo pressure level and representative altitude."""
    best_level = PRESSURE_LEVELS_HPA[0][0]
    best_alt = PRESSURE_LEVELS_HPA[0][1]
    best_diff = abs(cruise_altitude_ft - best_alt)
    for level_hpa, alt_ft in PRESSURE_LEVELS_HPA:
        diff = abs(cruise_altitude_ft - alt_ft)
        if diff < best_diff:
            best_diff = diff
            best_level = level_hpa
            best_alt = alt_ft
    return best_level, best_alt


def wind_components_kt(
    wind_speed_kt: float, wind_direction_deg: float, track_bearing_deg: float
) -> tuple[float, float, float]:
    """
    Return signed headwind component (+ headwind, - tailwind),
    headwind_component_kt (>=0), tailwind_component_kt (>=0).
    """
    import math

    angle_rad = math.radians(wind_direction_deg - track_bearing_deg)
    signed = wind_speed_kt * math.cos(angle_rad)
    headwind = max(0.0, signed)
    tailwind = max(0.0, -signed)
    return signed, headwind, tailwind


def crosswind_component_kt(wind_speed_kt: float, wind_direction_deg: float, track_bearing_deg: float) -> float:
    """Magnitude of the wind component perpendicular to the track."""
    return abs(wind_speed_kt * math.sin(math.radians(wind_direction_deg - track_bearing_deg)))


def groundspeed_kt(true_airspeed_kt: float, headwind_kt: float, crosswind_kt: float = 0.0) -> float:
    """Groundspeed along the track after crabbing into a crosswind (0 when the aircraft cannot hold the track)."""
    if abs(crosswind_kt) >= true_airspeed_kt:
        return 0.0
    return math.sqrt(true_airspeed_kt**2 - crosswind_kt**2) - headwind_kt


def pressure_levels_around(altitude_ft: float) -> tuple[tuple[int, int], tuple[int, int], float]:
    """The pressure levels (hPa, ft) enclosing an altitude and the weight (0-1) of the upper one.

    Outside the available range, or exactly on a level, both entries are the same level.
    """
    levels = PRESSURE_LEVELS_HPA
    if altitude_ft <= levels[0][1]:
        return levels[0], levels[0], 0.0
    if altitude_ft >= levels[-1][1]:
        return levels[-1], levels[-1], 0.0
    for lower, upper in zip(levels, levels[1:]):
        if lower[1] <= altitude_ft <= upper[1]:
            weight = (altitude_ft - lower[1]) / (upper[1] - lower[1])
            if weight == 0.0:
                return lower, lower, 0.0
            if weight == 1.0:
                return upper, upper, 0.0
            return lower, upper, weight
    return levels[-1], levels[-1], 0.0


def wind_to_uv(speed_kt: float, direction_deg: float) -> tuple[float, float]:
    """East and north components of a wind given as (speed, direction it blows from)."""
    rad = math.radians(direction_deg)
    return -speed_kt * math.sin(rad), -speed_kt * math.cos(rad)


def uv_to_wind(u: float, v: float, calm_direction_deg: float = 0.0) -> tuple[float, float]:
    """(speed, direction it blows from) of east/north components."""
    speed = math.hypot(u, v)
    if speed < 1e-9:
        return 0.0, calm_direction_deg
    return speed, (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0


def interpolate_wind(
    lower: tuple[float, float], upper: tuple[float, float], weight: float
) -> tuple[float, float]:
    """Wind between two levels, interpolated on the (u, v) components so that veering winds stay correct.

    Each wind is (speed_kt, direction_deg); ``weight`` is the share of the upper one.
    """
    u0, v0 = wind_to_uv(*lower)
    u1, v1 = wind_to_uv(*upper)
    return uv_to_wind(u0 + weight * (u1 - u0), v0 + weight * (v1 - v0), lower[1])
