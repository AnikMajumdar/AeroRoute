from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.services.delay_risk import predict_delay_risk as rules_predict
from app.services.ml_features import DELAY_FEATURE_COLUMNS, features_to_vector

logger = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "artifacts"
MODEL_FILE = ARTIFACT_DIR / "delay_risk_model_v1.joblib"
META_FILE = ARTIFACT_DIR / "delay_risk_model_v1_metadata.json"
RISK_LEVELS = ["low", "medium", "high"]


class DelayRiskModel:
    """Delay risk classifier — ML when artifact exists, else rules baseline."""

    def __init__(self) -> None:
        self._model = None
        self._metadata: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not MODEL_FILE.exists():
            return
        try:
            import joblib

            self._model = joblib.load(MODEL_FILE)
            if META_FILE.exists():
                self._metadata = json.loads(META_FILE.read_text())
        except Exception as exc:
            logger.warning("Failed to load delay risk model: %s", exc)
            self._model = None

    @property
    def is_ml_loaded(self) -> bool:
        return self._model is not None

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        if self._model is None:
            result = rules_predict(features)
            result["model_target"] = "delay_risk"
            return result

        columns = self._metadata.get("feature_columns", DELAY_FEATURE_COLUMNS)
        vector = [features_to_vector(features, columns)]
        try:
            proba = None
            if hasattr(self._model, "predict_proba"):
                proba = self._model.predict_proba(vector)[0]
                pred_idx = int(proba.argmax())
                confidence = float(proba[pred_idx])
            else:
                pred_idx = int(self._model.predict(vector)[0])
                confidence = 0.6

            classes = list(getattr(self._model, "classes_", RISK_LEVELS))
            level = classes[pred_idx] if pred_idx < len(classes) else RISK_LEVELS[pred_idx]
            return {
                "model_name": self._metadata.get("model_name", "delay_risk_classifier_v1"),
                "model_version": self._metadata.get("model_version", "v1"),
                "model_target": "delay_risk",
                "delay_risk": level,
                "confidence": round(confidence, 3),
                "feature_summary": {k: features.get(k) for k in columns[:8]},
                "is_surrogate": False,
            }
        except Exception as exc:
            logger.warning("ML delay predict failed, using rules: %s", exc)
            result = rules_predict(features)
            result["model_target"] = "delay_risk"
            return result


delay_risk_model = DelayRiskModel()
