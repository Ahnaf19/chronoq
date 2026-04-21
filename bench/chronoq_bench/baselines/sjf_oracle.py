"""Shortest-Job-First oracle — uses true_ms (non-preemptive)."""

from __future__ import annotations

from chronoq_bench.simulator import BaseScheduler, Job


class SJFOracleScheduler(BaseScheduler):
    """Run the shortest job first. Uses ground-truth duration — oracle only."""

    @property
    def name(self) -> str:
        return "sjf_oracle"

    def select(self, waiting: list[Job]) -> Job:
        return min(waiting, key=lambda j: j.true_ms)
