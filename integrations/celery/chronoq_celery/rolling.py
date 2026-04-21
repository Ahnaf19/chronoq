"""Per-type rolling statistics tracker for the Celery integration.

TypeStatsTracker maintains a bounded ring buffer of recent actual_ms values
per task_type. It provides (mean, p95, count) snapshots used to populate
QueueContext.recent_mean_ms_this_type at scoring time.
"""

from __future__ import annotations

import threading
from collections import deque

import numpy as np


class TypeStatsTracker:
    """Thread-safe per-type ring buffer of recent actual_ms observations.

    Args:
        window: Maximum number of completions to retain per task_type.
    """

    def __init__(self, window: int = 100) -> None:
        self._window = window
        self._data: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def record(self, task_type: str, actual_ms: float) -> None:
        """Record a completed task's duration."""
        with self._lock:
            if task_type not in self._data:
                self._data[task_type] = deque(maxlen=self._window)
            self._data[task_type].append(actual_ms)

    def snapshot(self, task_type: str) -> tuple[float, float, int]:
        """Return (mean_ms, p95_ms, count) for the given task_type.

        Returns (0.0, 0.0, 0) for unseen types — callers treat 0.0 as "unknown".
        """
        with self._lock:
            buf = self._data.get(task_type)
            if not buf:
                return 0.0, 0.0, 0
            arr = np.array(buf, dtype=np.float64)

        mean = float(np.mean(arr))
        p95 = float(np.percentile(arr, 95))
        count = len(arr)
        return mean, p95, count

    def seed(self, type_means: dict[str, float]) -> None:
        """Pre-warm the tracker with known per-type means (single synthetic observation each).

        Used in demo.py to avoid cold-start during the active benchmark after pre-training.
        """
        for task_type, mean_ms in type_means.items():
            with self._lock:
                if task_type not in self._data:
                    self._data[task_type] = deque(maxlen=self._window)
                self._data[task_type].append(mean_ms)
