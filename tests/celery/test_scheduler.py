"""Tests for LearnedScheduler — fifo/shadow/active modes, heap dispatch, registry."""

from __future__ import annotations

from unittest.mock import patch

from chronoq_celery.rolling import TypeStatsTracker
from chronoq_celery.scheduler import LearnedScheduler


class TestFifoMode:
    def test_fifo_calls_apply_fn_immediately(self):
        scheduler = LearnedScheduler(mode="fifo")
        called = []
        scheduler.submit("resize", 1024, lambda: called.append(1))
        assert called == [1]

    def test_fifo_ranker_never_instantiated(self):
        scheduler = LearnedScheduler(mode="fifo")
        assert scheduler._ranker is None
        assert scheduler._extractor is None

    def test_fifo_dispatch_next_always_false(self):
        scheduler = LearnedScheduler(mode="fifo")
        result = scheduler.dispatch_next()
        assert result is False

    def test_fifo_multiple_submits_in_order(self):
        scheduler = LearnedScheduler(mode="fifo")
        order = []
        scheduler.submit("resize", 1024, lambda: order.append("a"))
        scheduler.submit("transcode", 2048, lambda: order.append("b"))
        assert order == ["a", "b"]


class TestShadowMode:
    def test_shadow_calls_apply_fn_in_arrival_order(self):
        stats = TypeStatsTracker()
        stats.seed({"resize": 100.0, "transcode": 5000.0})
        scheduler = LearnedScheduler(mode="shadow", stats_tracker=stats)

        order = []
        scheduler.submit("transcode", 4096, lambda: order.append("first"))
        scheduler.submit("resize", 512, lambda: order.append("second"))
        # Shadow preserves arrival order regardless of score
        assert order == ["first", "second"]

    def test_shadow_ranker_is_instantiated(self):
        scheduler = LearnedScheduler(mode="shadow")
        assert scheduler._ranker is not None

    def test_shadow_mode_property(self):
        scheduler = LearnedScheduler(mode="shadow")
        assert scheduler.mode == "shadow"


class TestActiveMode:
    def _make_seeded_scheduler(self, type_means: dict[str, float]) -> LearnedScheduler:
        """Create a trained active-mode scheduler with seeded stats."""
        from chronoq_ranker import TaskRanker
        from chronoq_ranker.config import RankerConfig

        config = RankerConfig(
            cold_start_threshold=10,
            retrain_every_n=50,
            storage_uri="memory://",
            min_groups=5,
        )
        ranker = TaskRanker(config=config)
        stats = TypeStatsTracker()
        stats.seed(type_means)
        return LearnedScheduler(mode="active", ranker=ranker, stats_tracker=stats)

    def test_active_heap_is_populated_on_submit(self):
        scheduler = LearnedScheduler(mode="active")
        scheduler.submit("resize", 1024, lambda: None)
        with scheduler._lock:
            assert len(scheduler._heap) == 1

    def test_active_dispatch_next_returns_true_when_task_waiting(self):
        scheduler = LearnedScheduler(mode="active")
        called = []
        scheduler.submit("resize", 1024, lambda: called.append(1))
        result = scheduler.dispatch_next()
        assert result is True
        assert called == [1]

    def test_active_dispatch_next_returns_false_on_empty_heap(self):
        scheduler = LearnedScheduler(mode="active")
        assert scheduler.dispatch_next() is False

    def test_active_heap_cleared_after_dispatch(self):
        scheduler = LearnedScheduler(mode="active")
        scheduler.submit("resize", 1024, lambda: None)
        scheduler.dispatch_next()
        with scheduler._lock:
            assert len(scheduler._heap) == 0

    def test_active_score_order_low_score_first(self):
        """Tasks with lower predicted score should dispatch before higher-scored ones.

        We mock _score so the test covers heap/dispatch logic without needing a
        trained model — scoring correctness is covered by the ranker tests.
        """
        scheduler = LearnedScheduler(mode="active")
        # Deterministic scores: "short" task gets 10.0, "long" gets 10000.0
        call_count = [0]

        def fake_score(task_id, task_type, payload_size):
            call_count[0] += 1
            return 10.0 if task_type == "short" else 10000.0

        scheduler._score = fake_score

        order = []
        scheduler.submit("long", 1024, lambda: order.append("long"))
        scheduler.submit("short", 512, lambda: order.append("short"))

        scheduler.dispatch_next()
        scheduler.dispatch_next()

        # Short-duration task (score=10.0) should dispatch before long (score=10000.0)
        assert order[0] == "short"

    def test_active_mode_property(self):
        scheduler = LearnedScheduler(mode="active")
        assert scheduler.mode == "active"


class TestRecordCompletion:
    def test_record_completion_updates_stats(self):
        stats = TypeStatsTracker()
        scheduler = LearnedScheduler(mode="shadow", stats_tracker=stats)
        task_id = scheduler.submit("resize", 1024, lambda: None)
        scheduler.record_start(task_id, "resize", 1024)
        scheduler.record_completion(task_id, "resize", 1024)
        _, _, count = stats.snapshot("resize")
        assert count >= 1

    def test_record_completion_missing_entry_returns_none(self):
        scheduler = LearnedScheduler(mode="shadow")
        result = scheduler.record_completion("nonexistent", "resize", 1024)
        assert result is None

    def test_cleanup_registry_removes_entry(self):
        scheduler = LearnedScheduler(mode="active")
        task_id = scheduler.submit("resize", 1024, lambda: None)
        scheduler.record_start(task_id, "resize", 1024)
        scheduler.cleanup_registry(task_id)
        with scheduler._lock:
            assert task_id not in scheduler._registry

    def test_record_completion_calls_ranker_record(self):
        scheduler = LearnedScheduler(mode="shadow")
        task_id = scheduler.submit("resize", 1024, lambda: None)
        scheduler.record_start(task_id, "resize", 1024)

        with patch.object(scheduler._ranker, "record") as mock_record:
            scheduler.record_completion(task_id, "resize", 1024)
            mock_record.assert_called_once()

    def test_cleanup_registry_no_ranker_record(self):
        """task_failure: cleanup_registry is called; ranker.record must NOT be called."""
        scheduler = LearnedScheduler(mode="shadow")
        task_id = scheduler.submit("resize", 1024, lambda: None)
        scheduler.record_start(task_id, "resize", 1024)

        with patch.object(scheduler._ranker, "record") as mock_record:
            scheduler.cleanup_registry(task_id)
            mock_record.assert_not_called()
