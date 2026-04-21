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
