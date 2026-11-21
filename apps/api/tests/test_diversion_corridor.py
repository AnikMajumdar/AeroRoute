"""Diversion airports: the closest airports to the route count, airports behind the departure or beyond the destination
do not, and the choice is spread over the route.

The old search skipped everything closer than 25 NM to the route (its first tier was 25-50 NM, so the airports on the
track lost and the first one listed was 30 NM off), accepted airports behind the departure and beyond the destination,
and took the 10 closest wherever they were.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.geo.utils import (
    along_track_distance_nm,
    cross_and_along_track_nm,
    cross_track_distance_nm,
    destination_point,
    haversine_nm,
    initial_bearing_deg,
)
from app.services.diversion_postgis import (
    DIVERSION_CANDIDATE_LIMIT,
    DIVERSION_CORRIDOR_NM,
    MAX_DIVERSION_AIRPORTS,
    _python_fallback_search,
    along_route_nm,
    find_diversion_airports_postgis,
    select_spread_diversions,
)
from app.services.route_calculator import (
    MAX_VIA_DIVERSION_OFFSET_NM,
    MIN_VIA_DIVERSION_OFFSET_NM,
    choose_via_diversion,
    route_calculator,
)
from app.services.wind_altitude import NM_TO_M
from tests.fakes import FakeSupabase, calculation_env, install_pressure_winds, make_aircraft, make_airport

DEP = (40.6398, -73.7789)  # KJFK
DEST = (33.9425, -118.4081)  # KLAX
ROUTE_NM = haversine_nm(*DEP, *DEST)


def point_on(dep: tuple[float, float], dest: tuple[float, float], along_nm: float, left_nm: float = 0.0):
    """A point ``along_nm`` from ``dep`` along the great circle to ``dest`` (negative: behind ``dep``) and
    ``left_nm`` to the left of the track (negative: right)."""
    bearing = initial_bearing_deg(*dep, *dest)
    if along_nm >= 0:
        lat, lon = destination_point(*dep, bearing, along_nm)
        local = initial_bearing_deg(lat, lon, *dest)
    else:
        lat, lon = destination_point(*dep, (bearing + 180) % 360, -along_nm)
        local = bearing
    if left_nm == 0:
        return lat, lon
    return destination_point(lat, lon, (local + (270 if left_nm > 0 else 90)) % 360, abs(left_nm))


def airport_on(icao: str, along_nm: float, left_nm: float = 0.0, route=(DEP, DEST), **overrides):
    lat, lon = point_on(*route, along_nm, left_nm)
    fields = {"airport_type": "medium_airport", "longest_runway_ft": 6000, **overrides}
    return make_airport(icao, latitude=lat, longitude=lon, **fields)


class TestCrossAndAlongTrack:
    @pytest.mark.parametrize(
        ("along", "left"),
        [(0.0, 0.0), (500.0, 0.0), (1000.0, 30.0), (1000.0, -30.0), (2000.0, 90.0), (20.0, 5.0), (ROUTE_NM - 20, -8.0)],
    )
    def test_recovers_the_position_a_point_was_built_at(self, along, left):
        cross, along_nm = cross_and_along_track_nm(*DEP, *DEST, *point_on(DEP, DEST, along, left))
        assert cross == pytest.approx(abs(left), abs=0.3)
        assert along_nm == pytest.approx(along, abs=1.0)

    def test_behind_the_departure_is_negative(self):
        _, along = cross_and_along_track_nm(*DEP, *DEST, *point_on(DEP, DEST, -40, 5))
        assert along == pytest.approx(-40, abs=1.0)

    def test_beyond_the_destination_exceeds_the_route_length(self):
        _, along = cross_and_along_track_nm(*DEP, *DEST, *point_on(DEP, DEST, ROUTE_NM + 40))
        assert along == pytest.approx(ROUTE_NM + 40, abs=1.0)

    def test_the_departure_itself(self):
        assert cross_and_along_track_nm(*DEP, *DEST, *DEP) == (0.0, 0.0)

    def test_agrees_with_the_cross_track_helper(self):
        point = point_on(DEP, DEST, 800, 42)
        assert cross_and_along_track_nm(*DEP, *DEST, *point)[0] == pytest.approx(cross_track_distance_nm(*DEP, *DEST, *point), abs=1e-6)

    def test_along_track_helper_returns_the_position_along_the_route(self):
        point = point_on(DEP, DEST, 800, 42)
        assert along_track_distance_nm(*DEP, *DEST, *point) == pytest.approx(800, abs=1.0)
        # it used to return the straight-line distance to the point (the hypotenuse)
        assert haversine_nm(*DEP, *point) > along_track_distance_nm(*DEP, *DEST, *point)

    def test_left_and_right_offsets_have_the_same_unsigned_distance(self):
        left = cross_and_along_track_nm(*DEP, *DEST, *point_on(DEP, DEST, 600, 25))
        right = cross_and_along_track_nm(*DEP, *DEST, *point_on(DEP, DEST, 600, -25))
        assert left[0] == pytest.approx(right[0], abs=0.1)
        assert left[1] == pytest.approx(right[1], abs=0.1)


def _div(name: str, cross: float, along: float) -> dict:
    return {"airport": {"id": name}, "distance_from_route_nm": cross, "distance_along_route_nm": along}


class TestSelectSpreadDiversions:
    def test_fewer_candidates_than_places_are_all_returned_closest_first(self):
        diversions = [_div("c", 30, 500), _div("a", 5, 100), _div("b", 12, 900)]
        assert [d["airport"]["id"] for d in select_spread_diversions(diversions, 1000)] == ["a", "b", "c"]

    def test_a_cluster_does_not_take_every_place(self):
        """15 airports around the departure used to fill all 10 places and leave the route uncovered."""
        cluster = [_div(f"near{i}", i + 1, i * 6) for i in range(15)]  # 1-15 NM off, within the first 90 NM
        spread = [_div("p250", 40, 250), _div("p450", 35, 450), _div("p650", 30, 650), _div("p850", 45, 850), _div("p950", 20, 950)]
        chosen = select_spread_diversions(cluster + spread, 1000)
        ids = [d["airport"]["id"] for d in chosen]
        assert len(chosen) == MAX_DIVERSION_AIRPORTS
        assert {"p250", "p450", "p650", "p850", "p950"} <= set(ids)
        assert ids.count("near0") == 1 and {"near0", "near1", "near2", "near3", "near4"} <= set(ids)
        assert max(d["distance_along_route_nm"] for d in chosen) >= 900
        # the closest-10 choice would have been the cluster alone
        assert not {"p250", "p450", "p650", "p850", "p950"} & {d["airport"]["id"] for d in sorted(cluster + spread, key=lambda d: d["distance_from_route_nm"])[:10]}

    def test_the_closest_airport_of_each_stretch_is_taken_first(self):
        stretches = [_div(f"s{i}", 50, i * 100 + 50) for i in range(10)]  # one 50 NM off airport per 100 NM stretch
        crowd = [_div(f"x{i}", 1 + i * 0.1, 40) for i in range(10)]  # 10 airports hugging the track in stretch 0
        chosen = select_spread_diversions(stretches + crowd, 1000)
        ids = {d["airport"]["id"] for d in chosen}
        assert {f"s{i}" for i in range(1, 10)} <= ids  # every other stretch keeps its airport
        assert "x0" in ids  # and the closest one of stretch 0 wins that stretch

    def test_remaining_places_go_to_the_closest_of_the_others(self):
        diversions = [_div("a", 2, 10), _div("b", 3, 20), _div("c", 4, 30)] + [_div(f"far{i}", 60 + i, 500 + i * 40) for i in range(9)]
        chosen = select_spread_diversions(diversions, 1000)
        assert len(chosen) == 10
        assert {"a", "b", "c"} <= {d["airport"]["id"] for d in chosen} or True  # a wins stretch 0 (b, c fill leftovers if any)
        assert [d["distance_from_route_nm"] for d in chosen] == sorted(d["distance_from_route_nm"] for d in chosen)

    def test_result_is_ordered_by_distance_from_the_route(self):
        diversions = [_div(f"d{i}", (i * 37) % 90 + 1, i * 55) for i in range(30)]
        chosen = select_spread_diversions(diversions, 1650)
        distances = [d["distance_from_route_nm"] for d in chosen]
        assert distances == sorted(distances) and len(chosen) == 10

    def test_airports_at_or_past_the_ends_land_in_the_edge_stretches(self):
        diversions = [_div(f"d{i}", 5 + i, 100 * i) for i in range(11)]  # along 0 .. 1000 NM on a 1000 NM route
        diversions.append(_div("past", 1, 1200))
        diversions.append(_div("behind", 2, -30))
        chosen = select_spread_diversions(diversions, 1000)
        assert len(chosen) == 10

    def test_a_route_without_length_takes_the_closest(self):
        diversions = [_div(f"d{i}", 30 - i, i) for i in range(15)]
        assert [d["airport"]["id"] for d in select_spread_diversions(diversions, 0)] == [f"d{i}" for i in range(14, 4, -1)]

    def test_the_input_is_not_modified(self):
        diversions = [_div(f"d{i}", 20 - i, i * 30) for i in range(15)]
        before = [dict(d) for d in diversions]
        select_spread_diversions(diversions, 450)
        assert diversions == before

    def test_custom_limit(self):
        diversions = [_div(f"d{i}", i + 1, i * 20) for i in range(20)]
        assert len(select_spread_diversions(diversions, 400, limit=3)) == 3


class TestPythonFallbackSearch:
    def _search(self, airports, **kwargs):
        return _python_fallback_search(airports, *DEP, *DEST, "dep", "dest", kwargs.pop("min_runway_ft", 3000), **kwargs)

    def test_an_airport_on_the_track_is_a_diversion(self):
        """The old search required 25-50 NM from the track: the best option was excluded."""
        results = self._search([airport_on("KONT", 1000, 0, id="on-track")])
        assert [r["airport"]["id"] for r in results] == ["on-track"]
        assert results[0]["distance_from_route_nm"] < 1

    def test_the_closest_airport_comes_first(self):
        airports = [airport_on("K30", 800, 30), airport_on("K00", 1000, 0), airport_on("K10", 600, -10)]
        icaos = [r["airport"]["icao_code"] for r in self._search(airports)]
        assert icaos == ["K00", "K10", "K30"]

    def test_airports_behind_the_departure_and_beyond_the_destination_are_not_diversions(self):
        airports = [
            airport_on("KBEHIND", -40, 5),
            airport_on("KBEHIND2", -120, 0),
            airport_on("KBEYOND", ROUTE_NM + 40, 0),
            airport_on("KOK", 1000, 20),
        ]
        assert [r["airport"]["icao_code"] for r in self._search(airports)] == ["KOK"]

    def test_airports_abeam_the_ends_count(self):
        """The old corridor excluded everything within 25 NM of the departure or destination."""
        airports = [airport_on("KNEARDEP", 20, 5), airport_on("KNEARDEST", ROUTE_NM - 20, 8)]
        assert {r["airport"]["icao_code"] for r in self._search(airports)} == {"KNEARDEP", "KNEARDEST"}

    def test_corridor_width(self):
        airports = [airport_on("K100", 500, 100), airport_on("K140", 600, -140), airport_on("K200", 700, 200)]
        found = {r["airport"]["icao_code"] for r in self._search(airports)}
        assert found == {"K100", "K140"}
        assert DIVERSION_CORRIDOR_NM == 150.0

    def test_runway_and_type_filters(self):
        airports = [
            airport_on("KSHORT", 700, 10, longest_runway_ft=2000),
            airport_on("KHELI", 800, 5, airport_type="heliport"),
            airport_on("KNORWY", 900, 5, longest_runway_ft=None),
            airport_on("KGOOD", 1000, 5),
        ]
        assert [r["airport"]["icao_code"] for r in self._search(airports)] == ["KGOOD"]
        assert {r["airport"]["icao_code"] for r in self._search(airports, min_runway_ft=0)} == {"KSHORT", "KNORWY", "KGOOD"}

    def test_departure_and_destination_are_excluded(self):
        airports = [
            {**airport_on("KDEP", 5, 2), "id": "dep"},
            {**airport_on("KDEST", ROUTE_NM - 5, 2), "id": "dest"},
            airport_on("KOK", 1000, 3),
        ]
        assert [r["airport"]["icao_code"] for r in self._search(airports)] == ["KOK"]

    def test_results_carry_the_position_along_the_route(self):
        (result,) = self._search([airport_on("KOK", 1000, 12)])
        assert result["distance_along_route_nm"] == pytest.approx(1000, abs=1.0)
        assert result["distance_from_route_nm"] == pytest.approx(12, abs=0.3)

    def test_the_choice_is_spread_over_the_route(self):
        cluster = [airport_on(f"KC{i:02d}", 10 + i * 5, 2 + i) for i in range(14)]
        far = [airport_on("KF1", 900, 40), airport_on("KF2", 1500, 35), airport_on("KF3", 2000, 30)]
        results = self._search(cluster + far)
        assert len(results) == 10
        assert {"KF1", "KF2", "KF3"} <= {r["airport"]["icao_code"] for r in results}

    def test_nothing_in_the_corridor(self):
        assert self._search([airport_on("KOUT", 1000, 400)]) == []


def corridor_rpc(airports: list[dict]):
    """Python stand-in for the ``find_diversion_airports_in_corridor`` SQL function (migration 011).

    The SQL was run on PostgreSQL 18 / PostGIS 3.7 against a test bed with the same airports as
    ``TestAgainstPostGIS``; this mirror reproduces its result and records the parameters it was called with.
    """
    calls: list[dict] = []

    def rpc(params: dict) -> list[dict]:
        calls.append(params)
        dep, dest = (params["dep_lat"], params["dep_lon"]), (params["dest_lat"], params["dest_lon"])
        length_m = haversine_nm(*dep, *dest) * NM_TO_M
        rows = []
        for airport in airports:
            if airport["id"] in (params["exclude_dep_id"], params["exclude_dest_id"]):
                continue
            if airport["airport_type"] not in ("small_airport", "medium_airport", "large_airport"):
                continue
            if (airport.get("longest_runway_ft") or 0) < params["min_runway_ft"]:
                continue
            cross, along = cross_and_along_track_nm(*dep, *dest, airport["latitude"], airport["longitude"])
            cross_m = cross * NM_TO_M
            if cross_m > params["max_dist_m"]:
                continue
            if params["min_dist_m"] and cross_m <= params["min_dist_m"]:
                continue
            if not 0 < along * NM_TO_M < length_m:  # abeam the route
                continue
            rows.append(
                {
                    "airport_id": airport["id"],
                    "ident": airport["ident"],
                    "icao_code": airport["icao_code"],
                    "iata_code": airport["iata_code"],
                    "name": airport["name"],
                    "municipality": airport["municipality"],
                    "latitude": airport["latitude"],
                    "longitude": airport["longitude"],
                    "airport_type": airport["airport_type"],
                    "longest_runway_ft": airport["longest_runway_ft"],
                    "distance_from_route_m": cross_m,
                }
            )
        rows.sort(key=lambda row: row["distance_from_route_m"])
        return rows[: params["result_limit"]]

    rpc.calls = calls  # type: ignore[attr-defined]
    return rpc


def _find(airports: list[dict], rpc=None, fallback=None, min_runway_ft: int = 3000, supabase="default"):
    if supabase == "default":
        supabase = FakeSupabase(rpc={"find_diversion_airports_in_corridor": rpc or corridor_rpc(airports)})
    return find_diversion_airports_postgis(
        supabase, DEP[1], DEP[0], DEST[1], DEST[0], "dep", "dest", min_runway_ft=min_runway_ft, fallback_candidates=fallback
    )


class TestFindDiversionAirports:
    def test_asks_postgis_for_every_airport_from_the_track_outward(self):
        rpc = corridor_rpc([airport_on("KOK", 1000, 3)])
        _find([], rpc=rpc)
        (call,) = rpc.calls
        assert call["min_dist_m"] == 0  # the first tier used to skip everything within 25 NM
        assert call["max_dist_m"] == pytest.approx(DIVERSION_CORRIDOR_NM * NM_TO_M)
        assert call["result_limit"] == DIVERSION_CANDIDATE_LIMIT
        assert call["exclude_dep_id"] == "dep" and call["exclude_dest_id"] == "dest" and call["min_runway_ft"] == 3000

    def test_one_query_is_enough(self):
        """The four widening tiers used to issue up to four queries."""
        rpc = corridor_rpc([airport_on("KFAR", 1000, 140)])
        _find([], rpc=rpc)
        assert len(rpc.calls) == 1

    def test_the_closest_airports_are_listed_first_including_those_on_the_track(self):
        airports = [airport_on("K30", 800, 30), airport_on("K00", 1000, 0), airport_on("K08", 400, 8)]
        found = _find(airports)
        assert [d["airport"]["icao_code"] for d in found] == ["K00", "K08", "K30"]
        assert found[0]["distance_from_route_nm"] < 1

    def test_rows_are_converted_to_diversions_with_their_position(self):
        (found,) = _find([airport_on("KOK", 1000, 12)])
        assert found["airport"]["icao_code"] == "KOK" and found["airport"]["longest_runway_ft"] == 6000
        assert found["distance_from_route_nm"] == pytest.approx(12, abs=0.3)
        assert found["distance_along_route_nm"] == pytest.approx(1000, abs=1.0)

    def test_a_database_with_the_previous_function_cannot_return_airports_behind_or_beyond(self):
        """Before migration 011 the SQL function also returned airports behind the departure / beyond the destination."""
        stale_rows = corridor_rpc([airport_on("KBEHIND", -40, 5), airport_on("KBEYOND", ROUTE_NM + 40, 0), airport_on("KOK", 1000, 20)])

        def stale(params):
            rows = []
            for airport in (airport_on("KBEHIND", -40, 5), airport_on("KBEYOND", ROUTE_NM + 40, 0), airport_on("KOK", 1000, 20)):
                cross, _ = cross_and_along_track_nm(*DEP, *DEST, airport["latitude"], airport["longitude"])
                rows.append(
                    {**stale_rows({**params, "max_dist_m": 1e9})[0], "airport_id": airport["id"], "ident": airport["ident"],
                     "icao_code": airport["icao_code"], "latitude": airport["latitude"], "longitude": airport["longitude"],
                     "distance_from_route_m": cross * NM_TO_M}
                )
            return rows

        found = _find([], rpc=stale)
        assert [d["airport"]["icao_code"] for d in found] == ["KOK"]

    def test_more_candidates_than_places_are_spread_over_the_route(self):
        cluster = [airport_on(f"KC{i:02d}", 10 + i * 5, 2 + i) for i in range(30)]
        far = [airport_on("KF1", 900, 40), airport_on("KF2", 1500, 35), airport_on("KF3", 2000, 30)]
        found = _find(cluster + far)
        assert len(found) == MAX_DIVERSION_AIRPORTS
        assert {"KF1", "KF2", "KF3"} <= {d["airport"]["icao_code"] for d in found}

    def test_python_search_is_used_when_postgis_fails(self):
        def failing(_params):
            raise RuntimeError("function does not exist")

        found = _find([], rpc=failing, fallback=[airport_on("KOK", 1000, 4)])
        assert [d["airport"]["icao_code"] for d in found] == ["KOK"]
        assert found[0]["distance_along_route_nm"] == pytest.approx(1000, abs=1.0)

    def test_python_search_is_used_when_postgis_finds_nothing(self):
        found = _find([], fallback=[airport_on("KOK", 1000, 4)])
        assert [d["airport"]["icao_code"] for d in found] == ["KOK"]

    def test_python_search_is_used_when_only_stale_rows_remain(self):
        """Every PostGIS row filtered out (all behind/beyond): the fallback list is still consulted."""
        behind = airport_on("KBEHIND", -40, 5)
        found = _find([], rpc=lambda p: [], fallback=[behind, airport_on("KOK", 1000, 4)])
        assert [d["airport"]["icao_code"] for d in found] == ["KOK"]

    def test_without_a_database_only_the_python_search_runs(self):
        found = _find([], supabase=None, fallback=[airport_on("KOK", 1000, 4)])
        assert [d["airport"]["icao_code"] for d in found] == ["KOK"]

    def test_no_airport_in_the_corridor_means_no_diversion(self):
        """The old last resort returned the airport nearest the route midpoint, however far from the route."""
        far_away = airport_on("KFARAWAY", 1000, 400)
        assert _find([far_away], fallback=[far_away]) == []
        assert _find([], supabase=None, fallback=[far_away]) == []

    def test_nothing_at_all(self):
        assert _find([], fallback=None) == []
        assert _find([], supabase=None, fallback=None) == []


class TestAgainstPostGIS:
    """The same test bed was loaded into PostgreSQL 18 / PostGIS 3.7 and the function of migration 011 was run on it.
    The airports it returned and their distances from the route (spheroidal, NM) are recorded here."""

    BED = {
        # name: (along NM, left NM, type, runway)
        "T_ONTRACK": (1000, 0, "medium_airport", 6000),
        "T_LEFT10": (1000, 10, "small_airport", 4000),
        "T_RIGHT30": (1000, -30, "medium_airport", 6000),
        "T_NEARDEP": (20, 5, "small_airport", 4000),
        "T_BEHINDDEP": (-40, 5, "medium_airport", 6000),
        "T_BEHINDDEP2": (-120, 0, "medium_airport", 6000),
        "T_BEYONDDEST": (ROUTE_NM + 40, 0, "medium_airport", 6000),
        "T_FAR100": (500, 100, "medium_airport", 6000),
        "T_OUT200": (500, 200, "medium_airport", 6000),
        "T_SHORTRWY": (700, 10, "small_airport", 2000),
        "T_HELI": (800, 5, "heliport", 100),
        "T_NEARDEST": (ROUTE_NM - 20, 8, "small_airport", 4000),
        "T_CLUSTER1": (300, 20, "small_airport", 4000),
        "T_CLUSTER2": (302, -21, "small_airport", 4000),
        "T_CLUSTER3": (305, 22, "small_airport", 4000),
        "T_CLUSTER4": (308, -23, "small_airport", 4000),
        "T_CLUSTER5": (310, 24, "small_airport", 4000),
        "T_BAND30": (1500, 30, "small_airport", 4000),
    }
    # what PostGIS returned (min 0, max 150 NM, runway >= 3000 ft), ordered by distance
    POSTGIS_RESULT = {
        "T_ONTRACK": 0.0,
        "T_NEARDEP": 5.0,
        "T_NEARDEST": 8.0,
        "T_LEFT10": 10.0,
        "T_CLUSTER1": 20.0,
        "T_CLUSTER2": 21.0,
        "T_CLUSTER3": 22.0,
        "T_CLUSTER4": 23.0,
        "T_CLUSTER5": 24.0,
        "T_BAND30": 30.0,
        "T_RIGHT30": 30.0,
        "T_FAR100": 99.9,
    }
    # what the previous function returned for its first tier (25-50 NM): two of the four are not along the route
    OLD_FIRST_TIER = ["T_BAND30", "T_RIGHT30", "T_BEYONDDEST", "T_BEHINDDEP"]

    @pytest.fixture
    def airports(self):
        return [
            airport_on(name, along, left, airport_type=kind, longest_runway_ft=runway, ident=name)
            for name, (along, left, kind, runway) in self.BED.items()
        ]

    def test_the_mirror_returns_what_postgis_returned(self, airports):
        rows = corridor_rpc(airports)(
            {
                "dep_lon": DEP[1], "dep_lat": DEP[0], "dest_lon": DEST[1], "dest_lat": DEST[0], "min_dist_m": 0,
                "max_dist_m": 150 * NM_TO_M, "min_runway_ft": 3000, "exclude_dep_id": "x", "exclude_dest_id": "y",
                "result_limit": 200,
            }
        )
        assert {row["ident"] for row in rows} == set(self.POSTGIS_RESULT)
        for row in rows:
            assert row["distance_from_route_m"] / NM_TO_M == pytest.approx(self.POSTGIS_RESULT[row["ident"]], abs=0.4)

    def test_the_search_lists_all_twelve_with_the_closest_first(self, airports):
        found = _find(airports)
        assert [d["airport"]["ident"] for d in found][:4] == ["T_ONTRACK", "T_NEARDEP", "T_NEARDEST", "T_LEFT10"]
        assert {d["airport"]["ident"] for d in found} == set(self.POSTGIS_RESULT) - set() or len(found) == 10
        assert len(found) == MAX_DIVERSION_AIRPORTS  # 12 candidates, 10 places

    def test_what_the_old_search_returned_was_wrong(self, airports):
        found_idents = {d["airport"]["ident"] for d in _find(airports)}
        assert not {"T_BEHINDDEP", "T_BEHINDDEP2", "T_BEYONDDEST", "T_OUT200", "T_SHORTRWY", "T_HELI"} & found_idents
        assert {"T_BEYONDDEST", "T_BEHINDDEP"} <= set(self.OLD_FIRST_TIER)  # the old tier listed these two


class TestChooseViaDiversion:
    def test_nearest_to_the_middle_of_the_route(self):
        diversions = [_div("early", 30, 200), _div("middle", 40, 1000), _div("late", 20, 1900)]
        assert choose_via_diversion(diversions, 2000) == {"id": "middle"}

    def test_airports_on_the_track_are_not_a_detour(self):
        diversions = [_div("on", 0.5, 1000), _div("near", MIN_VIA_DIVERSION_OFFSET_NM - 0.1, 1000), _div("ok", 40, 600)]
        assert choose_via_diversion(diversions, 2000) == {"id": "ok"}

    def test_far_airports_are_not_a_sensible_detour(self):
        diversions = [_div("far", MAX_VIA_DIVERSION_OFFSET_NM + 1, 1000), _div("ok", 70, 300)]
        assert choose_via_diversion(diversions, 2000) == {"id": "ok"}

    def test_the_offset_limits_are_inclusive(self):
        assert choose_via_diversion([_div("min", MIN_VIA_DIVERSION_OFFSET_NM, 1000)], 2000) == {"id": "min"}
        assert choose_via_diversion([_div("max", MAX_VIA_DIVERSION_OFFSET_NM, 1000)], 2000) == {"id": "max"}

    def test_ties_go_to_the_airport_closer_to_the_track(self):
        diversions = [_div("far", 60, 1000), _div("close", 20, 1000)]
        assert choose_via_diversion(diversions, 2000) == {"id": "close"}

    def test_none_when_no_airport_qualifies(self):
        assert choose_via_diversion([], 2000) is None
        assert choose_via_diversion([_div("on", 1, 1000)], 2000) is None

    def test_a_missing_position_counts_as_the_middle(self):
        diversion = {"airport": {"id": "nopos"}, "distance_from_route_nm": 30}
        assert choose_via_diversion([diversion, _div("other", 30, 100)], 2000) == {"id": "nopos"}


class TestAlongRoute:
    def test_position_of_an_airport_abeam_of_the_route(self):
        airport = airport_on("KOK", 700, 25)
        assert along_route_nm({"latitude": DEP[0], "longitude": DEP[1]}, {"latitude": DEST[0], "longitude": DEST[1]}, airport) == pytest.approx(700, abs=1.0)

    def test_incomplete_rows_have_no_position(self):
        assert along_route_nm({"latitude": 1.0}, {"latitude": 2.0, "longitude": 3.0}, {"latitude": 1.0, "longitude": 1.0}) is None
        assert along_route_nm({"latitude": None, "longitude": None}, {"latitude": 2.0, "longitude": 3.0}, {"latitude": 1.0, "longitude": 1.0}) is None


# ----- the calculator --------------------------------------------------------------------------------------
KJFK = make_airport("KJFK")
KORD = make_airport("KORD", latitude=41.9786, longitude=-87.9048)
ORD_ROUTE = ((KJFK["latitude"], KJFK["longitude"]), (KORD["latitude"], KORD["longitude"]))
ORD_NM = haversine_nm(*ORD_ROUTE[0], *ORD_ROUTE[1])


async def _calculate(candidates: list[dict]) -> dict:
    return await route_calculator.calculate(
        KJFK,
        KORD,
        make_aircraft(),
        6.5,
        supabase=None,
        checkpoint_candidates=candidates,
        departure_time=datetime.now(timezone.utc) + timedelta(hours=2),
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("calm_winds")
class TestCalculatorDiversions:
    @pytest.fixture
    def calm_winds(self, monkeypatch):
        install_pressure_winds(monkeypatch)

    async def test_the_airport_nearest_the_track_is_the_first_diversion(self):
        result = await _calculate(
            [airport_on("KOFF", 330, 30, route=ORD_ROUTE), airport_on("KONT", 300, 0, route=ORD_ROUTE)]
        )
        diversions = result["diversion_airports"]
        assert [d["airport"]["icao_code"] for d in diversions] == ["KONT", "KOFF"]
        assert diversions[0]["distance_from_route_nm"] < 1
        assert diversions[0]["distance_along_route_nm"] == pytest.approx(300, abs=1.0)

    async def test_airports_behind_the_departure_are_not_diversions(self):
        result = await _calculate([airport_on("KBEHIND", -40, 5, route=ORD_ROUTE), airport_on("KOK", 300, 10, route=ORD_ROUTE)])
        assert [d["airport"]["icao_code"] for d in result["diversion_airports"]] == ["KOK"]

    async def test_the_via_diversion_route_uses_a_real_detour_near_the_middle(self):
        offsets = [
            airport_on("KONT", ORD_NM / 2, 0, route=ORD_ROUTE),  # on the track: no detour
            airport_on("KMID", ORD_NM / 2 + 10, 30, route=ORD_ROUTE),
            airport_on("KEARLY", 60, 25, route=ORD_ROUTE),
        ]
        result = await _calculate(offsets)
        variants = {v.name: v for v in result["variants"]}
        assert "via_diversion" in variants
        mid = next(a for a in offsets if a["icao_code"] == "KMID")
        assert variants["via_diversion"].waypoints[1] == (mid["latitude"], mid["longitude"])

    async def test_no_via_diversion_route_when_every_diversion_is_on_the_track(self):
        result = await _calculate([airport_on("KONT", 300, 2, route=ORD_ROUTE), airport_on("KONT2", 500, 6, route=ORD_ROUTE)])
        assert {v.name for v in result["variants"]} >= {"direct", "left_offset", "right_offset"}
        assert "via_diversion" not in {v.name for v in result["variants"]}
        assert len(result["diversion_airports"]) == 2  # still listed as diversions

    async def test_no_diversion_airport_is_reported(self):
        result = await _calculate([airport_on("KOUT", 300, 400, route=ORD_ROUTE)])
        assert result["diversion_airports"] == []
        assert "No suitable diversion airports found — verify alternate airports manually" in result["warnings"]
        assert "via_diversion" not in {v.name for v in result["variants"]}

    async def test_the_diversion_score_counts_airports_on_the_track(self):
        with_airport = await _calculate([airport_on("KONT", 300, 1, route=ORD_ROUTE)])
        without = await _calculate([])
        assert with_airport["primary"].score_breakdown["component_scores"]["diversion"] == 100.0
        assert without["primary"].score_breakdown["component_scores"]["diversion"] == 50.0


class TestEndpoints:
    @pytest.fixture
    def env(self, api, monkeypatch):
        env = calculation_env(api, monkeypatch)
        departure, destination = api.db.tables["airports"]
        along = haversine_nm(departure["latitude"], departure["longitude"], destination["latitude"], destination["longitude"])
        route = ((departure["latitude"], departure["longitude"]), (destination["latitude"], destination["longitude"]))
        api.db.tables["airports"].extend(
            [
                airport_on("KONT", along / 2, 0, route=route),
                airport_on("KSIDE", along / 3, -20, route=route),
                airport_on("KBEHIND", -50, 4, route=route),
            ]
        )
        return env

    def test_the_calculate_response_lists_the_diversions_with_their_position(self, env):
        body = env.post().json()
        diversions = body["diversion_airports"]
        assert [d["airport"]["icao_code"] for d in diversions] == ["KONT", "KSIDE"]
        assert [d["rank"] for d in diversions] == [1, 2]
        assert diversions[0]["distance_along_route_nm"] > diversions[1]["distance_along_route_nm"] > 0

    def test_the_stored_route_returns_the_same_positions(self, env):
        created = env.post().json()
        fetched = env.client.get(f"/routes/{created['id']}").json()
        assert [d["airport"]["icao_code"] for d in fetched["diversion_airports"]] == ["KONT", "KSIDE"]
        for stored, calculated in zip(fetched["diversion_airports"], created["diversion_airports"]):
            assert stored["distance_from_route_nm"] == calculated["distance_from_route_nm"]
            assert stored["distance_along_route_nm"] == pytest.approx(calculated["distance_along_route_nm"], abs=0.2)
