"""TaskRanker — orchestrates prediction, recording, and model retraining."""

import threading

from loguru import logger

from chronoq_ranker.config import RankerConfig
from chronoq_ranker.features import DefaultExtractor, FeatureExtractor, _legacy_extract_features
from chronoq_ranker.models.gradient import GradientEstimator
from chronoq_ranker.models.heuristic import HeuristicEstimator
from chronoq_ranker.schemas import (
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
        self._previous_model_type: str = "heuristic"

        # Warm-start from existing data
        if self._store.count() > 0:
            self._warm_start()

    def predict(
        self, task_type: str, payload_size: int, metadata: dict | None = None
    ) -> PredictionResult:
        """Predict execution time for a task (v1-compatible single-item API)."""
        features = _legacy_extract_features(task_type, payload_size, metadata)

        with self._lock:
            estimator = self._estimator

        estimated_ms, confidence = estimator.predict(features)

        return PredictionResult(
            estimated_ms=estimated_ms,
            confidence=confidence,
            model_version=estimator.version(),
            model_type=estimator.model_type(),
        )

    def predict_scores(
        self,
        candidates: list[TaskCandidate],
        group_id: str | None = None,  # noqa: ARG002  (used when LambdaRank lands in W3)
    ) -> list[ScoredTask]:
        """Score a batch of candidates for ranking; return sorted shortest-first.

        With the v1 heuristic/gradient estimators the score is the predicted
        duration in ms (lower = sooner). When LambdaRank lands in Chunk 1 W3,
        the score becomes a relative pairwise rank score within ``group_id``.
        """
        if not candidates:
            return []

        with self._lock:
            estimator = self._estimator

        scored_with_cands = []
        for cand in candidates:
            features = self._extractor.extract(cand)
            estimated_ms, _confidence = estimator.predict(features)
            scored_with_cands.append((cand, estimated_ms))

        # Ascending by score → shortest-first.
        scored_with_cands.sort(key=lambda pair: pair[1])

        return [
            ScoredTask(
                task_id=cand.task_id,
                score=score,
                rank=rank,
                model_version=estimator.version(),
                model_type=estimator.model_type(),
            )
            for rank, (cand, score) in enumerate(scored_with_cands)
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

        record = TaskRecord(
            task_type=task_type,
            payload_size=payload_size,
            actual_ms=actual_ms,
            metadata=metadata or {},
            model_version_at_record=current_version,
        )
        self._store.save(record)

        since_count = self._store.count_since(current_version)
        if since_count >= self._config.retrain_every_n:
            logger.info(
                "Auto-retrain triggered: {} records since version {}",
                since_count,
                current_version,
            )
            self.retrain()

    def retrain(self) -> RetrainResult:
        """Retrain the model, auto-promoting from heuristic to gradient if enough data."""
        records = self._store.get_all()
        total = len(records)

        with self._lock:
            previous_type = self._estimator.model_type()

        if total >= self._config.cold_start_threshold:
            new_estimator = GradientEstimator()
        else:
            new_estimator = HeuristicEstimator()

        # Fit outside lock to minimize lock duration
        metrics = new_estimator.fit(records)

        promoted = new_estimator.model_type() != previous_type

        with self._lock:
            self._estimator = new_estimator

        logger.info(
            "Retrain complete: model={}, version={}, mae={:.1f}, promoted={}",
            new_estimator.model_type(),
            new_estimator.version(),
            metrics["mae"],
            promoted,
        )

        return RetrainResult(
            mae=metrics["mae"],
            mape=metrics["mape"],
            samples_used=metrics["samples_used"],
            model_version=new_estimator.version(),
            promoted=promoted,
        )

    def _warm_start(self) -> None:
        """Fit model from existing storage data on init."""
        records = self._store.get_all()
        if len(records) >= self._config.cold_start_threshold:
            estimator = GradientEstimator()
        else:
            estimator = HeuristicEstimator()
        estimator.fit(records)
        with self._lock:
            self._estimator = estimator
        logger.info(
            "Warm-started with {} records, model={}",
            len(records),
            estimator.model_type(),
        )
