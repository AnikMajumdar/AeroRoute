"""Offset route candidates are labelled by their side of the track, whatever the direction of travel."""

from __future__ import annotations

import pytest

from app.geo.utils import cross_track_distance_nm, haversine_nm, initial_bearing_deg
from app.services.ml_features import _candidate_type_ord
from app.services.route_calculator import OFFSET_NM, _build_route_variants

KJFK = (40.6398, -73.7789)
KLAX = (33.9425, -118.4081)
KSEA = (47.4502, -122.3088)
KPDX = (45.5887, -122.5975)

ROUTES = {
    "westbound JFK-LAX": (KJFK, KLAX),
    "eastbound LAX-JFK": (KLAX, KJFK),
    "southbound SEA-LAX": (KSEA, KLAX),
    "northbound LAX-SEA": (KLAX, KSEA),
    "short southbound SEA-PDX": (KSEA, KPDX),
}


def _variants(dep, dest):
    return dict(_build_route_variants(dep[0], dep[1], dest[0], dest[1]))


def _side_of_track(dep, dest, point) -> float:
    """Signed angle (deg) from the track to the point as seen from the departure: negative = left, positive = right."""
    track = initial_bearing_deg(dep[0], dep[1], dest[0], dest[1])
    to_point = initial_bearing_deg(dep[0], dep[1], point[0], point[1])
    return (to_point - track + 540) % 360 - 180


@pytest.mark.parametrize("dep,dest", ROUTES.values(), ids=ROUTES.keys())
class TestOffsetCandidates:
    def test_candidate_names(self, dep, dest):
        names = [name for name, _ in _build_route_variants(dep[0], dep[1], dest[0], dest[1])]
        assert names == ["direct", "left_offset", "right_offset"]

    def test_left_offset_lies_left_of_the_track_and_right_offset_right(self, dep, dest):
        variants = _variants(dep, dest)
        left_mid, right_mid = variants["left_offset"][1], variants["right_offset"][1]
        assert _side_of_track(dep, dest, left_mid) < 0
        assert _side_of_track(dep, dest, right_mid) > 0

    def test_offsets_are_about_35nm_from_the_direct_track(self, dep, dest):
        variants = _variants(dep, dest)
        for name in ("left_offset", "right_offset"):
            mid = variants[name][1]
            cross_track = cross_track_distance_nm(dep[0], dep[1], dest[0], dest[1], mid[0], mid[1])
            # the offset is taken perpendicular to the initial bearing, so long routes deviate by a few NM
            assert OFFSET_NM - 5 <= cross_track <= OFFSET_NM + 1, (name, cross_track)

    def test_offsets_are_on_opposite_sides_of_the_midpoint(self, dep, dest):
        variants = _variants(dep, dest)
        left_mid, right_mid = variants["left_offset"][1], variants["right_offset"][1]
        assert haversine_nm(left_mid[0], left_mid[1], right_mid[0], right_mid[1]) == pytest.approx(2 * OFFSET_NM, rel=0.1)

    def test_every_candidate_starts_and_ends_at_the_airports(self, dep, dest):
        for name, waypoints in _build_route_variants(dep[0], dep[1], dest[0], dest[1]):
            assert waypoints[0] == dep and waypoints[-1] == dest, name


class TestLabelsAreNotCompassBased:
    def test_westbound_left_is_south_of_the_direct_track(self):
        # The old "north_offset" label sat on the LEFT of the track, i.e. south of a westbound route.
        variants = _variants(KJFK, KLAX)
        assert variants["left_offset"][1][0] < variants["right_offset"][1][0]

    def test_eastbound_left_is_north_of_the_direct_track(self):
        variants = _variants(KLAX, KJFK)
        assert variants["left_offset"][1][0] > variants["right_offset"][1][0]


class TestOptionalCandidates:
    def test_diversion_and_weather_candidates_are_appended(self):
        extras = _build_route_variants(
            KJFK[0],
            KJFK[1],
            KLAX[0],
            KLAX[1],
            diversion_airport={"latitude": 39.0, "longitude": -95.0},
            weather_checkpoint={"latitude": 38.0, "longitude": -100.0},
        )
        assert [name for name, _ in extras] == [
            "direct",
            "left_offset",
            "right_offset",
            "via_diversion",
            "via_weather_checkpoint",
        ]


class TestMlCandidateOrdinals:
    def test_new_and_legacy_names_share_ordinals(self):
        assert _candidate_type_ord("direct") == 0
        assert _candidate_type_ord("left_offset") == _candidate_type_ord("north_offset") == 1
        assert _candidate_type_ord("right_offset") == _candidate_type_ord("south_offset") == 2
        assert _candidate_type_ord("via_diversion") == 3
        assert _candidate_type_ord("via_weather_checkpoint") == 4

    def test_unknown_name_defaults_to_direct(self):
        assert _candidate_type_ord("something_else") == 0
