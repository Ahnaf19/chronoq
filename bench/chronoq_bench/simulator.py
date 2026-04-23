"""SimPy discrete-event simulator for benchmarking job schedulers.

Architecture:
- Jobs arrive according to a Poisson process driven by the trace's arrival_ms times.
- A ``simpy.Resource`` with ``capacity=n_workers`` models one or more parallel workers
  pulling from a shared waiting queue (the common Celery deployment pattern).
- Whenever a worker slot becomes free and ≥1 job is waiting, the active scheduler's
  ``select()`` is called to pick the next job.
- Per-job telemetry (arrival, start, end, true_ms) is recorded for metric computation.

Worker model:
- ``n_workers=1`` (default) reproduces the original single-server queue behaviour —
  all existing baselines and tests run unchanged.
- ``n_workers>1`` runs jobs concurrently across parallel workers. Each worker is
  still non-preemptive per-job (same semantics as a single Celery worker process);
  preemption of a running job would have to happen on one specific worker.

Scheduler interface (BaseScheduler):
    select(waiting: list[Job]) -> Job
        Called whenever a worker slot becomes free and ≥1 job is waiting.
        Returns the job to run next. With ``n_workers=N``, ``select()`` is called
        once per job (exactly ``len(jobs)`` times across the run).

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

        Called exactly when a worker slot becomes free and ``waiting`` is non-empty.
        Implementations must not modify ``waiting`` in place — the simulator
        removes the returned job.
        """

    def on_arrival(
        self,
        env: Environment,  # noqa: ARG002
        waiting: list[Job],  # noqa: ARG002
        running: Job | None,  # noqa: ARG002
    ) -> bool:
        """Hook called when a new job arrives while any worker is busy.

        Return True to preempt a running job (future SRPT use).
        Default is False — non-preemptive.

        With ``n_workers>1``, ``running`` is the most recently started job. The
        hook is invoked whenever at least one worker is busy at arrival time.
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
    """Discrete-event simulator: Poisson arrivals, N parallel workers.

    Args:
        scheduler: Scheduling policy (any BaseScheduler subclass).
        seed: RNG seed for reproducibility (default 42).
        n_workers: Number of parallel workers pulling from the shared queue
            (default 1, matching the original single-server behaviour). Represents
            e.g. ``celery -c N`` worker concurrency. Must be ≥1.

    Raises:
        ValueError: if ``n_workers < 1``.
    """

    def __init__(
        self,
        scheduler: BaseScheduler,
        seed: int = 42,
        n_workers: int = 1,
    ) -> None:
        if n_workers < 1:
            raise ValueError(f"n_workers must be ≥ 1, got {n_workers}")
        self._scheduler = scheduler
        self._seed = seed
        self._n_workers = n_workers

    @property
    def n_workers(self) -> int:
        return self._n_workers

    def run(self, jobs_in: list[Job]) -> SimResult:
        """Replay ``jobs_in`` through the simulator and return per-job telemetry."""
        env = simpy.Environment()
        workers = simpy.Resource(env, capacity=self._n_workers)
        completed: list[Job] = []
        waiting: list[Job] = []
        # Track currently running jobs (used for the on_arrival hook). With
        # capacity=N this grows to at most N entries.
        running: list[Job] = []

        # Sort by arrival so we process in order
        arrivals = sorted(jobs_in, key=lambda j: j.arrival_ms)

        def _worker_proc(job: Job) -> Generator:
            """Acquire a worker slot, run the job, release.

            The scheduler picks *which* waiting job runs on this slot at the
            moment the slot is acquired — not at enqueue time. That way an
            arrival at t=5 can overtake an arrival at t=3 that is still sitting
            in the waiting list because all workers were busy at t=3.
            """
            with workers.request() as req:
                yield req
                # Slot acquired — choose the next job to run from waiting.
                # The ``job`` argument is just the most-recent arrival that
                # triggered this process; the scheduler gets full visibility
                # into ``waiting``.
                chosen = self._scheduler.select(waiting)
                waiting.remove(chosen)
                chosen.start_ms = env.now
                running.append(chosen)
                yield env.timeout(chosen.true_ms)
                chosen.end_ms = env.now
                chosen.remaining_ms = 0.0
                running.remove(chosen)
                completed.append(chosen)

        def _arrival_process() -> Generator:
            for job in arrivals:
                delay = max(0.0, job.arrival_ms - env.now)
                yield env.timeout(delay)
                waiting.append(job)
                if running:
                    # One or more workers are busy — fire preemption hook with
                    # the most recently started job as the "running" reference.
                    self._scheduler.on_arrival(env, list(waiting), running[-1])
                env.process(_worker_proc(job))

        env.process(_arrival_process())
        env.run()

        return SimResult(scheduler_name=self._scheduler.name, jobs=completed)
