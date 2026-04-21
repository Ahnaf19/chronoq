"""SimPy discrete-event simulator for benchmarking job schedulers.

Architecture:
- Jobs arrive according to a Poisson process driven by the trace's arrival_ms times.
- A single server processes one job at a time (single-worker queue model).
- The active scheduler picks which waiting job to run next via ``select()``.
- Per-job telemetry (arrival, start, end, true_ms) is recorded for metric computation.

Scheduler interface (BaseScheduler):
    select(waiting: list[Job]) -> Job
        Called whenever the server becomes free and ≥1 job is waiting.
        Returns the job to run next.

Optional preemption hook (for future true-SRPT):
    on_arrival(env, waiting, running) -> bool
        Called when a new job arrives while the server is busy.
        Return True to interrupt the current job; False to leave it running.
        Default implementation always returns False (non-preemptive).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import simpy

if TYPE_CHECKING:
    from collections.abc import Generator

    from simpy import Environment


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Job:
    """A job instance inside the simulator (extends TraceJob with sim state)."""

    job_id: str
    task_type: str
    payload_size: int
    true_ms: float
    arrival_ms: float
    priority: int = 0

    # Filled in by the simulator at runtime
    start_ms: float = 0.0
    end_ms: float = 0.0
    remaining_ms: float = field(init=False)

    def __post_init__(self) -> None:
        self.remaining_ms = self.true_ms

    @property
    def jct_ms(self) -> float:
        """Job completion time = end_ms - arrival_ms."""
        return self.end_ms - self.arrival_ms

    @property
    def wait_ms(self) -> float:
        """Queue wait time = start_ms - arrival_ms."""
        return self.start_ms - self.arrival_ms


@dataclass
class SimResult:
    """Output of a single simulation run."""

    scheduler_name: str
    jobs: list[Job]

    @property
    def jct_ms(self) -> list[float]:
        return [j.jct_ms for j in self.jobs]

    @property
    def wait_ms(self) -> list[float]:
        return [j.wait_ms for j in self.jobs]


# ---------------------------------------------------------------------------
# Scheduler interface
# ---------------------------------------------------------------------------


class BaseScheduler(ABC):
    """Pluggable scheduling policy for the simulator."""

    @abstractmethod
    def select(self, waiting: list[Job]) -> Job:
        """Choose the next job to run from the waiting queue.

        Called exactly when the server becomes free and ``waiting`` is non-empty.
        Implementations must not modify ``waiting`` in place — the simulator
        removes the returned job.
        """

    def on_arrival(
        self,
        env: Environment,  # noqa: ARG002
        waiting: list[Job],  # noqa: ARG002
        running: Job | None,  # noqa: ARG002
    ) -> bool:
        """Hook called when a new job arrives while the server is busy.

        Return True to preempt the running job (future SRPT use).
        Default is False — non-preemptive.
        """
        return False

    @property
    @abstractmethod
    def name(self) -> str:
        """Short label for results.json and plot legends."""


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------


class Simulator:
    """Discrete-event simulator: Poisson arrivals, single-server queue.

    Args:
        scheduler:  Scheduling policy (any BaseScheduler subclass).
        seed:       RNG seed for reproducibility (default 42).
    """

    def __init__(self, scheduler: BaseScheduler, seed: int = 42) -> None:
        self._scheduler = scheduler
        self._seed = seed

    def run(self, jobs_in: list[Job]) -> SimResult:
        """Replay ``jobs_in`` through the simulator and return per-job telemetry."""
        env = simpy.Environment()
        completed: list[Job] = []
        waiting: list[Job] = []
        running: list[Job | None] = [None]  # mutable ref
        busy: list[bool] = [False]

        # Sort by arrival so we process in order
        arrivals = sorted(jobs_in, key=lambda j: j.arrival_ms)

        def _dispatch() -> None:
            """Start the next waiting job if the server is free."""
            if not busy[0] and waiting:
                next_job = self._scheduler.select(waiting)
                waiting.remove(next_job)
                env.process(_run_job(next_job))

        def _run_job(job: Job) -> Generator:
            busy[0] = True
            job.start_ms = env.now
            running[0] = job
            yield env.timeout(job.true_ms)
            job.end_ms = env.now
            job.remaining_ms = 0.0
            running[0] = None
            busy[0] = False
            completed.append(job)
            # Event-driven: immediately pick next job without polling
            _dispatch()

        def _arrival_process() -> Generator:
            for job in arrivals:
                delay = max(0.0, job.arrival_ms - env.now)
                yield env.timeout(delay)
                waiting.append(job)
                if busy[0]:
                    self._scheduler.on_arrival(env, list(waiting), running[0])
                _dispatch()

        env.process(_arrival_process())
        env.run()

        return SimResult(scheduler_name=self._scheduler.name, jobs=completed)
