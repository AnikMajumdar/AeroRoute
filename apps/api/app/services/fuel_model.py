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
            "warnings": self.warnings,
        }


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

    warnings: list[str] = []
    fuel_remaining: float | None = None
    fuel_margin: float | None = None

    if usable_fuel_gal is not None:
        fuel_remaining = usable_fuel_gal - total_required
        fuel_margin = fuel_remaining
        if fuel_remaining < 0:
            warnings.append(
                f"Estimated fuel shortfall of {abs(fuel_remaining):.1f} gal "
                "(educational estimate — verify with POH)"
            )
        elif fuel_remaining < reserve_fuel:
            warnings.append("Fuel remaining below planned reserve (educational warning)")

    return FuelBreakdown(
        climb_fuel_gal=climb_fuel,
        cruise_fuel_gal=cruise_fuel,
        descent_fuel_gal=descent_fuel,
        trip_fuel_gal=trip_fuel,
        reserve_fuel_gal=reserve_fuel,
        total_required_gal=total_required,
        usable_capacity_gal=usable_fuel_gal,
        fuel_remaining_gal=fuel_remaining,
        fuel_margin_gal=fuel_margin,
        warnings=warnings,
    )
