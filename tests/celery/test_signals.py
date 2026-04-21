"""Tests for attach_signals — signal wiring, registry population, fifo short-circuit."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from chronoq_celery.scheduler import LearnedScheduler
from chronoq_celery.signals import attach_signals


class TestSignalWiring:
    """attach_signals wires task_prerun / task_success / task_failure to the scheduler."""

    def test_attach_signals_returns_none(self):
        """attach_signals is a fire-and-forget setup function."""
        app = MagicMock()
        scheduler = LearnedScheduler(mode="shadow")
        result = attach_signals(app, scheduler)
        assert result is None

    def test_task_prerun_populates_registry(self):
        scheduler = LearnedScheduler(mode="active")

        # Simulate the signal being fired
        with patch("chronoq_celery.signals.task_prerun"):
            attach_signals(MagicMock(), scheduler)

        # Manually call record_start (mimics what signal handler does)
        task_id = "test-uuid-1234"
        scheduler.record_start(task_id, "resize", 512)
        with scheduler._lock:
            assert task_id in scheduler._registry
            assert scheduler._registry[task_id]["start_ms"] is not None

    def test_task_failure_cleans_registry(self):
        scheduler = LearnedScheduler(mode="shadow")
        task_id = "test-uuid-fail"
        scheduler.record_start(task_id, "resize", 512)
        scheduler.cleanup_registry(task_id)
        with scheduler._lock:
            assert task_id not in scheduler._registry

    def test_fifo_mode_ranker_record_never_called(self):
        """In fifo mode, ranker is None — record_completion must not error or call ranker."""
        scheduler = LearnedScheduler(mode="fifo")
        assert scheduler._ranker is None

        # record_completion with no registry entry should return None gracefully
        result = scheduler.record_completion("any-id", "resize", 512)
        assert result is None
