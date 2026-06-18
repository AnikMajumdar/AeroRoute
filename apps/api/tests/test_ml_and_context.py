import pytest

from app.services.delay_risk import predict_delay_risk
from app.services.route_context import (
    aircraft_snapshot,
    airport_snapshot,
    planning_economics,
    runway_suitability,
)


class TestDelayRiskModel:
    def test_low_risk_default(self):
        result = predict_delay_risk({})
        assert result["delay_risk"] == "low"
        assert result["model_name"] == "rules_baseline_v1"

    def test_high_risk_closed_airport(self):
        result = predict_delay_risk({"departure_closed": True})
        assert result["delay_risk"] == "high"


class TestRouteContext:
    def test_airport_snapshot_includes_runway(self):
        snap = airport_snapshot(
            {
                "icao_code": "KJFK",
                "name": "JFK",
                "longest_runway_ft": 14511,
                "airport_type": "large_airport",
            },
            "departure",
        )
        assert snap["longest_runway_ft"] == 14511

    def test_planning_economics_includes_fuel_price(self):
        econ = planning_economics(
            {"fuel_price_usd_per_gal": 6.5},
            {"primary_fuel_burn_gal": 100, "primary_fuel_cost_usd": 650, "fuel_breakdown": {"total_required_gal": 120}},
        )
        assert econ["fuel_price_usd_per_gal"] == 6.5
        assert econ["estimated_total_fuel_cost_usd"] == 780.0

    def test_runway_suitability(self):
        dep = {"icao_code": "KJFK", "longest_runway_ft": 14511}
        dest = {"icao_code": "KLAX", "longest_runway_ft": 12091}
        aircraft = {"min_runway_ft": 3000}
        result = runway_suitability(dep, dest, aircraft, [])
        assert result["departure"]["meets_aircraft_minimum"] is True

    def test_aircraft_snapshot_min_runway(self):
        ac = aircraft_snapshot({"name": "SR22", "min_runway_ft": 3000, "fuel_burn_gph": 17.2})
        assert ac["min_runway_ft"] == 3000
