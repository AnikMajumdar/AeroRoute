"""Missing weather / FAA data must not be scored as good conditions.

Unknown flight categories used to count as VFR, an unknown FAA status as "no delays", an unknown checkpoint
as 10 penalty points, and the first checkpoint was presented as the "best weather" route when nothing was known.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.geo.utils import destination_point, haversine_nm, initial_bearing_deg
from app.services.aviation_weather import aviation_weather_client
from app.services.faa_nas import faa_nas_client
from app.services.live_data.live_data_scoring import apply_live_penalties_to_score_breakdown
from app.services.ml_features import _score_component
from app.services.route_calculator import (
    _build_route_variants,
    data_gap_warnings,
    faa_status_known,
    route_calculator,
)
from app.services.route_scoring import (
    WEIGHTS,
    ScoringInput,
    calculate_normalized_score,
    combine_components,
    is_known_flight_category,
    scoring_data_warnings,
)
from app.services.weather_checkpoints import best_weather_checkpoint, fetch_checkpoint_weather
from tests.fakes import calculation_env, install_pressure_winds, make_aircraft, make_airport


def _input(**overrides) -> ScoringInput:
    values = {
        "ete_minutes": 120,
        "fuel_burn_gal": 50,
        "baseline_ete_minutes": 120,
        "baseline_fuel_gal": 50,
        "diversion_count": 3,
        "min_diversion_runway_ft": 5000,
    }
    values.update(overrides)
    return ScoringInput(**values)


def _score(preference: str = "balanced", **overrides) -> dict:
    return calculate_normalized_score(_input(**overrides), preference)


class TestFlightCategoryKnowledge:
    @pytest.mark.parametrize("category", ["VFR", "MVFR", "IFR", "LIFR", "vfr", " ifr "])
    def test_real_categories_are_known(self, category):
        assert is_known_flight_category(category)

    @pytest.mark.parametrize("category", [None, "", "  ", "UNKNOWN", "N/A", "VFR+"])
    def test_everything_else_is_a_missing_observation(self, category):
        assert not is_known_flight_category(category)


class TestUnknownWeather:
    def test_no_observation_leaves_the_weather_component_out(self):
        result = _score()
        assert result["component_scores"]["weather"] is None
        assert "weather" in result["unavailable_components"]
        assert "weather" not in result["effective_weights"]

    def test_unknown_is_not_scored_like_vfr(self):
        unknown = _score()["component_scores"]["weather"]
        vfr = _score(departure_flight_category="VFR", destination_flight_category="VFR")["component_scores"]["weather"]
        assert unknown is None and vfr == 100.0

    @pytest.mark.parametrize("category", [None, "", "UNKNOWN", "garbage"])
    def test_any_unknown_value_is_treated_the_same(self, category):
        result = _score(departure_flight_category=category, destination_flight_category=category)
        assert result["component_scores"]["weather"] is None

    def test_a_known_adverse_airport_is_never_dropped_because_the_other_is_unknown(self):
        result = _score(departure_flight_category="IFR")
        assert result["component_scores"]["weather"] == 60.0
        assert "weather" not in result["unavailable_components"]

    def test_categories_are_case_insensitive(self):
        assert _score(departure_flight_category="mvfr", destination_flight_category="lifr")["component_scores"]["weather"] == 20.0

    def test_checkpoint_weather_alone_makes_the_component_available(self):
        result = _score(checkpoint_weather_penalty=15.0)
        assert result["component_scores"]["weather"] == 85.0

    def test_no_checkpoint_weather_is_not_the_same_as_a_zero_penalty(self):
        assert _score(checkpoint_weather_penalty=None)["component_scores"]["weather"] is None
        assert _score(checkpoint_weather_penalty=0.0)["component_scores"]["weather"] == 100.0

    def test_known_weather_is_scored_as_before(self):
        result = _score(departure_flight_category="IFR", destination_flight_category="MVFR", checkpoint_weather_penalty=15.0)
        assert result["component_scores"]["weather"] == 25.0  # 100 - 40 - 20 - 15


class TestUnknownDelay:
    def test_unknown_status_leaves_the_delay_component_out(self):
        result = _score(delay_known=False)
        assert result["component_scores"]["delay"] is None
        assert "delay" in result["unavailable_components"]

    def test_known_status_is_scored_as_before(self):
        result = _score(departure_delay_min=10, destination_delay_min=20, departure_closed=True)
        assert result["component_scores"]["delay"] == 25.0  # 100 - (30 + 120) * 0.5
        assert "delay" not in result["unavailable_components"]

    def test_a_known_clean_status_is_perfect(self):
        assert _score()["component_scores"]["delay"] == 100.0

    def test_ground_stop_counts_when_known(self):
        assert _score(destination_ground_stop=True)["component_scores"]["delay"] == 70.0


class TestComposite:
    def test_weights_are_renormalised_over_the_available_components(self):
        result = _score(ete_minutes=150, fuel_burn_gal=55, diversion_count=0, delay_known=False)
        assert result["component_scores"] == {"time": 80.0, "fuel": 92.0, "weather": None, "delay": None, "diversion": 50.0}
        assert result["unavailable_components"] == ["weather", "delay"]
        total = 0.25 + 0.2 + 0.15
        assert result["effective_weights"] == pytest.approx(
            {"time": 0.25 / total, "fuel": 0.2 / total, "diversion": 0.15 / total}, abs=1e-4
        )
        assert sum(result["effective_weights"].values()) == pytest.approx(1.0, abs=1e-3)
        assert result["composite_score"] == pytest.approx((80 * 0.25 + 92 * 0.2 + 50 * 0.15) / total, abs=0.1)

    def test_unknown_weather_and_delay_do_not_inflate_the_composite(self):
        """With a poor route the old code padded the score with two perfect-looking components."""
        poor = {"ete_minutes": 180, "fuel_burn_gal": 70, "diversion_count": 0}  # time 60, fuel 68, diversion 50
        old_style = _score(departure_flight_category="VFR", destination_flight_category="VFR", **poor)  # weather/delay 100
        new_style = _score(delay_known=False, **poor)
        assert old_style["composite_score"] == pytest.approx(0.25 * 60 + 0.2 * 68 + 0.2 * 100 + 0.2 * 100 + 0.15 * 50, abs=0.1)
        assert new_style["composite_score"] < old_style["composite_score"]
        assert new_style["composite_score"] == pytest.approx((60 * 0.25 + 68 * 0.2 + 50 * 0.15) / 0.6, abs=0.1)

    def test_fully_known_input_keeps_the_original_weights_and_score(self):
        result = _score(
            ete_minutes=150,
            fuel_burn_gal=55,
            departure_delay_min=10,
            destination_delay_min=20,
            departure_closed=True,
            departure_flight_category="IFR",
            destination_flight_category="MVFR",
            checkpoint_weather_penalty=15.0,
        )
        assert result["component_scores"] == {"time": 80.0, "fuel": 92.0, "weather": 25.0, "delay": 25.0, "diversion": 100.0}
        assert result["unavailable_components"] == []
        assert result["effective_weights"] == WEIGHTS["balanced"]
        assert result["composite_score"] == pytest.approx(0.25 * 80 + 0.2 * 92 + 0.2 * 25 + 0.2 * 25 + 0.15 * 100, abs=0.1)

    def test_a_known_adverse_signal_lowers_the_composite(self):
        clean = _score(departure_flight_category="VFR", destination_flight_category="VFR")
        stormy = _score(departure_flight_category="LIFR", destination_flight_category="IFR")
        assert stormy["composite_score"] < clean["composite_score"]

    @pytest.mark.parametrize("preference", ["balanced", "fastest", "fuel_saver", "weather_cautious"])
    def test_every_preference_scores_without_weather_and_delay(self, preference):
        result = _score(preference, delay_known=False)
        assert 0 <= result["composite_score"] <= 100
        assert result["preference"] == preference
        assert set(result["effective_weights"]) == {"time", "fuel", "diversion"}
        assert sum(result["effective_weights"].values()) == pytest.approx(1.0, abs=1e-3)

    def test_the_legacy_breakdown_ignores_unknown_inputs(self):
        legacy = _score(delay_known=False)["legacy"]
        assert legacy["weather_penalty"] == 0 and legacy["delay_penalty"] == 0

    def test_combine_components_handles_a_single_component(self):
        composite, weights = combine_components({"time": 80.0, "weather": None}, {"time": 0.25, "weather": 0.2})
        assert composite == 80.0 and weights == {"time": 1.0}

    def test_combine_components_with_nothing_scoreable(self):
        assert combine_components({"weather": None}, {"weather": 0.2}) == (0.0, {})
        assert combine_components({"time": 50.0}, {}) == (0.0, {})


class TestScoringDataWarnings:
    def test_no_warning_when_everything_is_scored(self):
        assert scoring_data_warnings(_score(departure_flight_category="VFR")) == []

    def test_names_the_missing_components_and_what_the_score_is_based_on(self):
        (warning,) = scoring_data_warnings(_score(delay_known=False))
        assert warning == (
            "Weather and delay data unavailable — not part of the route score, which is based on "
            "time, fuel and diversion only"
        )

    def test_a_single_missing_component(self):
        (warning,) = scoring_data_warnings(_score(delay_known=False, departure_flight_category="VFR"))
        assert warning.startswith("Delay data unavailable")
        assert "time, fuel, weather and diversion only" in warning

    def test_weather_cautious_says_it_had_nothing_to_act_on(self):
        warnings = scoring_data_warnings(_score("weather_cautious", delay_known=False))
        assert len(warnings) == 2
        assert "weather-cautious preference had no weather data" in warnings[1]

    def test_other_preferences_do_not_get_the_extra_line(self):
        assert len(scoring_data_warnings(_score("fastest", delay_known=False))) == 1


class TestLivePenalties:
    PENALTIES = {"weather_penalty": 35.0, "delay_penalty": 25.0, "tfr_reroute_penalty": 0.0}

    def test_penalties_are_subtracted_from_known_components(self):
        base = _score(departure_flight_category="VFR", destination_flight_category="VFR")
        updated = apply_live_penalties_to_score_breakdown(base, self.PENALTIES)
        assert updated["component_scores"]["weather"] == 65.0
        assert updated["component_scores"]["delay"] == 75.0
        expected = 0.25 * 100 + 0.2 * 100 + 0.2 * 65 + 0.2 * 75 + 0.15 * 100
        assert updated["composite_score"] == pytest.approx(expected, abs=0.1)
        assert updated["total"] == updated["composite_score"]
        assert updated["unavailable_components"] == []
        assert updated["live_data_penalties"] == self.PENALTIES

    def test_unavailable_components_stay_out_without_a_penalty(self):
        base = _score(delay_known=False)
        updated = apply_live_penalties_to_score_breakdown(base, {"weather_penalty": 0.0, "delay_penalty": 0.0})
        assert updated["component_scores"]["weather"] is None and updated["component_scores"]["delay"] is None
        assert updated["unavailable_components"] == ["weather", "delay"]
        assert updated["composite_score"] == base["composite_score"]
        assert updated["effective_weights"] == base["effective_weights"]

    def test_a_real_adverse_signal_makes_an_unavailable_component_count(self):
        base = _score(delay_known=False)
        updated = apply_live_penalties_to_score_breakdown(base, self.PENALTIES)
        assert updated["component_scores"]["weather"] == 65.0  # 100 - 35, not dropped
        assert updated["component_scores"]["delay"] == 75.0
        assert updated["unavailable_components"] == []
        # time, fuel and diversion are 100: 0.25 * 100 + 0.2 * 100 + 0.2 * 65 + 0.2 * 75 + 0.15 * 100
        assert updated["composite_score"] == 88.0
        assert updated["effective_weights"] == WEIGHTS["balanced"]

    def test_only_the_penalised_component_becomes_available(self):
        base = _score(delay_known=False)
        updated = apply_live_penalties_to_score_breakdown(base, {"weather_penalty": 18.0, "delay_penalty": 0.0})
        assert updated["component_scores"]["weather"] == 82.0
        assert updated["component_scores"]["delay"] is None
        assert updated["unavailable_components"] == ["delay"]

    def test_penalties_cannot_push_a_component_below_zero(self):
        base = _score(departure_flight_category="LIFR", destination_flight_category="LIFR")
        updated = apply_live_penalties_to_score_breakdown(base, {"weather_penalty": 90.0, "delay_penalty": 0.0})
        assert updated["component_scores"]["weather"] == 0.0

    def test_the_input_breakdown_is_not_modified(self):
        base = _score(delay_known=False)
        before = repr(base)
        apply_live_penalties_to_score_breakdown(base, self.PENALTIES)
        assert repr(base) == before


class TestCheckpointWeather:
    @staticmethod
    def _checkpoint(icao: str, category: str | None) -> dict:
        return {"icao": icao, "flight_category": category}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("category", "penalty"), [("VFR", 0), ("MVFR", 15), ("IFR", 35), ("LIFR", 55), (None, None)])
    async def test_penalty_per_category(self, monkeypatch, category, penalty):
        async def metar(_icao):
            return {"flight_category": category} if category else None

        monkeypatch.setattr(aviation_weather_client, "get_metar", metar)
        results = await fetch_checkpoint_weather([make_airport("KAAA")])
        assert results[0]["weather_penalty"] == penalty
        assert results[0]["flight_category"] == (category or "UNKNOWN")

    def test_the_best_known_category_wins(self):
        checkpoints = [self._checkpoint("KAAA", "IFR"), self._checkpoint("KBBB", "VFR"), self._checkpoint("KCCC", "MVFR")]
        assert best_weather_checkpoint(checkpoints)["icao"] == "KBBB"

    def test_ties_go_to_the_first_checkpoint_along_the_route(self):
        checkpoints = [self._checkpoint("KAAA", "MVFR"), self._checkpoint("KBBB", "MVFR")]
        assert best_weather_checkpoint(checkpoints)["icao"] == "KAAA"

    def test_unknown_checkpoints_are_skipped_when_others_are_known(self):
        checkpoints = [self._checkpoint("KAAA", "UNKNOWN"), self._checkpoint("KBBB", "IFR")]
        assert best_weather_checkpoint(checkpoints)["icao"] == "KBBB"

    def test_no_known_weather_means_no_best_checkpoint(self):
        """It used to return the first checkpoint, presenting an arbitrary airport as the best-weather choice."""
        assert best_weather_checkpoint([self._checkpoint("KAAA", "UNKNOWN"), self._checkpoint("KBBB", None)]) is None

    def test_no_checkpoints(self):
        assert best_weather_checkpoint([]) is None

    def test_unrecognised_categories_are_not_ranked(self):
        assert best_weather_checkpoint([self._checkpoint("KAAA", "N/A")]) is None

    def test_no_weather_checkpoint_variant_without_a_checkpoint(self):
        names = [name for name, _ in _build_route_variants(40.0, -74.0, 41.0, -88.0, weather_checkpoint=None)]
        assert "via_weather_checkpoint" not in names

    def test_a_weather_checkpoint_variant_goes_through_the_checkpoint(self):
        variants = dict(_build_route_variants(40.0, -74.0, 41.0, -88.0, weather_checkpoint={"latitude": 40.5, "longitude": -80.0}))
        assert variants["via_weather_checkpoint"][1] == (40.5, -80.0)


class TestFaaStatusKnown:
    @pytest.mark.parametrize("status", [None, {}, {"status": "unknown"}, {"status": "UNKNOWN"}, {"status": None}])
    def test_missing_or_unknown(self, status):
        assert not faa_status_known(status)

    @pytest.mark.parametrize("status", ["normal", "delayed", "closed", "ground_stop"])
    def test_real_statuses(self, status):
        assert faa_status_known({"status": status})


class TestDataGapWarnings:
    SCORED = {"unavailable_components": []}

    def test_partial_weather(self):
        (warning,) = data_gap_warnings(self.SCORED, ["destination KORD"], [])
        assert warning == "Weather unavailable for destination KORD — not included in the weather score"

    def test_both_airports(self):
        (warning,) = data_gap_warnings(self.SCORED, ["departure KJFK", "destination KORD"], [])
        assert "departure KJFK and destination KORD" in warning

    def test_partial_faa_status(self):
        (warning,) = data_gap_warnings(self.SCORED, [], ["departure KJFK"])
        assert warning == "FAA status unavailable for departure KJFK — not included in the delay score"

    def test_some_checkpoints_without_weather(self):
        (warning,) = data_gap_warnings(self.SCORED, [], [], checkpoints_without_weather=1, checkpoint_count=3)
        assert "1 of 3 en-route checkpoints" in warning

    def test_all_or_no_checkpoints_without_weather_is_not_a_partial_gap(self):
        assert data_gap_warnings(self.SCORED, [], [], checkpoints_without_weather=2, checkpoint_count=2) == []
        assert data_gap_warnings(self.SCORED, [], [], checkpoints_without_weather=0, checkpoint_count=2) == []
        assert data_gap_warnings(self.SCORED, [], [], checkpoints_without_weather=0, checkpoint_count=0) == []

    def test_a_component_without_any_data_is_reported_by_the_scoring_warning_instead(self):
        breakdown = {"unavailable_components": ["weather", "delay"]}
        assert data_gap_warnings(breakdown, ["departure KJFK", "destination KORD"], ["departure KJFK"], 2, 3) == []


class TestMlFeatureHelper:
    def test_null_component_scores_are_neutral(self):
        breakdown = _score(delay_known=False)
        assert _score_component(breakdown, "weather") == 50.0
        assert _score_component(breakdown, "delay") == 50.0
        assert _score_component(breakdown, "time") == 100.0

    def test_missing_breakdown_is_neutral(self):
        assert _score_component(None, "weather") == 50.0
        assert _score_component({}, "weather") == 50.0


# ----- the calculator, end to end -------------------------------------------------------------------------
KJFK = make_airport("KJFK")
KORD = make_airport("KORD", latitude=41.9786, longitude=-87.9048)


def _checkpoints() -> list[dict]:
    distance = haversine_nm(KJFK["latitude"], KJFK["longitude"], KORD["latitude"], KORD["longitude"])
    bearing = initial_bearing_deg(KJFK["latitude"], KJFK["longitude"], KORD["latitude"], KORD["longitude"])
    airports = []
    for icao, share in (("KAAA", 0.3), ("KBBB", 0.7)):
        lat, lon = destination_point(KJFK["latitude"], KJFK["longitude"], bearing, distance * share)
        airports.append(make_airport(icao, latitude=lat, longitude=lon))
    return airports


async def _calculate(preference: str = "balanced") -> dict:
    return await route_calculator.calculate(
        KJFK,
        KORD,
        make_aircraft(),
        6.5,
        supabase=None,
        checkpoint_candidates=_checkpoints(),
        departure_time=datetime.now(timezone.utc) + timedelta(hours=2),
        route_preference=preference,
    )


def _connect_providers(monkeypatch, categories: dict[str, str | None], faa: dict[str, str] | None = None) -> None:
    async def metar(icao):
        category = categories.get(icao)
        return {"flight_category": category} if category else None

    async def status(icao, supabase=None):
        value = (faa or {}).get(icao, "normal")
        return {"status": value, "delay_minutes": 0, "is_closed": value == "closed", "ground_stop": False}

    monkeypatch.setattr(aviation_weather_client, "get_metar", metar)
    monkeypatch.setattr(faa_nas_client, "get_airport_status", status)


@pytest.fixture
def calm_winds(monkeypatch):
    install_pressure_winds(monkeypatch)


@pytest.mark.asyncio
@pytest.mark.usefixtures("calm_winds")
class TestCalculatorWithoutProviders:
    """The current build: no METAR and no FAA status."""

    async def test_weather_and_delay_are_not_scored(self):
        result = await _calculate()
        breakdown = result["primary"].score_breakdown
        assert breakdown["component_scores"]["weather"] is None
        assert breakdown["component_scores"]["delay"] is None
        assert breakdown["unavailable_components"] == ["weather", "delay"]
        assert set(breakdown["effective_weights"]) == {"time", "fuel", "diversion"}

    async def test_the_route_score_says_what_it_is_based_on(self):
        result = await _calculate()
        assert (
            "Weather and delay data unavailable — not part of the route score, which is based on "
            "time, fuel and diversion only"
        ) in result["warnings"]

    async def test_no_arbitrary_weather_checkpoint_route(self):
        result = await _calculate()
        names = [candidate["name"] for candidate in result["candidate_summaries"]]
        assert "via_weather_checkpoint" not in names
        assert {"direct", "left_offset", "right_offset"} <= set(names)

    async def test_unknown_checkpoints_carry_no_penalty(self):
        result = await _calculate()
        checkpoints = result["weather_checkpoints"]
        assert [c["icao"] for c in checkpoints] == ["KAAA", "KBBB"]
        assert all(c["flight_category"] == "UNKNOWN" and c["weather_penalty"] is None for c in checkpoints)

    async def test_every_variant_leaves_the_same_components_out(self):
        result = await _calculate()
        assert {tuple(v.score_breakdown["unavailable_components"]) for v in result["variants"]} == {("weather", "delay")}

    async def test_weather_cautious_reports_that_it_had_nothing_to_act_on(self):
        result = await _calculate("weather_cautious")
        assert any("weather-cautious preference had no weather data" in w for w in result["warnings"])

    async def test_the_delay_estimate_still_computes_with_null_components(self):
        result = await _calculate()
        assert result["delay_prediction"]["delay_risk"]
        # the ML features see the neutral 50 for a component without data
        assert result["delay_features"]["weather_score"] == 50.0
        assert result["delay_features"]["delay_score"] == 50.0


@pytest.mark.asyncio
@pytest.mark.usefixtures("calm_winds")
class TestCalculatorWithProviders:
    async def test_known_data_is_scored_and_unchanged(self, monkeypatch):
        _connect_providers(monkeypatch, {"KJFK": "VFR", "KORD": "VFR", "KAAA": "VFR", "KBBB": "VFR"})
        result = await _calculate()
        breakdown = result["primary"].score_breakdown
        assert breakdown["component_scores"]["weather"] == 100.0
        assert breakdown["component_scores"]["delay"] == 100.0
        assert breakdown["unavailable_components"] == []
        assert breakdown["effective_weights"] == WEIGHTS["balanced"]
        assert not [w for w in result["warnings"] if "not part of the route score" in w or "not included in" in w]

    async def test_the_weather_checkpoint_route_goes_through_the_best_weather(self, monkeypatch):
        _connect_providers(monkeypatch, {"KJFK": "VFR", "KORD": "VFR", "KAAA": "IFR", "KBBB": "VFR"})
        result = await _calculate()
        variants = {v.name: v for v in result["variants"]}
        assert "via_weather_checkpoint" in variants
        best = next(c for c in _checkpoints() if c["icao_code"] == "KBBB")
        assert variants["via_weather_checkpoint"].waypoints[1] == (best["latitude"], best["longitude"])

    async def test_checkpoint_penalties_average_over_known_checkpoints_only(self, monkeypatch):
        _connect_providers(monkeypatch, {"KJFK": "VFR", "KORD": "VFR", "KAAA": "IFR", "KBBB": None})
        result = await _calculate()
        assert result["primary"].score_breakdown["component_scores"]["weather"] == 65.0  # 100 - 35 (KBBB not counted)

    async def test_a_missing_destination_is_flagged_not_assumed_vfr(self, monkeypatch):
        _connect_providers(monkeypatch, {"KJFK": "IFR", "KORD": None, "KAAA": "VFR", "KBBB": "VFR"})
        result = await _calculate()
        breakdown = result["primary"].score_breakdown
        assert breakdown["component_scores"]["weather"] == 60.0  # the known IFR departure is kept
        assert "Weather unavailable for destination KORD — not included in the weather score" in result["warnings"]

    async def test_missing_checkpoint_weather_is_flagged(self, monkeypatch):
        _connect_providers(monkeypatch, {"KJFK": "VFR", "KORD": "VFR", "KAAA": "MVFR", "KBBB": None})
        result = await _calculate()
        assert any("1 of 2 en-route checkpoints" in w for w in result["warnings"])

    async def test_partial_faa_status_is_flagged(self, monkeypatch):
        _connect_providers(
            monkeypatch,
            {"KJFK": "VFR", "KORD": "VFR", "KAAA": "VFR", "KBBB": "VFR"},
            faa={"KORD": "unknown"},
        )
        result = await _calculate()
        assert result["primary"].score_breakdown["component_scores"]["delay"] == 100.0
        assert "FAA status unavailable for destination KORD — not included in the delay score" in result["warnings"]

    async def test_a_closed_known_airport_still_lowers_the_delay_component(self, monkeypatch):
        _connect_providers(
            monkeypatch,
            {"KJFK": "VFR", "KORD": "VFR", "KAAA": "VFR", "KBBB": "VFR"},
            faa={"KORD": "closed"},
        )
        result = await _calculate()
        assert result["primary"].score_breakdown["component_scores"]["delay"] == 40.0  # 100 - 120 * 0.5


class TestCalculateEndpoint:
    @pytest.fixture
    def env(self, api, monkeypatch):
        return calculation_env(api, monkeypatch)

    def test_the_response_describes_the_missing_components(self, env):
        response = env.post()
        assert response.status_code == 201
        body = response.json()
        breakdown = body["normalized_score_breakdown"]
        assert breakdown["component_scores"]["weather"] is None
        assert breakdown["component_scores"]["delay"] is None
        assert breakdown["unavailable_components"] == ["weather", "delay"]
        assert body["primary_score"] == breakdown["composite_score"]
        assert any("not part of the route score" in w for w in body["warnings"])

    def test_the_stored_route_returns_the_same_breakdown(self, env):
        created = env.post().json()
        fetched = env.client.get(f"/routes/{created['id']}").json()
        assert fetched["normalized_score_breakdown"]["unavailable_components"] == ["weather", "delay"]
        assert fetched["normalized_score_breakdown"]["component_scores"]["weather"] is None
        assert fetched["primary_score"] == created["primary_score"]
