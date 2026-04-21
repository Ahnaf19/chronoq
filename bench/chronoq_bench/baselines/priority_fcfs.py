"""Priority + FCFS baseline.

Jobs with higher ``priority`` values run first; ties broken by arrival order.
Mirrors Celery's static priority field (0–9, higher = more urgent).
"""

from __future__ import annotations

from chronoq_bench.simulator import BaseScheduler, Job


class PriorityFCFSScheduler(BaseScheduler):
    """Static priority scheduling, FCFS within the same priority level."""

    @property
    def name(self) -> str:
        return "priority_fcfs"

    def select(self, waiting: list[Job]) -> Job:
        return min(waiting, key=lambda j: (-j.priority, j.arrival_ms))
