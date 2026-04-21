"""Tests for predict_scores() and the v2 batch-ranking types.

Covers behavior callers depend on before LambdaRank lands in Chunk 1 W3:
empty input, sort-stability by score, rank field monotonicity, and shape
of ScoredTask vs the current (heuristic) estimator.
"""

from chronoq_ranker import (
    DEFAULT_SCHEMA_V1,
    DefaultExtractor,
    FeatureSchema,
    QueueContext,
    RankerConfig,
    ScoredTask,
    TaskCandidate,
    TaskRanker,
)


def _ranker() -> TaskRanker:
    cfg = RankerConfig(
        cold_start_threshold=10,
        retrain_every_n=20,
        storage_uri="memory://",
    )
    return TaskRanker(config=cfg)


def test_predict_scores_empty_list_returns_empty() -> None:
    ranker = _ranker()
    assert ranker.predict_scores([]) == []


def test_predict_scores_returns_sorted_shortest_first() -> None:
    ranker = _ranker()
    # Seed with clearly-separable data so the heuristic has opinions.
    for _ in range(5):
        ranker.record("small", payload_size=10, actual_ms=100.0)
    for _ in range(5):
        ranker.record("large", payload_size=10, actual_ms=10_000.0)
    # Explicit retrain — auto-retrain only fires at retrain_every_n (20 here).
    ranker.retrain()

    candidates = [
        TaskCandidate(task_id="c-large", task_type="large"),
        TaskCandidate(task_id="c-small", task_type="small"),
    ]
    scored = ranker.predict_scores(candidates)

    assert len(scored) == 2
    # "small" should score lower (shorter predicted duration) → rank 0.
    assert scored[0].task_id == "c-small"
    assert scored[0].rank == 0
    assert scored[1].task_id == "c-large"
    assert scored[1].rank == 1
    assert scored[0].score < scored[1].score


def test_scored_task_shape() -> None:
    ranker = _ranker()
    scored = ranker.predict_scores([TaskCandidate(task_id="t", task_type="x")])
    assert len(scored) == 1
    s = scored[0]
    assert isinstance(s, ScoredTask)
    assert s.task_id == "t"
    assert s.rank == 0
    assert s.model_type in {"heuristic", "gradient_boosting", "lambdarank"}
    assert s.model_version  # non-empty string


def test_predict_scores_group_id_accepted_and_ignored_today() -> None:
    """W2 accepts group_id but doesn't use it; W3 LambdaRank will."""
    ranker = _ranker()
    result_a = ranker.predict_scores([TaskCandidate(task_id="t", task_type="x")], group_id=None)
    result_b = ranker.predict_scores(
        [TaskCandidate(task_id="t", task_type="x")], group_id="batch-42"
    )
    # Same estimator, same feature dict (modulo wall-clock) → same ranks.
    assert result_a[0].rank == result_b[0].rank == 0


def test_default_extractor_emits_all_15_features() -> None:
    extractor = DefaultExtractor()
    features = extractor.extract(
        TaskCandidate(
            task_id="t",
            task_type="resize",
            features={"payload_size": 1024, "prompt_length": 42, "retry_count": 1},
        ),
        QueueContext(queue_depth=3, worker_count_busy=2),
    )
    expected = set(DEFAULT_SCHEMA_V1.numeric) | set(DEFAULT_SCHEMA_V1.categorical)
    assert set(features.keys()) == expected
    assert len(expected) == 15
    # Null-safe defaults for missing fields.
    assert features["user_tier"] == "__unknown__"
    assert features["time_since_last_retrain_s"] == 0.0


def test_default_extractor_symmetric_record_extraction() -> None:
    """extract_from_record should produce the same keyset as extract()."""
    from chronoq_ranker import TaskRecord

    extractor = DefaultExtractor()
    at_score_time = extractor.extract(TaskCandidate(task_id="t", task_type="x"))
    at_train_time = extractor.extract_from_record(
        TaskRecord(task_type="x", payload_size=0, actual_ms=100.0)
    )
    assert at_score_time.keys() == at_train_time.keys()


def test_feature_schema_version_round_trip() -> None:
    schema = FeatureSchema(
        version="custom-v0",
        numeric=["a", "b"],
        categorical=["c"],
        required=["a"],
    )
    dumped = schema.model_dump()
    restored = FeatureSchema(**dumped)
    assert restored.version == "custom-v0"
    assert restored.numeric == ["a", "b"]
    assert restored.categorical == ["c"]
    assert restored.required == ["a"]


def test_feature_extractor_is_injectable() -> None:
    """Callers can pass a custom FeatureExtractor; default is DefaultExtractor."""
    from chronoq_ranker.features import FeatureExtractor

    class MinimalExtractor(FeatureExtractor):
        schema = FeatureSchema(
            version="min-v0", numeric=["payload_size"], categorical=["task_type"]
        )

        def extract(self, candidate, context=None):  # type: ignore[override]
            return {"task_type": candidate.task_type, "payload_size": 0.0}

        def extract_from_record(self, record):  # type: ignore[override]
            return {"task_type": record.task_type, "payload_size": float(record.payload_size)}

    ranker = TaskRanker(
        config=RankerConfig(storage_uri="memory://"),
        feature_extractor=MinimalExtractor(),
    )
    scored = ranker.predict_scores([TaskCandidate(task_id="t", task_type="x")])
    assert len(scored) == 1
