import pytest

from app.services.copilot_intent import classify_copilot_intent, generate_suggested_questions
from app.services.ml_features import (
    delay_label_from_features,
    ete_label_from_route,
    extract_delay_features,
    extract_ete_features,
    refresh_delay_feature_categories,
)


class TestCopilotIntent:
    def test_classify_wind(self):
        assert classify_copilot_intent("Which segment has the strongest headwind?") == "wind"

    def test_classify_fuel(self):
        assert classify_copilot_intent("How much reserve fuel remains?") == "fuel"

    def test_classify_compare(self):
        assert classify_copilot_intent("Compare primary and alternate") == "primary_vs_alternate"


class TestSuggestedQuestions:
    def test_generates_from_wind_risk(self):
        ctx = {
            "primary_route": {"score": 80},
            "alternate_route": {"score": 75},
            "wind_summary": {"max_headwind_kt": 25},
            "diversions": [{"icao": "KPHX"}],
            "fuel_breakdown": {"reserve_fuel_gal": 20},
            "departure_weather": {"metar": {"available": True}},
            "destination_weather": {"metar": {"available": True}},
            "warnings": [],
        }
        qs = generate_suggested_questions(ctx)
        assert any("headwind" in q.lower() for q in qs)


class TestMLFeatures:
    def test_delay_label_high_on_closure(self):
        features = {"departure_closed": 1, "departure_delay_minutes": 0}
        label = delay_label_from_features(features)
        assert label["delay_risk"] == "high"

    def test_delay_label_medium_from_headwind_composite(self):
        features = refresh_delay_feature_categories(
            {
                "departure_delay_minutes": 0,
                "destination_delay_minutes": 0,
                "departure_faa_unknown": 1,
                "destination_faa_unknown": 1,
                "departure_flight_category": None,
                "destination_flight_category": None,
                "max_headwind_component_kt": 28,
                "weather_score": 75,
                "delay_score": 80,
                "diversion_count": 0,
                "route_distance_nm": 800,
            }
        )
        label = delay_label_from_features(features)
        assert label["delay_risk"] in ("medium", "high")

    def test_ete_label_from_route(self):
        label = ete_label_from_route({"primary_ete_minutes": 120.5})
        assert label["ete_minutes"] == 120.5
        assert label["label_source"] == "deterministic_engine_v1"

    def test_extract_delay_features_shape(self):
        req = {"route_preference": "balanced", "_aircraft_cruise_speed_kt": 180}
        route = {
            "primary_distance_nm": 500,
            "departure_weather": {"metar": {"flight_category": "VFR"}, "faa_status": {}},
            "destination_weather": {"metar": {"flight_category": "MVFR"}, "faa_status": {}},
            "weather_checkpoints": [],
            "normalized_score_breakdown": {"component_scores": {"weather": 80, "delay": 70}},
        }
        feat = extract_delay_features(req, route, [], [])
        assert feat["route_distance_nm"] == 500
        assert "departure_flight_category_ord" in feat

    def test_extract_ete_features_shape(self):
        req = {"_aircraft_cruise_speed_kt": 200}
        route = {"primary_distance_nm": 300, "primary_ete_minutes": 90, "route_candidates": []}
        feat = extract_ete_features(req, route, [{"headwind_component_kt": 5}])
        assert feat["number_of_segments"] == 1


class TestDelayRiskInference:
    def test_rules_fallback(self):
        from app.services.delay_risk import predict_delay_risk

        result = predict_delay_risk({"departure_delay_minutes": 45})
        assert result["delay_risk"] in ("low", "medium", "high")

    def test_ml_model_singleton(self):
        from ml.inference.delay_risk_model import delay_risk_model

        result = delay_risk_model.predict({"departure_delay_minutes": 0, "destination_delay_minutes": 0})
        assert "delay_risk" in result
