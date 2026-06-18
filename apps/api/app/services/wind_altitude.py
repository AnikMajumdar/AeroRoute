from __future__ import annotations

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
