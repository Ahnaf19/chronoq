"""Random scheduler — lower bound / sanity check baseline."""

from __future__ import annotations

import random

from chronoq_bench.simulator import BaseScheduler, Job


class RandomScheduler(BaseScheduler):
    """Pick a random waiting job. Seeded for reproducibility."""

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)

    @property
    def name(self) -> str:
        return "random"

    def select(self, waiting: list[Job]) -> Job:
        return self._rng.choice(waiting)
