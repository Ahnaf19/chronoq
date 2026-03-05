"""GradientBoosting estimator for warm-start predictions."""

import statistics

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import LabelEncoder

from chronoq_predictor.features import extract_training_features
from chronoq_predictor.models.base import BaseEstimator
from chronoq_predictor.models.heuristic import HeuristicEstimator
from chronoq_predictor.schemas import TaskRecord


class GradientEstimator(BaseEstimator):
    """Warm estimator: GradientBoostingRegressor with heuristic fallback."""

    def __init__(self) -> None:
        self._model: GradientBoostingRegressor | None = None
        self._label_encoder: LabelEncoder = LabelEncoder()
        self._known_types: set[str] = set()
        self._heuristic_fallback: HeuristicEstimator = HeuristicEstimator()
        self._version_counter: int = 0
        self._version: str = "gradient-v0"
        self._training_mae: float = 0.0
        self._mean_prediction: float = 1000.0

    def fit(self, records: list[TaskRecord]) -> dict:
        """Train GradientBoosting on records with 80/20 split."""
        self._heuristic_fallback.fit(records)

        features_list = []
        targets = []
        task_types = []

        for r in records:
            feat = extract_training_features(r)
            task_types.append(feat["task_type"])
            features_list.append(feat)
            targets.append(r.actual_ms)

        self._label_encoder.fit(task_types)
        self._known_types = set(self._label_encoder.classes_)

        x_all = self._build_feature_matrix(features_list)
        y = np.array(targets)

        # Train/test split
        if len(records) >= 5:
            split_idx = int(len(records) * 0.8)
            x_train, x_test = x_all[:split_idx], x_all[split_idx:]
            y_train, y_test = y[:split_idx], y[split_idx:]
        else:
            x_train, x_test = x_all, x_all
            y_train, y_test = y, y

        self._model = GradientBoostingRegressor(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            random_state=42,
        )
        self._model.fit(x_train, y_train)

        predictions = self._model.predict(x_test)
        self._mean_prediction = float(np.mean(predictions)) if len(predictions) > 0 else 1000.0

        errors = np.abs(predictions - y_test)
        mae = float(np.mean(errors))
        self._training_mae = mae

        pct_errors = []
        for pred, actual in zip(predictions, y_test, strict=False):
            if actual > 0:
                pct_errors.append(abs(pred - actual) / actual)
        mape = float(statistics.mean(pct_errors) * 100) if pct_errors else 0.0

        self._version_counter += 1
        self._version = f"gradient-v{self._version_counter}"

        return {"mae": mae, "mape": mape, "samples_used": len(records)}

    def predict(self, features: dict) -> tuple[float, float]:
        """Predict using trained model, falling back to heuristic for unseen types."""
        task_type = features.get("task_type", "")

        if self._model is None or task_type not in self._known_types:
            return self._heuristic_fallback.predict(features)

        x_input = self._build_feature_matrix([features])
        prediction = float(self._model.predict(x_input)[0])
        prediction = max(1.0, prediction)

        confidence = max(0.1, min(1.0, 1.0 - self._training_mae / max(self._mean_prediction, 1.0)))
        return (prediction, confidence)

    def version(self) -> str:
        return self._version

    def model_type(self) -> str:
        return "gradient_boosting"

    def _build_feature_matrix(self, features_list: list[dict]) -> np.ndarray:
        """Convert feature dicts to numpy array for sklearn."""
        rows = []
        for feat in features_list:
            task_type = feat["task_type"]
            if task_type in self._known_types:
                encoded_type = float(self._label_encoder.transform([task_type])[0])
            else:
                encoded_type = -1.0
            rows.append(
                [
                    encoded_type,
                    float(feat.get("payload_size", 0)),
                    float(feat.get("hour_of_day", 0)),
                    float(feat.get("queue_depth", 0)),
                ]
            )
        return np.array(rows)
