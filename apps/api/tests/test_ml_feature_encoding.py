"""ML feature encoding: local departure time, FAA-unknown flag and unknown-weather category."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.geo import timezones
from app.geo.timezones import conus_timezone_name, to_local_time
from app.services.delay_risk import predict_delay_risk
from app.services.ml_features import (
    UNKNOWN_CATEGORY_ORD,
    _category_ord,
    delay_label_from_features,
    extract_delay_features,
    extract_ete_features,
    refresh_delay_feature_categories,
)

EASTERN, CENTRAL, MOUNTAIN, PACIFIC, ARIZONA = (
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Phoenix",
)

# (ICAO, latitude, longitude, expected zone) - real airport coordinates
AIRPORTS = [
    ("KJFK", 40.6398, -73.7789, EASTERN),
    ("KBOS", 42.3643, -71.0052, EASTERN),
    ("KATL", 33.6367, -84.4281, EASTERN),
    ("KMIA", 25.7932, -80.2906, EASTERN),
    ("KDTW", 42.2124, -83.3534, EASTERN),
    ("KCLE", 41.4117, -81.8498, EASTERN),
    ("KIND", 39.7173, -86.2944, EASTERN),
    ("KSDF", 38.1744, -85.7360, EASTERN),
    ("KCHA", 35.0353, -85.2038, EASTERN),
    ("KTLH", 30.3965, -84.3503, EASTERN),
    ("KPNS", 30.4734, -87.1866, CENTRAL),
    ("KECP", 30.3571, -85.7954, CENTRAL),
    ("KORD", 41.9786, -87.9048, CENTRAL),
    ("KMKE", 42.9472, -87.8966, CENTRAL),
    ("KMSP", 44.8820, -93.2218, CENTRAL),
    ("KSTL", 38.7487, -90.3700, CENTRAL),
    ("KBNA", 36.1245, -86.6782, CENTRAL),
    ("KBHM", 33.5629, -86.7535, CENTRAL),
    ("KMSY", 29.9934, -90.2580, CENTRAL),
    ("KDFW", 32.8968, -97.0380, CENTRAL),
    ("KIAH", 29.9844, -95.3414, CENTRAL),
    ("KMAF", 31.9425, -102.2019, CENTRAL),
    ("KAMA", 35.2194, -101.7059, CENTRAL),
    ("KOKC", 35.3931, -97.6007, CENTRAL),
    ("KOMA", 41.3032, -95.8941, CENTRAL),
    ("KFAR", 46.9207, -96.8158, CENTRAL),
    ("KBIS", 46.7727, -100.7468, CENTRAL),
    ("KDEN", 39.8617, -104.6732, MOUNTAIN),
    ("KSLC", 40.7884, -111.9778, MOUNTAIN),
    ("KABQ", 35.0402, -106.6092, MOUNTAIN),
    ("KELP", 31.8072, -106.3779, MOUNTAIN),
    ("KBIL", 45.8077, -108.5430, MOUNTAIN),
    ("KBOI", 43.5644, -116.2228, MOUNTAIN),
    ("KGLD", 39.3706, -101.6990, MOUNTAIN),
    ("KRAP", 44.0453, -103.0574, MOUNTAIN),
    ("KMSO", 46.9163, -114.0906, MOUNTAIN),
    ("KPHX", 33.4343, -112.0116, ARIZONA),
    ("KFLG", 35.1385, -111.6707, ARIZONA),
    ("KTUS", 32.1161, -110.9410, ARIZONA),
    ("KLAX", 33.9425, -118.4081, PACIFIC),
    ("KSFO", 37.6188, -122.3750, PACIFIC),
    ("KSEA", 47.4502, -122.3088, PACIFIC),
    ("KPDX", 45.5887, -122.5975, PACIFIC),
    ("KLAS", 36.0840, -115.1537, PACIFIC),
    ("KRNO", 39.4991, -119.7681, PACIFIC),
    ("KGEG", 47.6199, -117.5339, PACIFIC),
    ("KSAN", 32.7336, -117.1897, PACIFIC),
]


class TestTimezoneLookup:
    @pytest.mark.parametrize(("icao", "lat", "lon", "expected"), AIRPORTS, ids=[a[0] for a in AIRPORTS])
    def test_airport_zone(self, icao, lat, lon, expected):
        assert conus_timezone_name(lat, lon) == expected

    @pytest.mark.parametrize(("lat", "lon"), [(21.32, -157.92), (61.17, -150.0), (51.5, -0.45), (0.0, 0.0)])
    def test_points_outside_the_contiguous_us_have_no_zone(self, lat, lon):
        assert conus_timezone_name(lat, lon) is None


class TestToLocalTime:
    SUMMER = datetime(2026, 7, 15, 18, 0, tzinfo=timezone.utc)
    WINTER = datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc)

    @pytest.mark.parametrize(
        ("lat", "lon", "summer_hour", "winter_hour"),
        [
            (40.6398, -73.7789, 14, 13),  # New York: EDT / EST
            (41.9786, -87.9048, 13, 12),  # Chicago
            (39.8617, -104.6732, 12, 11),  # Denver
            (33.9425, -118.4081, 11, 10),  # Los Angeles
            (33.4343, -112.0116, 11, 11),  # Phoenix keeps MST all year
        ],
    )
    def test_daylight_saving_is_applied(self, lat, lon, summer_hour, winter_hour):
        assert to_local_time(self.SUMMER, lat, lon).hour == summer_hour
        assert to_local_time(self.WINTER, lat, lon).hour == winter_hour

    def test_the_date_follows_the_local_zone(self):
        utc = datetime(2026, 11, 15, 2, 0, tzinfo=timezone.utc)  # Sunday 02:00 UTC
        local = to_local_time(utc, 33.9425, -118.4081)  # Los Angeles: Saturday 18:00 PST
        assert (local.hour, local.weekday(), local.day) == (18, 5, 14)

    def test_unknown_location_keeps_utc(self):
        assert to_local_time(self.SUMMER, None, None) == self.SUMMER
        assert to_local_time(self.SUMMER, 40.0, None).hour == 18

    def test_naive_datetimes_are_treated_as_utc(self):
        assert to_local_time(datetime(2026, 7, 15, 18, 0), 40.6398, -73.7789).hour == 14

    def test_outside_the_us_uses_the_longitude_offset(self):
        assert to_local_time(self.SUMMER, 33.0, 15.0).hour == 19  # 15 deg east = UTC+1

    def test_missing_tz_database_falls_back_to_the_longitude_offset(self, monkeypatch):
        def missing(_name):
            raise timezones.ZoneInfoNotFoundError("no tzdata")

        monkeypatch.setattr(timezones, "ZoneInfo", missing)
        assert to_local_time(self.WINTER, 41.9786, -87.9048).hour == 12  # round(-87.9 / 15) = -6


def _request(departure_time="2026-07-15T18:00:00+00:00", **extra):
    return {"departure_time": departure_time, "_aircraft_cruise_speed_kt": 120, "_cruise_altitude_ft": 8500, **extra}


def _route(**extra):
    return {
        "primary_distance_nm": 2145,
        "primary_path": [{"lat": 33.9425, "lon": -118.4081}, {"lat": 40.6398, "lon": -73.7789}],
        "departure_weather": {"metar": {}, "faa_status": {}},
        "destination_weather": {"metar": {}, "faa_status": {}},
        "weather_checkpoints": [],
        **extra,
    }


class TestDepartureHourIsLocal:
    def test_delay_features_use_the_departure_airports_local_time(self):
        features = extract_delay_features(_request(), _route(), [], [])
        assert features["departure_hour_local"] == 11  # 18:00 UTC is 11:00 PDT in Los Angeles (used to be 18)
        assert features["departure_month"] == 7

    def test_ete_features_use_the_same_local_hour(self):
        assert extract_ete_features(_request(), _route(), [])["departure_hour_local"] == 11

    def test_weekday_and_month_follow_local_time_too(self):
        features = extract_delay_features(_request("2026-11-15T02:00:00+00:00"), _route(), [], [])
        assert (features["departure_hour_local"], features["departure_day_of_week"], features["departure_month"]) == (18, 5, 11)

    def test_east_coast_departure(self):
        path = [{"lat": 40.6398, "lon": -73.7789}, {"lat": 33.9425, "lon": -118.4081}]
        assert extract_delay_features(_request(), _route(primary_path=path), [], [])["departure_hour_local"] == 14

    def test_first_leg_is_used_when_the_path_is_missing(self):
        segments = [
            {"segment_index": 1, "start_lat": 39.0, "start_lon": -95.0},
            {"segment_index": 0, "start_lat": 40.6398, "start_lon": -73.7789},
        ]
        features = extract_delay_features(_request(), _route(primary_path=None), segments, [])
        assert features["departure_hour_local"] == 14

    def test_without_any_coordinates_the_utc_hour_is_kept(self):
        features = extract_delay_features(_request(), _route(primary_path=None), [], [])
        assert features["departure_hour_local"] == 18

    def test_stored_timestamps_with_offsets_and_fractions_are_parsed(self):
        features = extract_delay_features(_request("2026-07-15T11:00:00.123456-07:00"), _route(), [], [])
        assert features["departure_hour_local"] == 11


class TestFaaUnknownFlag:
    @staticmethod
    def _flags(faa_status):
        route = _route(departure_weather={"metar": {}, "faa_status": faa_status})
        features = extract_delay_features(_request(), route, [], [])
        return features["departure_faa_unknown"]

    def test_absent_faa_data_is_unknown(self):
        assert self._flags({}) == 1  # used to be 0
        assert self._flags(None) == 1

    def test_missing_weather_block_is_unknown(self):
        features = extract_delay_features(_request(), _route(departure_weather=None), [], [])
        assert features["departure_faa_unknown"] == 1

    def test_unknown_status_and_parse_failures_are_unknown(self):
        assert self._flags({"status": "unknown", "parse_success": False}) == 1
        assert self._flags({"status": "normal", "parse_success": False}) == 1
        assert self._flags({"status": None, "parse_success": True}) == 1

    def test_parsed_status_is_known(self):
        assert self._flags({"status": "normal", "parse_success": True, "delay_minutes": 0}) == 0
        assert self._flags({"status": "delay", "delay_minutes": 25}) == 0

    def test_label_does_not_claim_faa_data_when_it_is_absent(self):
        features = extract_delay_features(_request(), _route(), [], [])
        assert "FAA NAS" not in delay_label_from_features(features)["data_basis"]


class TestUnknownWeatherIsNotVfr:
    def test_category_ordinals(self):
        assert [_category_ord(c) for c in ("VFR", "MVFR", "IFR", "LIFR")] == [0, 1, 2, 3]
        assert [_category_ord(c) for c in (None, "", "UNKNOWN", "N/A")] == [UNKNOWN_CATEGORY_ORD] * 4
        assert _category_ord("vfr") == 0  # case-insensitive

    def test_missing_metar_is_not_encoded_as_vfr(self):
        features = extract_delay_features(_request(), _route(), [], [])
        assert features["departure_flight_category_ord"] == UNKNOWN_CATEGORY_ORD
        assert features["destination_flight_category_ord"] == UNKNOWN_CATEGORY_ORD

    def test_real_vfr_is_still_zero(self):
        route = _route(departure_weather={"metar": {"flight_category": "VFR"}, "faa_status": {}})
        assert extract_delay_features(_request(), route, [], [])["departure_flight_category_ord"] == 0

    def test_worst_enroute_ignores_unknown_checkpoints_but_reports_no_data(self):
        def worst(*categories):
            route = _route(weather_checkpoints=[{"flight_category": c} for c in categories])
            return extract_delay_features(_request(), route, [], [])["worst_enroute_flight_category_ord"]

        assert worst() == UNKNOWN_CATEGORY_ORD
        assert worst(None, "UNKNOWN") == UNKNOWN_CATEGORY_ORD
        assert worst("VFR", None) == 0
        assert worst("MVFR", "UNKNOWN", "IFR") == 2

    def test_labels_do_not_treat_unknown_weather_as_ifr_or_vfr_evidence(self):
        features = extract_delay_features(_request(), _route(), [], [])
        label = delay_label_from_features(features)
        assert "ifr_dep_dest_or_checkpoint" not in str(label["label_source"])
        assert "METAR/TAF" not in label["data_basis"]

    def test_rules_baseline_does_not_index_the_category_list_from_the_end(self):
        # ord -1 used to select ["VFR", "MVFR", "IFR", "LIFR"][-1] == "LIFR" and add IFR risk
        unknown = predict_delay_risk({"departure_flight_category_ord": -1, "destination_flight_category_ord": -1})
        lifr = predict_delay_risk({"departure_flight_category_ord": 3, "destination_flight_category_ord": 0})
        assert unknown["confidence"] == 0.7  # no IFR contribution
        assert lifr["confidence"] < unknown["confidence"]

    def test_legacy_rows_are_corrected_on_refresh(self):
        legacy = {
            "departure_flight_category": None,
            "departure_flight_category_ord": 0,
            "destination_flight_category": "IFR",
            "destination_flight_category_ord": 0,
            "departure_faa_status": None,
            "departure_faa_unknown": 0,
            "destination_faa_status": "normal",
            "destination_faa_unknown": 0,
        }
        fixed = refresh_delay_feature_categories(legacy)
        assert fixed["departure_flight_category_ord"] == UNKNOWN_CATEGORY_ORD
        assert fixed["destination_flight_category_ord"] == 2
        assert fixed["departure_faa_unknown"] == 1
        assert fixed["destination_faa_unknown"] == 0

    def test_refresh_never_downgrades_an_unknown_flag(self):
        fixed = refresh_delay_feature_categories({"departure_faa_status": "normal", "departure_faa_unknown": 1})
        assert fixed["departure_faa_unknown"] == 1
