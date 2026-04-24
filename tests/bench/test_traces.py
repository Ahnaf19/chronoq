"""Tests for trace loaders."""

from chronoq_bench.traces.base import TraceJob
from chronoq_bench.traces.synthetic import SyntheticTraceLoader

# ---------------------------------------------------------------------------
# SyntheticTraceLoader
# ---------------------------------------------------------------------------


def test_synthetic_returns_requested_count() -> None:
    loader = SyntheticTraceLoader(n_jobs=100)
    jobs = loader.load()
    assert len(jobs) == 100


def test_synthetic_load_n_override() -> None:
    loader = SyntheticTraceLoader(n_jobs=500)
    jobs = loader.load(n=50)
    assert len(jobs) == 50


def test_synthetic_jobs_are_trace_jobs() -> None:
    loader = SyntheticTraceLoader(n_jobs=10)
    jobs = loader.load()
    assert all(isinstance(j, TraceJob) for j in jobs)


def test_synthetic_arrivals_are_non_decreasing() -> None:
    loader = SyntheticTraceLoader(n_jobs=200)
    jobs = loader.load()
    arrivals = [j.arrival_ms for j in jobs]
    assert arrivals == sorted(arrivals)


def test_synthetic_true_ms_positive() -> None:
    loader = SyntheticTraceLoader(n_jobs=100)
    jobs = loader.load()
    assert all(j.true_ms > 0.0 for j in jobs)


def test_synthetic_task_types_are_valid() -> None:
    valid = {"resize", "analyze", "compress", "encode", "transcode"}
    loader = SyntheticTraceLoader(n_jobs=200, seed=42)
    jobs = loader.load()
    assert all(j.task_type in valid for j in jobs)


def test_synthetic_seeded_reproducible() -> None:
    a = SyntheticTraceLoader(n_jobs=50, seed=42).load()
    b = SyntheticTraceLoader(n_jobs=50, seed=42).load()
    assert [j.true_ms for j in a] == [j.true_ms for j in b]


def test_synthetic_different_seeds_differ() -> None:
    a = SyntheticTraceLoader(n_jobs=50, seed=42).load()
    b = SyntheticTraceLoader(n_jobs=50, seed=99).load()
    assert [j.true_ms for j in a] != [j.true_ms for j in b]


def test_synthetic_has_duration_spread() -> None:
    """Pareto-like trace must have high variance — p99/p50 ratio > 5."""
    loader = SyntheticTraceLoader(n_jobs=1000, seed=42)
    jobs = loader.load()
    durations = sorted(j.true_ms for j in jobs)
    p50 = durations[500]
    p99 = durations[990]
    assert p99 / p50 > 5.0


def test_synthetic_name() -> None:
    assert SyntheticTraceLoader().name == "synthetic_pareto"


# ---------------------------------------------------------------------------
# BurstGPTLoader (offline mode only in CI)
# ---------------------------------------------------------------------------


def test_burstgpt_ci_sample_loads(monkeypatch) -> None:
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from chronoq_bench.traces.burstgpt import BurstGPTLoader

    loader = BurstGPTLoader()
    jobs = loader.load()
    assert len(jobs) == 100
    assert all(isinstance(j, TraceJob) for j in jobs)


def test_burstgpt_ci_sample_positive_durations(monkeypatch) -> None:
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from chronoq_bench.traces.burstgpt import BurstGPTLoader

    jobs = BurstGPTLoader().load()
    assert all(j.true_ms > 0.0 for j in jobs)


def test_burstgpt_ci_sample_load_n(monkeypatch) -> None:
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from chronoq_bench.traces.burstgpt import BurstGPTLoader

    jobs = BurstGPTLoader().load(n=20)
    assert len(jobs) == 20


def test_burstgpt_name() -> None:
    from chronoq_bench.traces.burstgpt import BurstGPTLoader

    assert BurstGPTLoader().name == "burstgpt"


def test_burstgpt_loader_offline_sample_loads(monkeypatch) -> None:
    """Validate that CHRONOQ_BENCH_OFFLINE=1 + BurstGPTLoader() returns a non-empty
    list of TraceJob from the committed CI fixture at bench/fixtures/burstgpt_ci_sample.parquet.

    This is the canonical offline gate: every CI run must exercise this path.
    Later commits in this branch update the assertions for the multi-type binning.
    """
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from chronoq_bench.traces.burstgpt import BurstGPTLoader

    jobs = BurstGPTLoader().load()
    assert len(jobs) > 0, "BurstGPTLoader offline should return at least 1 job"
    assert all(isinstance(j, TraceJob) for j in jobs)
    assert all(j.true_ms > 0.0 for j in jobs)
    assert all(j.payload_size > 0 for j in jobs)


# ---------------------------------------------------------------------------
# BorgLoader (offline mode only in CI)
# ---------------------------------------------------------------------------


def test_borg_loader_offline_sample_loads(monkeypatch) -> None:
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from chronoq_bench.traces.borg import BorgLoader

    loader = BorgLoader()
    jobs = loader.load()
    assert len(jobs) == 100
    assert all(isinstance(j, TraceJob) for j in jobs)


def test_borg_loader_offline_positive_durations(monkeypatch) -> None:
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from chronoq_bench.traces.borg import BorgLoader

    jobs = BorgLoader().load()
    assert all(j.true_ms > 0.0 for j in jobs)


def test_borg_loader_offline_load_n(monkeypatch) -> None:
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from chronoq_bench.traces.borg import BorgLoader

    jobs = BorgLoader().load(n=20)
    assert len(jobs) == 20


def test_borg_loader_name() -> None:
    from chronoq_bench.traces.borg import BorgLoader

    assert BorgLoader().name == "borg"


def test_borg_loader_schema_validation(monkeypatch) -> None:
    """Loader must raise ValueError when required columns are missing."""
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    import pandas as pd
    import pytest
    from chronoq_bench.traces.borg import BorgLoader

    loader = BorgLoader()
    # Patch _get_dataframe to return a frame missing required columns
    bad_df = pd.DataFrame({"foo": [1, 2, 3]})
    with pytest.raises(ValueError, match="missing required columns"):
        loader._validate_schema(bad_df)


def test_borg_loader_task_types_valid(monkeypatch) -> None:
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from chronoq_bench.traces.borg import _SCHED_CLASS_TO_TYPE, BorgLoader

    jobs = BorgLoader().load()
    valid_types = set(_SCHED_CLASS_TO_TYPE.values()) | {f"sched_class_{i}" for i in range(10)}
    assert all(j.task_type in valid_types for j in jobs)


def test_borg_loader_payload_size_positive(monkeypatch) -> None:
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from chronoq_bench.traces.borg import BorgLoader

    jobs = BorgLoader().load()
    assert all(j.payload_size >= 1 for j in jobs)
