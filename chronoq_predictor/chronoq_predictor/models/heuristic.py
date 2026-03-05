"""Heuristic estimator using per-type running mean and standard deviation."""

import statistics

from chronoq_predictor.models.base import BaseEstimator
from chronoq_predictor.schemas import TaskRecord


class HeuristicEstimator(BaseEstimator):
    """Cold-start estimator: per-task_type mean and std deviation."""

    def __init__(self) -> None:
        self._stats: dict[str, dict[str, float]] = {}
        self._global_mean: float = 1000.0
        self._version_counter: int = 0
        self._version: str = "heuristic-v0"

    def fit(self, records: list[TaskRecord]) -> dict:
        """Recompute stats from all records."""
        by_type: dict[str, list[float]] = {}
        for r in records:
            by_type.setdefault(r.task_type, []).append(r.actual_ms)

        self._stats = {}
        all_values: list[float] = []
        for task_type, values in by_type.items():
            mean = statistics.mean(values)
            std = statistics.stdev(values) if len(values) > 1 else 0.0
            self._stats[task_type] = {"mean": mean, "std": std, "count": len(values)}
            all_values.extend(values)

        if all_values:
            self._global_mean = statistics.mean(all_values)

        self._version_counter += 1
        self._version = f"heuristic-v{self._version_counter}"

        # Compute MAE and MAPE
        mae = 0.0
        mape = 0.0
        if records:
            errors = []
            pct_errors = []
            for r in records:
                feats = {"task_type": r.task_type, "payload_size": r.payload_size}
                predicted, _ = self.predict(feats)
                errors.append(abs(predicted - r.actual_ms))
                if r.actual_ms > 0:
                    pct_errors.append(abs(predicted - r.actual_ms) / r.actual_ms)
            mae = statistics.mean(errors) if errors else 0.0
            mape = statistics.mean(pct_errors) * 100 if pct_errors else 0.0

        return {"mae": mae, "mape": mape, "samples_used": len(records)}

    def predict(self, features: dict) -> tuple[float, float]:
        """Predict based on per-type mean. Unseen types get global mean."""
        task_type = features.get("task_type", "")

        if not self._stats:
            return (1000.0, 0.1)

        if task_type in self._stats:
            s = self._stats[task_type]
            mean = s["mean"]
            std = s["std"]
            confidence = 1.0 / (1.0 + std / max(mean, 1.0))
            return (mean, confidence)

        return (self._global_mean, 0.3)

    def version(self) -> str:
        return self._version

    def model_type(self) -> str:
        return "heuristic"
