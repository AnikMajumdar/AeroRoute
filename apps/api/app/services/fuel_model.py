from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class FuelBreakdown:
    climb_fuel_gal: float
    cruise_fuel_gal: float
    descent_fuel_gal: float
    trip_fuel_gal: float
    reserve_fuel_gal: float
    total_required_gal: float
    usable_capacity_gal: float | None
    fuel_remaining_gal: float | None
    fuel_margin_gal: float | None
    warnings: list[str]
    feasible: bool | None = None
    still_air_range_nm: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "climb_fuel_gal": round(self.climb_fuel_gal, 2),
            "cruise_fuel_gal": round(self.cruise_fuel_gal, 2),
            "descent_fuel_gal": round(self.descent_fuel_gal, 2),
            "trip_fuel_gal": round(self.trip_fuel_gal, 2),
            "reserve_fuel_gal": round(self.reserve_fuel_gal, 2),
            "total_required_gal": round(self.total_required_gal, 2),
            "usable_capacity_gal": self.usable_capacity_gal,
            "fuel_remaining_gal": self.fuel_remaining_gal,
            "fuel_margin_gal": self.fuel_margin_gal,
            "feasible": self.feasible,
            "still_air_range_nm": self.still_air_range_nm,
            "warnings": self.warnings,
        }


def usable_fuel_capacity(aircraft: dict[str, Any]) -> float | None:
    """Usable fuel (gal) of an aircraft profile, or None when it is not set."""
    value = aircraft.get("usable_fuel_gal")
    return float(value) if value else None


def still_air_range_nm(aircraft: dict[str, Any], usable_fuel_gal: float) -> float:
    """Distance flown at cruise speed on the fuel left after climb and the planned reserve."""
    fuel_burn_gph = float(aircraft["fuel_burn_gph"])
    climb_fuel = float(aircraft.get("climb_fuel_gal") or fuel_burn_gph * 0.15)
    reserve_fuel = float(aircraft.get("reserve_fuel_min") or 45) / 60.0 * fuel_burn_gph
    cruise_fuel = max(0.0, usable_fuel_gal - climb_fuel - reserve_fuel)
    return cruise_fuel / fuel_burn_gph * float(aircraft.get("cruise_speed_kt") or 0)


def calculate_fuel_breakdown(
    aircraft: dict[str, Any],
    cruise_ete_minutes: float,
    climb_ete_minutes: float | None = None,
    descent_ete_minutes: float | None = None,
    usable_fuel_gal: float | None = None,
) -> FuelBreakdown:
    """Educational fuel planning model — not a substitute for POH/dispatch calculations."""
    fuel_burn_gph = float(aircraft["fuel_burn_gph"])
    climb_fuel = float(aircraft.get("climb_fuel_gal") or fuel_burn_gph * 0.15)
    climb_time = float(aircraft.get("climb_time_min") or 12)
    descent_time = float(aircraft.get("descent_time_min") or 8)
    reserve_min = float(aircraft.get("reserve_fuel_min") or 45)

    if climb_ete_minutes is not None:
        climb_time = climb_ete_minutes
    if descent_ete_minutes is not None:
        descent_time = descent_ete_minutes

    descent_fuel = (descent_time / 60.0) * fuel_burn_gph * 0.6
    cruise_fuel = (cruise_ete_minutes / 60.0) * fuel_burn_gph
    trip_fuel = climb_fuel + cruise_fuel + descent_fuel
    reserve_fuel = (reserve_min / 60.0) * fuel_burn_gph
    total_required = trip_fuel + reserve_fuel

    capacity = usable_fuel_gal if usable_fuel_gal is not None else usable_fuel_capacity(aircraft)
    warnings: list[str] = []
    fuel_remaining: float | None = None
    feasible: bool | None = None
    range_nm: float | None = None

    if capacity is None:
        warnings.append("Usable fuel capacity is not set for this aircraft, so range and endurance were not checked.")
    else:
        fuel_remaining = round(capacity - total_required, 2)  # spare fuel beyond the planned reserve
        feasible = fuel_remaining >= 0
        range_nm = round(still_air_range_nm(aircraft, capacity), 1)
        if not feasible:
            warnings.append(
                f"Not feasible non-stop: about {total_required:.0f} gal needed including reserve, but only "
                f"{capacity:.0f} gal usable. Still-air range with reserve is about {range_nm:.0f} NM; "
                "plan a fuel stop (educational estimate — verify with POH)."
            )

    return FuelBreakdown(
        climb_fuel_gal=climb_fuel,
        cruise_fuel_gal=cruise_fuel,
        descent_fuel_gal=descent_fuel,
        trip_fuel_gal=trip_fuel,
        reserve_fuel_gal=reserve_fuel,
        total_required_gal=total_required,
        usable_capacity_gal=capacity,
        fuel_remaining_gal=fuel_remaining,
        fuel_margin_gal=fuel_remaining,
        warnings=warnings,
        feasible=feasible,
        still_air_range_nm=range_nm,
    )
