from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.services.ml_features import ETE_FEATURE_COLUMNS, features_to_vector

logger = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "artifacts"
MODEL_FILE = ARTIFACT_DIR / "ete_model_v1.joblib"
META_FILE = ARTIFACT_DIR / "ete_model_v1_metadata.json"


class ETEPredictionModel:
    """ETE regressor — ML when artifact exists, else deterministic engine ETE."""

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
            logger.warning("Failed to load ETE model: %s", exc)
            self._model = None

    @property
    def is_ml_loaded(self) -> bool:
        return self._model is not None

    def predict(self, features: dict[str, Any], deterministic_ete_minutes: float) -> dict[str, Any]:
        if self._model is None:
            return {
                "model_name": "deterministic_engine_v1",
                "model_version": "v1",
                "model_target": "ete_prediction",
                "ete_minutes": round(deterministic_ete_minutes, 1),
                "ml_adjusted_ete_minutes": round(deterministic_ete_minutes, 1),
                "adjustment_minutes": 0.0,
                "confidence": None,
                "is_surrogate": True,
                "note": "No trained ETE model — using deterministic route engine ETE.",
            }

        columns = self._metadata.get("feature_columns", ETE_FEATURE_COLUMNS)
        vector = [features_to_vector(features, columns)]
        try:
            pred = float(self._model.predict(vector)[0])
            adjustment = pred - deterministic_ete_minutes
            return {
                "model_name": self._metadata.get("model_name", "ete_regressor_v1"),
                "model_version": self._metadata.get("model_version", "v1"),
                "model_target": "ete_prediction",
                "ete_minutes": round(deterministic_ete_minutes, 1),
                "ml_adjusted_ete_minutes": round(pred, 1),
                "adjustment_minutes": round(adjustment, 1),
                "confidence": self._metadata.get("mae_minutes"),
                "is_surrogate": True,
                "note": (
                    "ETE model trained on deterministic engine labels (surrogate). "
                    "Not validated against actual flight times."
                ),
                "feature_summary": {k: features.get(k) for k in columns[:6]},
            }
        except Exception as exc:
            logger.warning("ML ETE predict failed: %s", exc)
            return {
                "model_name": "deterministic_engine_v1",
                "model_target": "ete_prediction",
                "ete_minutes": round(deterministic_ete_minutes, 1),
                "ml_adjusted_ete_minutes": round(deterministic_ete_minutes, 1),
                "is_surrogate": True,
            }


ete_prediction_model = ETEPredictionModel()
