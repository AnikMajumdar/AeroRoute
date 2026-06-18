import math

import pytest

from app.geo.utils import (
    cross_track_distance_nm,
    destination_point,
    haversine_nm,
    initial_bearing_deg,
    intermediate_points,
)
from app.services.faa_nas_parser import parse_faa_airport_status
from app.services.fuel_model import calculate_fuel_breakdown
from app.services.open_meteo import OpenMeteoClient
from app.services.route_calculator import find_diversion_airports
from app.services.route_scoring import ScoringInput, calculate_normalized_score
from app.services.weather_checkpoints import WEATHER_CATEGORY_PENALTY
from app.services.wind_altitude import (
    cruise_altitude_to_pressure_level_hpa,
    wind_components_kt,
)


class TestHaversine:
    def test_same_point(self):
        assert haversine_nm(40.0, -74.0, 40.0, -74.0) == 0.0

    def test_known_distance(self):
        dist = haversine_nm(40.6398, -73.7789, 33.9425, -118.4081)
        assert 2100 < dist < 2200


class TestBearing:
    def test_north(self):
        bearing = initial_bearing_deg(0, 0, 1, 0)
        assert abs(bearing - 0) < 1 or abs(bearing - 360) < 1

    def test_east(self):
        bearing = initial_bearing_deg(0, 0, 0, 1)
        assert 85 < bearing < 95


class TestDestinationPoint:
    def test_round_trip(self):
        lat, lon = destination_point(40.0, -74.0, 90.0, 100.0)
        dist_back = haversine_nm(lat, lon, 40.0, -74.0)
        assert abs(dist_back - 100.0) < 1.0


class TestIntermediatePoints:
    def test_count(self):
        points = intermediate_points(40.0, -74.0, 34.0, -118.0, 3)
        assert len(points) == 3


class TestCrossTrack:
    def test_on_route(self):
        bearing = initial_bearing_deg(40.0, -74.0, 34.0, -118.0)
        half_dist = haversine_nm(40.0, -74.0, 34.0, -118.0) / 2
        mid_lat, mid_lon = destination_point(40.0, -74.0, bearing, half_dist)
        ct = cross_track_distance_nm(40.0, -74.0, 34.0, -118.0, mid_lat, mid_lon)
        assert ct < 1.0


class TestWindAltitude:
    def test_cessna_maps_near_8500ft(self):
        level, alt = cruise_altitude_to_pressure_level_hpa(8500)
        assert level in (850, 700)
        assert abs(alt - 8500) <= 3500

    def test_king_air_high_altitude(self):
        level, _ = cruise_altitude_to_pressure_level_hpa(28000)
        assert level <= 300

    def test_wind_components_headwind(self):
        signed, hw, tw = wind_components_kt(20, 90, 90)
        assert abs(signed - 20) < 0.1
        assert abs(hw - 20) < 0.1
        assert tw == 0.0

    def test_wind_components_tailwind(self):
        signed, hw, tw = wind_components_kt(20, 270, 90)
        assert abs(signed + 20) < 0.1
        assert hw == 0.0
        assert abs(tw - 20) < 0.1


class TestHeadwind:
    def test_direct_headwind(self):
        hw = OpenMeteoClient.headwind_component_kt(20, 90, 90)
        assert abs(hw - 20) < 0.1

    def test_direct_tailwind(self):
        hw = OpenMeteoClient.headwind_component_kt(20, 270, 90)
        assert abs(hw + 20) < 0.1


class TestFuelModel:
    def test_reserve_included_in_total(self):
        aircraft = {
            "fuel_burn_gph": 10.0,
            "climb_fuel_gal": 2.0,
            "climb_time_min": 10,
            "descent_time_min": 8,
            "reserve_fuel_min": 45,
        }
        breakdown = calculate_fuel_breakdown(aircraft, cruise_ete_minutes=120)
        assert breakdown.reserve_fuel_gal == pytest.approx(7.5, rel=0.01)
        assert breakdown.total_required_gal == pytest.approx(
            breakdown.trip_fuel_gal + breakdown.reserve_fuel_gal, rel=0.01
        )


