"""LearnedScheduler — pre-broker gate with fifo / shadow / active modes.

Celery's broker (Redis LISTS) offers no "select next task" hook at the protocol level.
LearnedScheduler acts as a pre-broker gate: callers pass an ``apply_fn`` (the function
that actually enqueues/executes a task) alongside the task metadata. In active mode,
tasks are held in an in-process min-heap scored by predicted duration and dispatched
in score order via ``dispatch_next()``, which is called from the task_success signal.

Modes:
    fifo   — tasks are dispatched immediately; ranker is never instantiated.
    shadow — tasks are scored and logged but dispatched in arrival order.
    active — tasks are held in a heap and dispatched in score order.
"""

from __future__ import annotations

import heapq
import threading
import time
from collections import Counter
from typing import TYPE_CHECKING, Literal

from chronoq_ranker import TaskRanker
from chronoq_ranker.schemas import QueueContext, TaskCandidate
from loguru import logger

from .rolling import TypeStatsTracker

if TYPE_CHECKING:
    from collections.abc import Callable

    from chronoq_ranker.config import RankerConfig

SchedulerMode = Literal["fifo", "shadow", "active"]


class LearnedScheduler:
    """Pre-broker scheduling gate with three operating modes.

    Args:
        mode:           "fifo" | "shadow" | "active"
        ranker:         Pre-initialised TaskRanker. If None, one is created when
                        mode != "fifo" (lazy init on first submit).
        ranker_config:  Passed to TaskRanker() if ``ranker`` is None.
        stats_tracker:  Shared TypeStatsTracker. Created internally if not provided.
        window:         Ring-buffer size for TypeStatsTracker (when created internally).
    """

    def __init__(
        self,
        mode: SchedulerMode = "fifo",
        ranker: TaskRanker | None = None,
        ranker_config: RankerConfig | None = None,
        stats_tracker: TypeStatsTracker | None = None,
        window: int = 100,
    ) -> None:
        self._mode: SchedulerMode = mode
        self._ranker_config = ranker_config
        self._lock = threading.Lock()

        if mode == "fifo":
            self._ranker: TaskRanker | None = None
            self._extractor = None
        else:
            self._ranker = ranker or TaskRanker(config=ranker_config)
            self._extractor = self._ranker._extractor  # type: ignore[attr-defined]

        self._stats: TypeStatsTracker = stats_tracker or TypeStatsTracker(window=window)

        # In-process heap: (score, arrival_order, apply_fn, task_id)
        self._heap: list[tuple[float, int, Callable, str]] = []
        self._arrival_counter: int = 0

        # Registry: task_id → {task_type, payload_size, start_ms}
        self._registry: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def mode(self) -> SchedulerMode:
        return self._mode

    def submit(
        self,
        task_type: str,
        payload_size: int,
        apply_fn: Callable,
        task_id: str | None = None,
    ) -> str:
        """Submit a task for scheduling.

        Args:
            task_type:    Task category string (e.g. "resize", "transcode").
            payload_size: Input payload size in bytes.
            apply_fn:     Zero-argument callable that enqueues/executes the task.
            task_id:      Optional caller-supplied ID; a unique string is generated if None.

        Returns:
            The task_id used internally.
        """
        import uuid

        tid = task_id or str(uuid.uuid4())

        if self._mode == "fifo":
            apply_fn()
            return tid

        score = self._score(tid, task_type, payload_size)

        if self._mode == "shadow":
            logger.debug(
                "shadow score task_id={} task_type={} payload_size={} score={:.4f}",
                tid,
                task_type,
                payload_size,
                score,
            )
            apply_fn()
            return tid

        # active mode — push to heap
        with self._lock:
            if tid in self._registry:
                raise ValueError(f"task_id already registered: {tid!r}")
            seq = self._arrival_counter
            self._arrival_counter += 1
            heapq.heappush(self._heap, (score, seq, apply_fn, tid))
            self._registry[tid] = {
                "task_type": task_type,
                "payload_size": payload_size,
                "start_ms": None,
            }

        return tid

    def dispatch_next(self) -> bool:
        """Pop the highest-priority task from the heap and call its apply_fn.

        Returns True if a task was dispatched, False if the heap is empty.
        The apply_fn is called OUTSIDE the lock to avoid reentrancy issues.
        """
        with self._lock:
            if not self._heap:
                return False
            _score, _seq, apply_fn, task_id = heapq.heappop(self._heap)

        apply_fn()
        logger.debug("dispatch_next dispatched task_id={}", task_id)
        return True

    def record_start(self, task_id: str, task_type: str, payload_size: int) -> None:
        """Record the moment a task begins execution (called from task_prerun signal)."""
        with self._lock:
            entry = self._registry.get(task_id)
            if entry is None:
                self._registry[task_id] = {
                    "task_type": task_type,
                    "payload_size": payload_size,
                    "start_ms": time.monotonic() * 1000,
                }
            else:
                entry["start_ms"] = time.monotonic() * 1000

    def record_completion(self, task_id: str, task_type: str, payload_size: int) -> float | None:
        """Compute actual_ms and update stats + ranker.

        Called from the task_success signal. Returns actual_ms or None on miss.
        """
        now_ms = time.monotonic() * 1000
        with self._lock:
            entry = self._registry.pop(task_id, None)

        if entry is None or entry.get("start_ms") is None:
            logger.warning("record_completion: no registry entry for task_id={}", task_id)
            return None

        actual_ms = now_ms - entry["start_ms"]

        self._stats.record(task_type, actual_ms)

        if self._ranker is not None:
            mean, p95, count = self._stats.snapshot(task_type)
            with self._lock:
                queue_depth = len(self._heap)
                same_type_depth = sum(
                    1
                    for _, _, _, tid in self._heap
                    if self._registry.get(tid, {}).get("task_type") == task_type
                )
            self._ranker.record(
                task_type=task_type,
                payload_size=payload_size,
                actual_ms=actual_ms,
                metadata={
                    "recent_mean_ms_this_type": mean,
                    "recent_p95_ms_this_type": p95,
                    "recent_count_this_type": count,
                    "queue_depth": queue_depth,
                    "queue_depth_same_type": same_type_depth,
                },
            )

        return actual_ms

    def cleanup_registry(self, task_id: str) -> None:
        """Remove a failed task from the registry without calling ranker.record."""
        with self._lock:
            self._registry.pop(task_id, None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _score(self, task_id: str, task_type: str, payload_size: int) -> float:
        """Score a single task using the trained estimator + live TypeStatsTracker."""
        if self._ranker is None or self._extractor is None:
            return 0.0

        mean, p95, count = self._stats.snapshot(task_type)

        with self._ranker._lock:  # type: ignore[attr-defined]
            estimator = self._ranker._estimator  # type: ignore[attr-defined]

        with self._lock:
            queue_depth = len(self._heap)
            same_type_count = Counter(
                self._registry.get(t, {}).get("task_type", "")
                for t in (item[3] for item in self._heap)
            ).get(task_type, 0)

        cand = TaskCandidate(
            task_id=task_id,
            task_type=task_type,
            features={"payload_size": float(payload_size)},
        )
        ctx = QueueContext(
            queue_depth=queue_depth,
            queue_depth_same_type=same_type_count,
            recent_mean_ms_this_type=mean,
            recent_p95_ms_this_type=p95,
            recent_count_this_type=count,
        )
        features = self._extractor.extract(cand, context=ctx)
        result = estimator.predict_batch([features])
        return float(result[0][0])
