"""Shortest Remaining Processing Time oracle — non-preemptive approximation.

True SRPT preempts the running job when a shorter one arrives; that requires
SimPy process interrupts and remaining-time tracking (~60 extra LOC with subtle
correctness risks).  This implementation re-sorts the queue on every selection
using true_ms as a proxy for remaining time.  It is a tighter upper bound than
SJF on queues where jobs arrive mid-flight, but not as tight as true preemptive
SRPT.

Documented as "SRPT-approx" in bench/artifacts/results.json and BENCHMARKS.md.
"""

from __future__ import annotations

from chronoq_bench.simulator import BaseScheduler, Job


class SRPTOracleScheduler(BaseScheduler):
    """Non-preemptive SRPT: always run the job with the shortest true_ms next."""

    @property
    def name(self) -> str:
        return "srpt_oracle"

    def select(self, waiting: list[Job]) -> Job:
        return min(waiting, key=lambda j: j.true_ms)
