"""Base types for trace loaders."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class TraceJob:
    """A single job in a benchmark trace.

    ``true_ms`` is the ground-truth execution time used by oracle baselines and
    for computing labels. It must NOT be passed to the learned ranker as a feature.
    ``arrival_ms`` is simulation time in ms from epoch 0.
    """

    job_id: str
    task_type: str
    payload_size: int
    true_ms: float
    arrival_ms: float = 0.0
    priority: int = 0
    metadata: dict = field(default_factory=dict)


class TraceLoader(ABC):
    """Load a sequence of TraceJob records for simulation."""

    @abstractmethod
    def load(self, n: int | None = None) -> list[TraceJob]:
        """Return up to ``n`` jobs (all jobs if n is None)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier used in results.json and plot legends."""
