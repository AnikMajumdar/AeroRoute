import pytest

from app.geo.utils import is_in_route_corridor, is_on_route_between
from app.services.diversion_postgis import _python_fallback_search
from app.services.weather_checkpoints import select_checkpoint_airports


# KJFK → KLAX great-circle (approximate)
KJFK = (40.6413, -73.7781)
KLAX = (33.9425, -118.4081)

AIRPORTS = [
    {
        "id": "dep",
        "icao_code": "KJFK",
        "name": "JFK",
        "latitude": KJFK[0],
        "longitude": KJFK[1],
        "airport_type": "large_airport",
        "longest_runway_ft": 14511,
    },
    {
        "id": "dest",
        "icao_code": "KLAX",
        "name": "LAX",
        "latitude": KLAX[0],
        "longitude": KLAX[1],
        "airport_type": "large_airport",
        "longest_runway_ft": 12091,
    },
    {
        "id": "mid",
        "icao_code": "KMCI",
        "name": "Kansas City",
        "latitude": 39.2976,
        "longitude": -94.7139,
        "airport_type": "large_airport",
        "longest_runway_ft": 10801,
    },
    {
        "id": "past-dest",
        "icao_code": "KSAN",
        "name": "San Diego",
        "latitude": 32.7338,
        "longitude": -117.1933,
        "airport_type": "large_airport",
        "longest_runway_ft": 9401,
    },
    {
        "id": "behind-dep",
        "icao_code": "KBOS",
        "name": "Boston",
        "latitude": 42.3656,
        "longitude": -71.0096,
        "airport_type": "large_airport",
        "longest_runway_ft": 10083,
    },
    {
        "id": "diversion",
        "icao_code": "KLAS",
        "name": "Las Vegas",
        "latitude": 36.0840,
        "longitude": -115.1537,
        "airport_type": "large_airport",
        "longest_runway_ft": 14510,
    },
]


class TestAlongTrack:
    def test_kansas_city_is_between_jfk_and_lax(self):
        assert is_on_route_between(*KJFK, *KLAX, AIRPORTS[2]["latitude"], AIRPORTS[2]["longitude"])

    def test_san_diego_is_past_lax(self):
        assert not is_on_route_between(*KJFK, *KLAX, AIRPORTS[3]["latitude"], AIRPORTS[3]["longitude"])

    def test_boston_is_behind_jfk(self):
        assert not is_on_route_between(*KJFK, *KLAX, AIRPORTS[4]["latitude"], AIRPORTS[4]["longitude"])

    def test_las_vegas_in_diversion_corridor(self):
        assert is_in_route_corridor(*KJFK, *KLAX, AIRPORTS[5]["latitude"], AIRPORTS[5]["longitude"])


class TestCheckpointSelection:
    def test_excludes_airports_past_destination(self):
        waypoints = [KJFK, KLAX]
        selected = select_checkpoint_airports(waypoints, AIRPORTS, "dep", "dest")
        ids = {a["id"] for a in selected}
        assert "past-dest" not in ids
        assert "behind-dep" not in ids
        assert "mid" in ids


class TestDiversionFallback:
    def test_python_fallback_finds_along_route_airport(self):
        results = _python_fallback_search(
            AIRPORTS,
            KJFK[0],
            KJFK[1],
            KLAX[0],
            KLAX[1],
            "dep",
            "dest",
            min_runway_ft=3000,
        )
        assert len(results) >= 1
        icaos = {(r["airport"].get("icao_code")) for r in results}
        assert "KLAS" in icaos
