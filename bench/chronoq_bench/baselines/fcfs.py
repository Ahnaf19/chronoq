"""First-Come First-Served (FCFS) baseline — the queue default."""

from __future__ import annotations

from chronoq_bench.simulator import BaseScheduler, Job


class FCFSScheduler(BaseScheduler):
    """Run jobs in arrival order."""

    @property
    def name(self) -> str:
        return "fcfs"

    def select(self, waiting: list[Job]) -> Job:
        return min(waiting, key=lambda j: j.arrival_ms)