class TestRouteScoring:
    def test_higher_composite_for_faster_route(self):
        base = ScoringInput(
            ete_minutes=180,
            fuel_burn_gal=50,
            baseline_ete_minutes=120,
            baseline_fuel_gal=50,
        )
        faster = ScoringInput(
            ete_minutes=120,
            fuel_burn_gal=50,
            baseline_ete_minutes=120,
            baseline_fuel_gal=50,
        )
        assert (
            calculate_normalized_score(faster)["composite_score"]
            > calculate_normalized_score(base)["composite_score"]
        )

    def test_weather_cautious_weights_weather(self):
        inp = ScoringInput(
            ete_minutes=120,
            fuel_burn_gal=50,
            baseline_ete_minutes=120,
            baseline_fuel_gal=50,
            departure_flight_category="IFR",
        )
        balanced = calculate_normalized_score(inp, "balanced")["composite_score"]
        cautious = calculate_normalized_score(inp, "weather_cautious")["composite_score"]
        assert cautious < balanced

    def test_scores_bounded_0_100(self):
        inp = ScoringInput(
            ete_minutes=500,
            fuel_burn_gal=200,
            baseline_ete_minutes=120,
            baseline_fuel_gal=50,
            departure_closed=True,
            departure_flight_category="LIFR",
        )
        result = calculate_normalized_score(inp)
        assert 0 <= result["composite_score"] <= 100
        for v in result["component_scores"].values():
            assert 0 <= v <= 100


class TestWeatherPenalties:
    def test_category_penalties_ordered(self):
        assert WEATHER_CATEGORY_PENALTY["VFR"] < WEATHER_CATEGORY_PENALTY["MVFR"]
        assert WEATHER_CATEGORY_PENALTY["MVFR"] < WEATHER_CATEGORY_PENALTY["IFR"]


class TestFAAParser:
    def test_parse_normal_status(self):
        status = parse_faa_airport_status("KJFK", {"delay": {"arrivalDelayMinutes": 15}})
        assert status.parse_success is True
        assert status.status == "delayed"
        assert status.delay_minutes == 15

    def test_parse_failure_unknown(self):
        status = parse_faa_airport_status("KJFK", None)
        assert status.parse_success is False
        assert status.status == "unknown"

    def test_ground_stop(self):
        status = parse_faa_airport_status("KJFK", {"groundStop": True})
        assert status.ground_stop is True
        assert status.status == "ground_stop"


class TestDiversionAirports:
    def _make_airport(self, id_, lat, lon, runway=5000, apt_type="medium_airport"):
        return {
            "id": id_,
            "ident": id_,
            "latitude": lat,
            "longitude": lon,
            "longest_runway_ft": runway,
            "airport_type": apt_type,
        }

    def test_finds_airports_in_corridor(self):
        route = [(40.0, -74.0), (34.0, -118.0)]
        bearing = initial_bearing_deg(40.0, -74.0, 34.0, -118.0)
        half_dist = haversine_nm(40.0, -74.0, 34.0, -118.0) / 2
        mid_lat, mid_lon = destination_point(40.0, -74.0, bearing, half_dist)
        div_lat, div_lon = destination_point(mid_lat, mid_lon, (bearing + 90) % 360, 35)

        airports = [
            self._make_airport("dep", 40.0, -74.0),
            self._make_airport("dest", 34.0, -118.0),
            self._make_airport("div1", div_lat, div_lon, runway=6000),
            self._make_airport("too_close", mid_lat, mid_lon, runway=6000),
            self._make_airport("short_runway", div_lat + 0.5, div_lon, runway=2000),
        ]
        results = find_diversion_airports(route, airports, "dep", "dest")
        ids = [r["airport"]["id"] for r in results]
        assert "div1" in ids
        assert "too_close" not in ids
        assert "short_runway" not in ids
        assert "dep" not in ids
