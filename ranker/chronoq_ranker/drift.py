"""Drift detection for the ranker.

``DriftDetector`` computes Population Stability Index (PSI) per numeric
feature, comparing a current batch against a reference distribution.  PSI
thresholds follow industry convention:
  < warn_threshold (config.psi_threshold, default 0.2) → stable
  warn_threshold <= PSI < 0.3                          → warn
  PSI >= 0.3                                           → drift (hard-coded)

Rolling MAE delta is tracked separately and exposed via ``DriftReport`` for
use by the ranker's drift_status() API.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import numpy as np

from chronoq_ranker.config import RankerConfig
from chronoq_ranker.features import DefaultExtractor
from chronoq_ranker.schemas import DriftReport, TaskRecord

if TYPE_CHECKING:
    from chronoq_ranker.features import FeatureExtractor

_DRIFT_THRESHOLD = 0.3  # hard-coded upper boundary; warn threshold is config.psi_threshold
_N_BINS = 10
_MAE_WINDOW = 100


class DriftDetector:
    """Monitors feature distribution shift and rolling prediction error.

    Call ``set_reference(records)`` once after a full model refit, then call
    ``check(recent_records)`` periodically to get a ``DriftReport``.
    """

    def __init__(
        self,
        config: RankerConfig | None = None,
        feature_extractor: FeatureExtractor | None = None,
    ) -> None:
        self._config = config or RankerConfig()
        self._extractor: FeatureExtractor = feature_extractor or DefaultExtractor()
        self._reference: dict[str, np.ndarray] = {}
        self._mae_window: deque[float] = deque(maxlen=_MAE_WINDOW)
        self.last_report: DriftReport | None = None

    def set_reference(self, records: list[TaskRecord]) -> None:
        """Store the reference distribution from the current training batch."""
        if not records:
            return
        numeric_cols = self._extractor.schema.numeric
        self._reference = {}
        for col in numeric_cols:
            vals = [self._extractor.extract_from_record(r).get(col, 0.0) for r in records]
            self._reference[col] = np.array(vals, dtype=np.float64)

    def record_mae(self, predicted_ms: float, actual_ms: float) -> None:
        """Track a single prediction error for rolling MAE."""
        self._mae_window.append(abs(predicted_ms - actual_ms))

    def check(self, records: list[TaskRecord]) -> DriftReport:
        """Compute PSI for each numeric feature vs the reference distribution.

        Raises RuntimeError if ``set_reference`` has not been called.
        """
        if not self._reference:
            raise RuntimeError(
                "DriftDetector.set_reference() must be called before check(). "
                "Call it after each full model refit with the training records."
            )

        per_feature_psi: dict[str, float] = {}
        warned: list[str] = []
        drifted: list[str] = []

        for col, ref_vals in self._reference.items():
            cur_vals = np.array(
                [self._extractor.extract_from_record(r).get(col, 0.0) for r in records],
                dtype=np.float64,
            )
            psi = _compute_psi(ref_vals, cur_vals)
            per_feature_psi[col] = round(psi, 6)

            if psi >= _DRIFT_THRESHOLD:
                drifted.append(col)
            elif psi >= self._config.psi_threshold:
                warned.append(col)

        rolling_mae_delta = float(np.mean(list(self._mae_window))) if self._mae_window else 0.0

        if drifted:
            status = "drift"
        elif warned:
            status = "warn"
        else:
            status = "stable"

        report = DriftReport(
            per_feature_psi=per_feature_psi,
            overall_status=status,
            rolling_mae_delta=rolling_mae_delta,
            drifted_features=sorted(drifted),
            warned_features=sorted(warned),
        )
        self.last_report = report
        return report


def _compute_psi(reference: np.ndarray, current: np.ndarray, n_bins: int = _N_BINS) -> float:
    """Population Stability Index using equal-frequency bins from the reference.

    Returns 0.0 for degenerate inputs (empty arrays, constant reference).
    PSI formula: sum( (A% - E%) * ln(A%/E%) ) where E=expected(ref), A=actual(cur).
    """
    if len(reference) < 2 or len(current) < 1:
        return 0.0

    quantiles = np.linspace(0, 100, n_bins + 1)
    bins = np.percentile(reference, quantiles)

    # Widen edges to capture boundary values
    bins[0] -= 1e-10
    bins[-1] += 1e-10

    # Degenerate: all reference values identical → unique_bins < 2 after np.unique
    unique_bins = np.unique(bins)
    if len(unique_bins) < 2:
        return 0.0

    ref_counts, _ = np.histogram(reference, bins=unique_bins)
    cur_counts, _ = np.histogram(current, bins=unique_bins)

    n_ref = max(len(reference), 1)
    n_cur = max(len(current), 1)

    eps = 1e-10
    ref_pct = np.clip(ref_counts / n_ref, eps, None)
    cur_pct = np.clip(cur_counts / n_cur, eps, None)

    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
