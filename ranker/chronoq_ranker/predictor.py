"""TaskPredictor — orchestrates prediction, recording, and model retraining."""

import threading

from loguru import logger

from chronoq_ranker.config import PredictorConfig
from chronoq_ranker.features import extract_features
from chronoq_ranker.models.gradient import GradientEstimator
from chronoq_ranker.models.heuristic import HeuristicEstimator
from chronoq_ranker.schemas import PredictionResult, RetrainResult, TaskRecord
from chronoq_ranker.storage import TelemetryStore, create_store


class TaskPredictor:
    """Main entry point: predict task duration, record actuals, auto-retrain."""

    def __init__(
        self,
        config: PredictorConfig | None = None,
        storage: TelemetryStore | str | None = None,
    ) -> None:
        self._config = config or PredictorConfig()

        if isinstance(storage, str):
            self._store = create_store(storage)
        elif storage is not None:
            self._store = storage
        else:
            self._store = create_store(self._config.storage_uri)

        self._estimator = HeuristicEstimator()
        self._lock = threading.Lock()
        self._previous_model_type: str = "heuristic"

        # Warm-start from existing data
        if self._store.count() > 0:
            self._warm_start()

    def predict(
        self, task_type: str, payload_size: int, metadata: dict | None = None
    ) -> PredictionResult:
        """Predict execution time for a task."""
        features = extract_features(task_type, payload_size, metadata)

        with self._lock:
            estimator = self._estimator

        estimated_ms, confidence = estimator.predict(features)

        return PredictionResult(
            estimated_ms=estimated_ms,
            confidence=confidence,
            model_version=estimator.version(),
            model_type=estimator.model_type(),
        )

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
