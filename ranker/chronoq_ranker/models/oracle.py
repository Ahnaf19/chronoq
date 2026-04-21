"""Oracle rankers for benchmark baselines.

OracleRanker uses the true ``actual_ms`` (future information) for perfect
SJF/SRPT ordering. **Never use in production.** Only valid in simulation
benchmarks where the true duration is available at scheduling time.

Usage in benchmarks: pass a features dict that includes ``_actual_ms``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from chronoq_ranker.models.base import BaseEstimator, ModelType

if TYPE_CHECKING:
    from chronoq_ranker.schemas import TaskRecord


class OracleRanker(BaseEstimator):
    """Perfect-knowledge shortest-job-first (or SRPT) oracle.

    Reads ``_actual_ms`` from the feature dict — a private key set by the
    benchmark harness before scoring. Since this is post-execution information,
    this ranker cannot be used outside of simulation.

    ``model_type()`` returns ``"oracle_sjf"`` or ``"oracle_srpt"`` depending
    on ``mode``.  SRPT is identical to SJF for non-preemptive schedulers
    (which is what the SimPy simulator models in Chunk 2).
    """

    def __init__(self, mode: Literal["sjf", "srpt"] = "sjf") -> None:
        self._mode = mode
        self._version_str = f"oracle-{mode}-v1"

    def fit(self, records: list[TaskRecord]) -> dict:
        """No-op: oracle uses ground truth directly."""
        return {"mae": 0.0, "mape": 0.0, "samples_used": len(records)}

    def predict(self, features: dict) -> tuple[float, float]:
        """Return actual_ms as the score (lower = shorter = scheduled sooner)."""
        actual_ms = float(features.get("_actual_ms", 0.0))
        return actual_ms, 1.0

    def predict_batch(self, feature_dicts: list[dict]) -> list[tuple[float, float]]:
        return [(float(f.get("_actual_ms", 0.0)), 1.0) for f in feature_dicts]

    def version(self) -> str:
        return self._version_str

    def model_type(self) -> ModelType:
        return "oracle_sjf" if self._mode == "sjf" else "oracle_srpt"
