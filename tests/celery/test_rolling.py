"""Tests for TypeStatsTracker — ring buffer, thread safety, stats accuracy."""

from __future__ import annotations

import threading

import numpy as np
import pytest
from chronoq_celery.rolling import TypeStatsTracker


class TestTypeStatsTrackerBasic:
    def test_unseen_type_returns_zeros(self):
        tracker = TypeStatsTracker()
        mean, p95, count = tracker.snapshot("unknown_type")
        assert mean == 0.0
        assert p95 == 0.0
        assert count == 0

    def test_single_observation(self):
        tracker = TypeStatsTracker()
        tracker.record("resize", 100.0)
        mean, p95, count = tracker.snapshot("resize")
        assert mean == pytest.approx(100.0)
        assert count == 1

    def test_mean_accuracy(self):
        tracker = TypeStatsTracker()
        values = [100.0, 200.0, 300.0]
        for v in values:
            tracker.record("resize", v)
        mean, _, count = tracker.snapshot("resize")
        assert mean == pytest.approx(200.0)
        assert count == 3

    def test_p95_accuracy(self):
        tracker = TypeStatsTracker()
        # 100 observations; p95 should be near the high end
        for i in range(100):
            tracker.record("transcode", float(i))
        _, p95, _ = tracker.snapshot("transcode")
        expected = float(np.percentile(list(range(100)), 95))
        assert p95 == pytest.approx(expected, rel=1e-3)

    def test_window_eviction(self):
        tracker = TypeStatsTracker(window=5)
        for i in range(10):
            tracker.record("resize", float(i * 100))
        _, _, count = tracker.snapshot("resize")
        # Only the last 5 observations should be retained
        assert count == 5

    def test_window_eviction_affects_mean(self):
        tracker = TypeStatsTracker(window=3)
        for v in [1.0, 2.0, 3.0, 100.0, 200.0, 300.0]:
            tracker.record("resize", v)
        mean, _, count = tracker.snapshot("resize")
        assert count == 3
        assert mean == pytest.approx((100.0 + 200.0 + 300.0) / 3)

    def test_multiple_types_independent(self):
        tracker = TypeStatsTracker()
        tracker.record("resize", 50.0)
        tracker.record("transcode", 500.0)
        mean_r, _, _ = tracker.snapshot("resize")
        mean_t, _, _ = tracker.snapshot("transcode")
        assert mean_r == pytest.approx(50.0)
        assert mean_t == pytest.approx(500.0)

    def test_thread_safety(self):
        tracker = TypeStatsTracker(window=200)
        errors: list[Exception] = []

        def writer():
            try:
                for _ in range(50):
                    tracker.record("resize", 100.0)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(50):
                    tracker.snapshot("resize")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        threads += [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"

    def test_seed_pre_warms_tracker(self):
        tracker = TypeStatsTracker()
        tracker.seed({"resize": 57.0, "transcode": 3220.0})
        mean_r, _, count_r = tracker.snapshot("resize")
        mean_t, _, count_t = tracker.snapshot("transcode")
        assert mean_r == pytest.approx(57.0)
        assert count_r == 1
        assert mean_t == pytest.approx(3220.0)
        assert count_t == 1
