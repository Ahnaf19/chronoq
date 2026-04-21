"""LightGBM LambdaRank estimator.

Wraps ``lightgbm.LGBMRanker(objective="lambdarank")`` with:
- 60s tumbling-window group assignment (or explicit ``group_id`` from records).
- Pairwise label construction: ``rank_label = max_rank - rank_ascending_by_actual_ms``.
- Incremental warm-start via ``init_model`` (full refit every N incrementals).
- Held-out Spearman ρ validation; rejects new model if ρ drops >0.1.
- Native LightGBM categorical encoding for ``task_type`` and ``user_tier``.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import UTC, datetime

import numpy as np

from chronoq_ranker.config import RankerConfig
from chronoq_ranker.features import DEFAULT_SCHEMA_V1, DefaultExtractor, FeatureExtractor
from chronoq_ranker.models.base import BaseEstimator, ModelType
from chronoq_ranker.schemas import InsufficientGroupsError, TaskRecord

_WINDOW_SECONDS = 60
_LEARNING_RATE = 0.05
_N_ESTIMATORS_FULL = 500
_NUM_LEAVES = 31
_MIN_DATA_IN_LEAF = 20
_RHO_REJECTION_DELTA = 0.1
# LightGBM lambdarank labels must be in [0, label_gain length - 1].
# Default label_gain has 31 entries (labels 0-30).  We cap at 9 (10 grades)
# and normalize proportionally for large groups, matching standard LTR practice.
_LABEL_MAX = 9

# Column order mirrors DEFAULT_SCHEMA_V1; must stay in sync.
_NUMERIC_COLS: list[str] = list(DEFAULT_SCHEMA_V1.numeric)
_CAT_COLS: list[str] = list(DEFAULT_SCHEMA_V1.categorical)
_CAT_COL_INDICES: list[int] = list(range(len(_NUMERIC_COLS), len(_NUMERIC_COLS) + len(_CAT_COLS)))


def _make_version() -> str:
    return f"lambdarank-v{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"


def _assign_tumbling_group_ids(records: list[TaskRecord]) -> list[TaskRecord]:
    """Assign 60s tumbling-window group_id to records that lack one."""
    result = []
    for r in records:
        if r.group_id is not None:
            result.append(r)
        else:
            ts = r.recorded_at.timestamp()
            bucket = int(ts // _WINDOW_SECONDS) * _WINDOW_SECONDS
            result.append(r.model_copy(update={"group_id": f"window_{bucket}"}))
    return result


def _spearman_rho(scores: np.ndarray, labels: np.ndarray) -> float:
    """Spearman rank correlation via argsort; O(n log n)."""
    n = len(scores)
    if n < 2:
        return 0.0
    rank_s = np.argsort(np.argsort(scores)).astype(np.float64)
    rank_l = np.argsort(np.argsort(labels)).astype(np.float64)
    d = rank_s - rank_l
    denom = n * (n * n - 1)
    if denom == 0:
        return 0.0
    return float(1.0 - 6.0 * np.dot(d, d) / denom)


def _spearman_rho_grouped(scores: np.ndarray, labels: np.ndarray, group_sizes: np.ndarray) -> float:
    """Per-group Spearman ρ averaged across groups (correct for LTR evaluation)."""
    start = 0
    rhos: list[float] = []
    for size in group_sizes:
        end = start + int(size)
        if size >= 2:
            rhos.append(_spearman_rho(scores[start:end], labels[start:end].astype(np.float64)))
        start = end
    return float(np.mean(rhos)) if rhos else 0.0


def _kendall_tau_grouped(scores: np.ndarray, labels: np.ndarray, group_sizes: np.ndarray) -> float:
    """Per-group Kendall τ averaged across groups."""
    start = 0
    taus: list[float] = []
    for size in group_sizes:
        end = start + int(size)
        if size >= 2:
            gs = scores[start:end]
            gl = labels[start:end].astype(np.float64)
            concordant = discordant = 0
            for i in range(int(size)):
                for j in range(i + 1, int(size)):
                    ds = gs[i] - gs[j]
                    dl = gl[i] - gl[j]
                    if dl != 0:
                        if ds * dl > 0:
                            concordant += 1
                        else:
                            discordant += 1
            total = int(size) * (int(size) - 1) / 2
            if total > 0:
                taus.append((concordant - discordant) / total)
        start = end
    return float(np.mean(taus)) if taus else 0.0


def _pairwise_accuracy_grouped(
    scores: np.ndarray, labels: np.ndarray, group_sizes: np.ndarray
) -> float:
    """Group-aware pairwise accuracy: fraction of within-group pairs correctly ordered."""
    start = 0
    total = 0
    correct = 0
    for size in group_sizes:
        end = start + int(size)
        gs = scores[start:end]
        gl = labels[start:end]
        for i in range(int(size)):
            for j in range(i + 1, int(size)):
                if gl[i] != gl[j]:
                    total += 1
                    if (gs[i] - gs[j]) * (gl[i] - gl[j]) > 0:
                        correct += 1
        start = end
    return correct / total if total > 0 else 1.0


class LambdaRankEstimator(BaseEstimator):
    """LightGBM LGBMRanker with lambdarank objective.

    Manages its own full/incremental lifecycle: ``fit()`` decides based on
    whether a model exists and ``config.full_refit_every_n_incrementals``.

    Thread safety: ``_model`` pointer swap inside ``_lock`` is atomic.
    Fitting happens outside the lock; a concurrent ``predict()`` call sees
    the previous model until the swap completes.
    """

    def __init__(
        self,
        config: RankerConfig | None = None,
        feature_extractor: FeatureExtractor | None = None,
    ) -> None:
        self._config = config or RankerConfig()
        self._extractor = feature_extractor or DefaultExtractor()
        self._model = None  # LGBMRanker | None
        self._encoder: dict[str, dict[str, int]] = {}
        self._version_str: str = ""
        self._last_rho: float = 0.0
        self._incremental_count: int = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # BaseEstimator interface
    # ------------------------------------------------------------------

    def fit(self, records: list[TaskRecord]) -> dict:
        """Full or incremental fit; decision driven by internal counter."""
        with self._lock:
            do_full = self._model is None or (
                self._incremental_count >= self._config.full_refit_every_n_incrementals
            )

        if do_full:
            metrics = self._full_fit(records)
            with self._lock:
                self._incremental_count = 0
        else:
            metrics = self._incremental_fit(records)
            with self._lock:
                self._incremental_count += 1
        return metrics

    def predict(self, features: dict) -> tuple[float, float]:
        """Score a single candidate; returns (score, confidence).

        Score is negated so that lower = scheduled sooner, matching the
        convention for heuristic/gradient estimators.
        """
        with self._lock:
            model = self._model
        if model is None:
            return 0.0, 0.0
        x_mat = self._build_matrix([features])
        # Use booster_ directly to avoid sklearn's feature-name validation warning.
        score = float(np.asarray(model.booster_.predict(x_mat))[0])
        return -score, 0.8

    def predict_batch(self, feature_dicts: list[dict]) -> list[tuple[float, float]]:
        """Score a batch in one LGBM call. Returns [(score, confidence), ...]."""
        if not feature_dicts:
            return []
        with self._lock:
            model = self._model
        if model is None:
            return [(0.0, 0.0)] * len(feature_dicts)
        x_mat = self._build_matrix(feature_dicts)
        # Use booster_ directly to avoid sklearn's feature-name validation warning.
        scores = np.asarray(model.booster_.predict(x_mat))
        # Negate: LGBM gives higher score to "more relevant" (shorter job),
        # but our sort convention is ascending (lower score = sooner).
        return [(-float(s), 0.8) for s in scores]

    def version(self) -> str:
        with self._lock:
            return self._version_str or "lambdarank-unfit-v0"

    def model_type(self) -> ModelType:
        return "lambdarank"

    # ------------------------------------------------------------------
    # Internal fit logic
    # ------------------------------------------------------------------

    def _full_fit(self, records: list[TaskRecord]) -> dict:
        """Rebuild encoder from scratch and fit a fresh LGBMRanker."""
        import lightgbm as lgb

        x_mat, y, groups_train, groups_val, val_start = self._prepare_data(
            records, rebuild_encoder=True
        )
        n_valid_groups = len(groups_train) + len(groups_val)

        if n_valid_groups < self._config.min_groups:
            raise InsufficientGroupsError(n_valid_groups, self._config.min_groups)

        x_train, y_train = x_mat[:val_start], y[:val_start]
        x_val, y_val = x_mat[val_start:], y[val_start:]

        model = lgb.LGBMRanker(
            objective="lambdarank",
            learning_rate=_LEARNING_RATE,
            n_estimators=_N_ESTIMATORS_FULL,
            num_leaves=_NUM_LEAVES,
            min_data_in_leaf=_MIN_DATA_IN_LEAF,
            random_state=42,
            deterministic=True,
            n_jobs=-1,
            verbose=-1,
        )

        fit_kwargs: dict = dict(
            group=groups_train,
            categorical_feature=_CAT_COL_INDICES,
            callbacks=[lgb.log_evaluation(period=-1)],
        )
        if len(groups_val) > 0 and len(x_val) > 0:
            fit_kwargs["eval_set"] = [(x_val, y_val)]
            fit_kwargs["eval_group"] = [groups_val]

        model.fit(x_train, y_train, **fit_kwargs)

        rho, pairwise_acc, tau = 0.0, 1.0, 0.0
        if len(groups_val) > 0 and len(x_val) >= 2:
            val_scores = np.asarray(model.booster_.predict(x_val))
            rho = _spearman_rho_grouped(val_scores, y_val, groups_val)
            pairwise_acc = _pairwise_accuracy_grouped(val_scores, y_val, groups_val)
            tau = _kendall_tau_grouped(val_scores, y_val, groups_val)

        with self._lock:
            self._model = model
            self._last_rho = rho
            self._version_str = _make_version()

        return {
            "spearman_rho": rho,
            "pairwise_accuracy": pairwise_acc,
            "kendall_tau": tau,
            "mae": 0.0,
            "mape": 0.0,
            "samples_used": len(records),
        }

    def _incremental_fit(self, records: list[TaskRecord]) -> dict:
        """Warm-start from existing model; add ``incremental_rounds`` trees."""
        import lightgbm as lgb

        with self._lock:
            prev_model = self._model
            prev_rho = self._last_rho

        if prev_model is None:
            return self._full_fit(records)

        x_mat, y, groups_train, groups_val, val_start = self._prepare_data(
            records, rebuild_encoder=False
        )
        x_train, y_train = x_mat[:val_start], y[:val_start]
        x_val, y_val = x_mat[val_start:], y[val_start:]

        model = lgb.LGBMRanker(
            objective="lambdarank",
            learning_rate=_LEARNING_RATE,
            n_estimators=self._config.incremental_rounds,
            num_leaves=_NUM_LEAVES,
            min_data_in_leaf=_MIN_DATA_IN_LEAF,
            random_state=42,
            deterministic=True,
            n_jobs=-1,
            verbose=-1,
        )
        model.fit(
            x_train,
            y_train,
            group=groups_train,
            categorical_feature=_CAT_COL_INDICES,
            init_model=prev_model.booster_,
            callbacks=[lgb.log_evaluation(period=-1)],
        )

        rho, pairwise_acc, tau = 0.0, 1.0, 0.0
        if len(x_val) >= 2:
            val_scores = np.asarray(model.booster_.predict(x_val))
            rho = _spearman_rho_grouped(val_scores, y_val, groups_val)
            pairwise_acc = _pairwise_accuracy_grouped(val_scores, y_val, groups_val)
            tau = _kendall_tau_grouped(val_scores, y_val, groups_val)

            # Reject if ρ degrades beyond the allowed delta
            if rho < prev_rho - _RHO_REJECTION_DELTA:
                return {
                    "spearman_rho": prev_rho,
                    "pairwise_accuracy": pairwise_acc,
                    "kendall_tau": tau,
                    "mae": 0.0,
                    "mape": 0.0,
                    "samples_used": len(records),
                    "_rejected": True,
                }

        with self._lock:
            self._model = model
            self._last_rho = rho
            self._version_str = _make_version()

        return {
            "spearman_rho": rho,
            "pairwise_accuracy": pairwise_acc,
            "kendall_tau": tau,
            "mae": 0.0,
            "mape": 0.0,
            "samples_used": len(records),
        }

    # ------------------------------------------------------------------
    # Data preparation helpers
    # ------------------------------------------------------------------

    def _prepare_data(
        self, records: list[TaskRecord], rebuild_encoder: bool
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
        """Build feature matrix + label array + group-size arrays for LGBM.

        Returns (x_mat, y, groups_train, groups_val, val_start_row).
        The last 10% of groups (sorted by group_id) form the validation split.
        """
        enriched = _assign_tumbling_group_ids(records)

        buckets: dict[str, list[TaskRecord]] = defaultdict(list)
        for r in enriched:
            buckets[r.group_id].append(r)  # type: ignore[index]

        valid_groups = {gid: recs for gid, recs in buckets.items() if len(recs) >= 2}

        feature_rows: list[dict] = []
        labels: list[int] = []
        group_sizes: list[int] = []

        for gid in sorted(valid_groups):
            group_recs = sorted(valid_groups[gid], key=lambda r: r.actual_ms)
            n = len(group_recs)
            for i, rec in enumerate(group_recs):
                feature_rows.append(self._extractor.extract_from_record(rec))
                # Normalize to [0, _LABEL_MAX]: for small groups exact ranks are used;
                # for large groups proportional mapping prevents exceeding label_gain limit.
                if n <= _LABEL_MAX + 1:
                    label = n - 1 - i
                else:
                    label = round((n - 1 - i) / (n - 1) * _LABEL_MAX)
                labels.append(label)
            group_sizes.append(n)

        x_mat = self._build_matrix(feature_rows, fit=rebuild_encoder)
        y = np.array(labels, dtype=np.int32)
        sizes = np.array(group_sizes, dtype=np.int32)

        n_groups = len(group_sizes)
        n_val = max(1, n_groups // 10) if n_groups >= 10 else 0
        n_train = n_groups - n_val

        val_start = int(np.sum(sizes[:n_train])) if n_train > 0 else len(labels)
        groups_train = sizes[:n_train]
        groups_val = sizes[n_train:]

        return x_mat, y, groups_train, groups_val, val_start

    def _build_matrix(self, feature_dicts: list[dict], fit: bool = False) -> np.ndarray:
        """Convert feature dicts to float32 numpy matrix.

        Column order: numeric columns first, then categorical (label-encoded).
        If ``fit=True``, rebuilds the encoder from scratch. Otherwise, extends
        the encoder with any new category values (preserving existing indices).
        """
        if fit:
            self._encoder = {col: {} for col in _CAT_COLS}

        for fdict in feature_dicts:
            for col in _CAT_COLS:
                val = str(fdict.get(col, "__unknown__"))
                enc = self._encoder.setdefault(col, {})
                if val not in enc:
                    enc[val] = len(enc)

        rows: list[list[float]] = []
        for fdict in feature_dicts:
            row: list[float] = [float(fdict.get(col, 0.0)) for col in _NUMERIC_COLS]
            for col in _CAT_COLS:
                val = str(fdict.get(col, "__unknown__"))
                row.append(float(self._encoder[col].get(val, 0)))
            rows.append(row)

        return np.array(rows, dtype=np.float32)
