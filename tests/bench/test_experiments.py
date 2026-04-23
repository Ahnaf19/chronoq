"""Tests for the jct_vs_load experiment driver.

These are the first tests to hit ``run_experiment()`` directly — CI ran the
smoke command but never unit-tested the return shape. With multi-seed + a
loader-agnostic signature shipping, locking in both the shape and
reproducibility behaviour prevents silent regressions when Wave 2 adds real
traces.
"""

from __future__ import annotations

import copy
import os
from typing import TYPE_CHECKING

import pytest
from chronoq_bench.experiments.jct_vs_load import run_experiment
from chronoq_bench.traces.base import TraceJob, TraceLoader
from chronoq_bench.traces.synthetic import SyntheticTraceLoader

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_smoke_env() -> Iterator[None]:
    """``main()`` inspects CHRONOQ_BENCH_SMOKE; these tests drive run_experiment
    directly with explicit args, so scrub the env var to avoid accidental
    cross-talk with developer shells that left it set."""
    prev = os.environ.pop("CHRONOQ_BENCH_SMOKE", None)
    try:
        yield
    finally:
        if prev is not None:
            os.environ["CHRONOQ_BENCH_SMOKE"] = prev


# A tiny fixed config that keeps per-test runtime under a few seconds each.
_TEST_KWARGS = dict(
    n_train=60,
    n_eval=40,
    load_points=[0.7],
)


class _RecordingLoader(TraceLoader):
    """TraceLoader that delegates to SyntheticTraceLoader but records calls.

    Used to prove ``run_experiment`` actually invokes the loader we pass in
    (rather than silently constructing a new SyntheticTraceLoader).
    """

    def __init__(self, inner: SyntheticTraceLoader, tag: str = "recording") -> None:
        self._inner = inner
        self._tag = tag
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._tag

    def load(self, n: int | None = None) -> list[TraceJob]:
        self.call_count += 1
        return self._inner.load(n=n)


# ---------------------------------------------------------------------------
# 1. Loader agnosticism
# ---------------------------------------------------------------------------


def test_run_experiment_accepts_loader() -> None:
    """Passing a custom TraceLoader threads through and its ``name`` shows up."""
    inner = SyntheticTraceLoader(n_jobs=200, seed=42)
    recording = _RecordingLoader(inner, tag="recording_loader_trace")

    data = run_experiment(**_TEST_KWARGS, seeds=[42], loader=recording)

    assert data["trace"] == "recording_loader_trace", "run_experiment should use loader.name"
    assert recording.call_count >= 1, "Custom loader was never asked to load data"


# ---------------------------------------------------------------------------
# 2. Multi-seed shape contract
# ---------------------------------------------------------------------------


def test_multi_seed_results_shape() -> None:
    """With 3 seeds, metric arrays must be list[list[float]] shape [n_load][3]."""
    seeds = [42, 43, 44]
    data = run_experiment(**_TEST_KWARGS, seeds=seeds)

    assert data["n_seeds"] == 3
    assert data["seeds"] == seeds
    load_pts = data["load_points"]

    for sched_name, metrics in data["schedulers"].items():
        for metric in ("mean_jct", "p99_jct", "hol_count"):
            arr = metrics[metric]
            assert len(arr) == len(load_pts), (
                f"{sched_name}.{metric} outer dim {len(arr)} != n_load_points {len(load_pts)}"
            )
            for col in arr:
                assert len(col) == len(seeds), (
                    f"{sched_name}.{metric} inner dim {len(col)} != n_seeds {len(seeds)}"
                )

            # Median mirror must be a flat list matching load_points
            median_arr = metrics[f"{metric}_median"]
            assert len(median_arr) == len(load_pts)
            assert all(isinstance(v, (int, float)) for v in median_arr)


def test_multi_seed_metadata_fields_present() -> None:
    """Contract for the downstream doc/notebook consumers."""
    data = run_experiment(**_TEST_KWARGS, seeds=[42, 43])

    # Both legacy and new fields present
    for key in (
        "trace",
        "seed",
        "seeds",
        "n_seeds",
        "feature_schema_version",
        "n_features",
        "load_points",
        "schedulers",
    ):
        assert key in data, f"missing top-level key: {key}"

    # feature_schema_version + n_features still required by bench/CLAUDE.md
    assert data["feature_schema_version"]
    assert data["n_features"] > 0


# ---------------------------------------------------------------------------
# 3. Smoke-mode parity (not the CLI wrapper — the library entry point)
# ---------------------------------------------------------------------------


def test_smoke_mode_single_seed() -> None:
    """CHRONOQ_BENCH_SMOKE=1 must leave run_experiment callable with 1 seed.

    main() does the smoke branching by env var, but run_experiment itself
    still needs to tolerate a single-seed call without collapsing the array
    shape — otherwise the smoke path can't write a valid results.json.
    """
    os.environ["CHRONOQ_BENCH_SMOKE"] = "1"
    try:
        data = run_experiment(**_TEST_KWARGS, seeds=[42])
    finally:
        os.environ.pop("CHRONOQ_BENCH_SMOKE", None)

    assert data["n_seeds"] == 1
    assert data["seeds"] == [42]

    # Shape is still [n_load][1] even with one seed
    for metrics in data["schedulers"].values():
        for metric in ("mean_jct", "p99_jct", "hol_count"):
            arr = metrics[metric]
            for col in arr:
                assert len(col) == 1


# ---------------------------------------------------------------------------
# 4. Reproducibility
# ---------------------------------------------------------------------------


def test_reproducibility_same_seed() -> None:
    """Two runs with the same seed list must produce byte-identical metrics.

    If this fails, check for un-seeded RNGs in the run_experiment path —
    the Reproducibility guardrail (±2% cross-machine) trusts that same-machine
    same-seed is bit-identical.
    """
    a = run_experiment(**_TEST_KWARGS, seeds=[42, 43])
    b = run_experiment(**_TEST_KWARGS, seeds=[42, 43])

    # Normalise away any dict ordering; compare deep structure
    a_sched = copy.deepcopy(a["schedulers"])
    b_sched = copy.deepcopy(b["schedulers"])

    assert a_sched == b_sched, "same-seed runs diverged — suspect an un-seeded RNG"
