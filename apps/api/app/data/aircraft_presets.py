from __future__ import annotations

from typing import TypedDict


class AircraftPresetSpec(TypedDict):
    name: str
    cruise_speed_kt: int
    fuel_burn_gph: float
    cruise_altitude_ft: int
    climb_fuel_gal: float
    climb_time_min: float
    descent_time_min: float
    reserve_fuel_min: float
    min_runway_ft: int
    notes: str


AIRCRAFT_PRESETS: list[AircraftPresetSpec] = [
    {
        "name": "Cessna 172",
        "cruise_speed_kt": 122,
        "fuel_burn_gph": 8.5,
        "cruise_altitude_ft": 8500,
        "climb_fuel_gal": 1.5,
        "climb_time_min": 12,
        "descent_time_min": 8,
        "reserve_fuel_min": 45,
        "min_runway_ft": 2500,
        "notes": "Cessna 172S — educational planning values",
    },
    {
        "name": "Piper PA-28",
        "cruise_speed_kt": 128,
        "fuel_burn_gph": 9.5,
        "cruise_altitude_ft": 8500,
        "climb_fuel_gal": 1.8,
        "climb_time_min": 14,
        "descent_time_min": 9,
        "reserve_fuel_min": 50,
        "min_runway_ft": 2500,
        "notes": "Piper PA-28 Archer — educational planning values",
    },
    {
        "name": "Beechcraft Baron",
        "cruise_speed_kt": 200,
        "fuel_burn_gph": 26.0,
        "cruise_altitude_ft": 18000,
        "climb_fuel_gal": 8.0,
        "climb_time_min": 18,
        "descent_time_min": 12,
        "reserve_fuel_min": 60,
        "min_runway_ft": 4000,
        "notes": "Beechcraft Baron G58 — educational planning values",
    },
    {
        "name": "Cirrus SR22",
        "cruise_speed_kt": 183,
        "fuel_burn_gph": 17.2,
        "cruise_altitude_ft": 12000,
        "climb_fuel_gal": 4.0,
        "climb_time_min": 15,
        "descent_time_min": 10,
        "reserve_fuel_min": 55,
        "min_runway_ft": 3000,
        "notes": "Cirrus SR22 — educational planning values",
    },
    {
        "name": "King Air 350",
        "cruise_speed_kt": 312,
        "fuel_burn_gph": 90.0,
        "cruise_altitude_ft": 28000,
        "climb_fuel_gal": 25.0,
        "climb_time_min": 22,
        "descent_time_min": 15,
        "reserve_fuel_min": 90,
        "min_runway_ft": 5000,
        "notes": "King Air 350 — educational planning values",
    },
]
