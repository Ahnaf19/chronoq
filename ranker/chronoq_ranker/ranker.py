"""TaskRanker — orchestrates prediction, recording, and model retraining."""

import threading

from loguru import logger

from chronoq_ranker.config import RankerConfig
from chronoq_ranker.features import DefaultExtractor, FeatureExtractor, _legacy_extract_features
from chronoq_ranker.models.gradient import GradientEstimator
from chronoq_ranker.models.heuristic import HeuristicEstimator
from chronoq_ranker.models.lambdarank import LambdaRankEstimator
from chronoq_ranker.schemas import (
    InsufficientGroupsError,
    PredictionResult,
    RetrainResult,
    ScoredTask,
    TaskCandidate,
    TaskRecord,
)
from chronoq_ranker.storage import TelemetryStore, create_store


class TaskRanker:
    """Main entry point: predict task duration, record actuals, auto-retrain, rank batches."""

    def __init__(
        self,
        config: RankerConfig | None = None,
        storage: TelemetryStore | str | None = None,
        feature_extractor: FeatureExtractor | None = None,
    ) -> None:
        self._config = config or RankerConfig()

        if isinstance(storage, str):
            self._store = create_store(storage)
        elif storage is not None:
            self._store = storage
        else:
            self._store = create_store(self._config.storage_uri)

        self._estimator = HeuristicEstimator()
        self._extractor = feature_extractor or DefaultExtractor()
        self._lock = threading.Lock()

        if self._store.count() > 0:
            self._warm_start()

    def predict(
        self, task_type: str, payload_size: int, metadata: dict | None = None
    ) -> PredictionResult:
        """Predict execution time for a task (v1-compatible single-item API)."""
        features = _legacy_extract_features(task_type, payload_size, metadata)

        with self._lock:
            estimator = self._estimator

        score, confidence = estimator.predict(features)

        return PredictionResult(
            estimated_ms=score,
            confidence=confidence,
            model_version=estimator.version(),
            model_type=estimator.model_type(),
        )

    def predict_scores(
        self,
        candidates: list[TaskCandidate],
        group_id: str | None = None,  # noqa: ARG002  (consumed by LambdaRank via group_id on records)
    ) -> list[ScoredTask]:
        """Score a batch of candidates for ranking; return sorted lowest-score-first.

        For heuristic/gradient models: score is estimated duration in ms (lower = sooner).
        For LambdaRank: score is a negated pairwise rank score (lower = sooner).
        """
        if not candidates:
            return []

        with self._lock:
            estimator = self._estimator

        all_features = [self._extractor.extract(cand) for cand in candidates]
        batch_results = estimator.predict_batch(all_features)

        scored = [
            (cand, result[0]) for cand, result in zip(candidates, batch_results, strict=False)
        ]
        scored.sort(key=lambda pair: pair[1])

        return [
            ScoredTask(
                task_id=cand.task_id,
                score=score,
                rank=rank,
                model_version=estimator.version(),
                model_type=estimator.model_type(),
            )
            for rank, (cand, score) in enumerate(scored)
        ]

    def record(
        self,
        task_type: str,
        payload_size: int,
        actual_ms: float,
        metadata: dict | None = None,
    ) -> None:
        """Record actual execution time and check auto-retrain trigger."""
        with self._lock:
            current_version = self._estimator.version()

        rec = TaskRecord(
            task_type=task_type,
            payload_size=payload_size,
            actual_ms=actual_ms,
            metadata=metadata or {},
            model_version_at_record=current_version,
        )
        self._store.save(rec)

        since_count = self._store.count_since(current_version)
        if since_count >= self._config.retrain_every_n:
            logger.info(
                "Auto-retrain triggered: {} records since version {}",
                since_count,
                current_version,
            )
            self.retrain()

    def retrain(self) -> RetrainResult:
        """Retrain the model, promoting heuristic → lambdarank when enough data."""
        records = self._store.get_all()
        total = len(records)

        with self._lock:
            previous_type = self._estimator.model_type()
            current_estimator = self._estimator

        if total >= self._config.cold_start_threshold:
            if isinstance(current_estimator, LambdaRankEstimator):
                new_estimator = current_estimator  # incremental fit on same instance
            else:
                new_estimator = LambdaRankEstimator(
                    config=self._config,
                    feature_extractor=self._extractor,
                )

            try:
                metrics = new_estimator.fit(records)
            except InsufficientGroupsError:
                if self._config.allow_degrade:
                    logger.warning(
                        "LambdaRank fit failed (insufficient groups); "
                        "degrading to GradientEstimator."
                    )
                    new_estimator = GradientEstimator()
                    metrics = new_estimator.fit(records)
                else:
                    raise
        else:
            new_estimator = HeuristicEstimator()
            metrics = new_estimator.fit(records)

        promoted = new_estimator.model_type() != previous_type

        with self._lock:
            self._estimator = new_estimator

        logger.info(
            "Retrain complete: model={}, version={}, promoted={}",
            new_estimator.model_type(),
            new_estimator.version(),
            promoted,
        )

        return RetrainResult(
            mae=metrics.get("mae", 0.0),
            mape=metrics.get("mape", 0.0),
            samples_used=metrics.get("samples_used", total),
            model_version=new_estimator.version(),
            promoted=promoted,
            model_type=new_estimator.model_type(),
            spearman_rho=metrics.get("spearman_rho"),
            pairwise_accuracy=metrics.get("pairwise_accuracy"),
            kendall_tau=metrics.get("kendall_tau"),
        )

    def drift_status(self) -> dict:
        """Return current drift state (placeholder until DriftDetector wired in W3+)."""
        return {"status": "unavailable", "reason": "drift detector not yet initialized"}

    def _warm_start(self) -> None:
        """Fit model from existing storage data on init."""
        records = self._store.get_all()
        n = len(records)

        if n >= self._config.cold_start_threshold:
            new_estimator: HeuristicEstimator | GradientEstimator | LambdaRankEstimator
            new_estimator = LambdaRankEstimator(
                config=self._config,
                feature_extractor=self._extractor,
            )
            try:
                new_estimator.fit(records)
            except InsufficientGroupsError:
                if self._config.allow_degrade:
                    new_estimator = GradientEstimator()
                    new_estimator.fit(records)
                else:
                    raise
        else:
            new_estimator = HeuristicEstimator()
            new_estimator.fit(records)

        with self._lock:
            self._estimator = new_estimator

        logger.info("Warm-started with {} records, model={}", n, new_estimator.model_type())
