"""Synthetic Pareto-distributed trace generator.

Heavy-tail durations are the regime where SJF (and LambdaRank) gains the most
over FCFS. Using Pareto guarantees a known structure so exit criteria are
verifiable before relying on BurstGPT.

All randomness seeded via ``seed`` parameter (default 42) for reproducibility.
"""

from __future__ import annotations

import random

import numpy as np

from chronoq_bench.traces.base import TraceJob, TraceLoader

# Task type profiles: (mean_log_ms, sigma_log) — log-normal base duration
_TASK_PROFILES: dict[str, tuple[float, float]] = {
    "resize": (3.0, 0.4),  # ~20ms
    "analyze": (4.5, 0.4),  # ~90ms
    "compress": (5.0, 0.4),  # ~150ms
    "encode": (6.0, 0.4),  # ~400ms
    "transcode": (7.5, 0.4),  # ~1800ms
}

_TASK_TYPES = list(_TASK_PROFILES)


class SyntheticTraceLoader(TraceLoader):
    """Pareto-shaped job trace with task-type-correlated durations.

    Duration = lognormal(mu_for_type + payload_factor, sigma) where
    payload_factor = log1p(payload_kb) * 0.3.  This ensures both ``task_type``
    and ``payload_size`` are genuine predictors — the same signal the ranker
    is trained to exploit.

    Arrivals follow a Poisson process with rate ``arrival_rate_per_ms``.
    """

    def __init__(
        self,
        n_jobs: int = 5000,
        arrival_rate_per_ms: float = 0.05,
        seed: int = 42,
    ) -> None:
        self._n = n_jobs
        self._rate = arrival_rate_per_ms
        self._seed = seed

    @property
    def name(self) -> str:
        return "synthetic_pareto"

    def load(self, n: int | None = None) -> list[TraceJob]:
        import math

        rng = random.Random(self._seed)
        np_rng = np.random.default_rng(self._seed)

        total = n if n is not None else self._n
        jobs: list[TraceJob] = []
        arrival_ms = 0.0

        for i in range(total):
            # Poisson inter-arrival: exponential with mean = 1/rate
            inter = -math.log(rng.random()) / self._rate
            arrival_ms += inter

            task_type = rng.choice(_TASK_TYPES)
            payload_size = rng.randint(100, 10000)
            mu, sigma = _TASK_PROFILES[task_type]
            payload_factor = math.log1p(payload_size / 1000) * 0.3
            true_ms = max(1.0, float(np_rng.lognormal(mu + payload_factor, sigma)))

            jobs.append(
                TraceJob(
                    job_id=f"syn-{i:06d}",
                    task_type=task_type,
                    payload_size=payload_size,
                    true_ms=true_ms,
                    arrival_ms=arrival_ms,
                )
            )

        return jobs
