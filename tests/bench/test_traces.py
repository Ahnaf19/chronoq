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
    task_type is binned from output_length: llm_short (<100), llm_medium (100-400),
    llm_long (>400). All three types must be present in the stratified 100-row fixture.
    """
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from chronoq_bench.traces.burstgpt import BurstGPTLoader

    valid_types = {"llm_short", "llm_medium", "llm_long"}
    jobs = BurstGPTLoader().load()
    assert len(jobs) > 0, "BurstGPTLoader offline should return at least 1 job"
    assert all(isinstance(j, TraceJob) for j in jobs)
    assert all(j.task_type in valid_types for j in jobs), (
        f"Unexpected task types: {set(j.task_type for j in jobs) - valid_types}"
    )
    assert all(j.true_ms > 0.0 for j in jobs)
    assert all(j.payload_size > 0 for j in jobs)


def test_burstgpt_task_type_binning_coverage(monkeypatch) -> None:
    """CI fixture must contain at least one job of each task type (stratified sample)."""
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from collections import Counter

    from chronoq_bench.traces.burstgpt import BurstGPTLoader

    jobs = BurstGPTLoader().load()
    counts = Counter(j.task_type for j in jobs)
    assert counts["llm_short"] > 0, "No llm_short jobs in CI fixture"
    assert counts["llm_medium"] > 0, "No llm_medium jobs in CI fixture"
    assert counts["llm_long"] > 0, "No llm_long jobs in CI fixture"


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


# ---------------------------------------------------------------------------
# AzureLoader (offline mode only in CI)
# ---------------------------------------------------------------------------


def test_azure_loader_offline_sample_loads(monkeypatch) -> None:
    """Committed CI fixture loads cleanly and returns exactly 100 TraceJobs."""
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from chronoq_bench.traces.azure import AzureLoader

    loader = AzureLoader()
    jobs = loader.load()
    assert len(jobs) == 100
    assert all(isinstance(j, TraceJob) for j in jobs)


def test_azure_loader_offline_positive_durations(monkeypatch) -> None:
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from chronoq_bench.traces.azure import AzureLoader

    jobs = AzureLoader().load()
    assert all(j.true_ms > 0.0 for j in jobs)


def test_azure_loader_offline_load_n(monkeypatch) -> None:
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from chronoq_bench.traces.azure import AzureLoader

    jobs = AzureLoader().load(n=20)
    assert len(jobs) == 20


def test_azure_loader_name() -> None:
    from chronoq_bench.traces.azure import AzureLoader

    assert AzureLoader().name == "azure"


def test_azure_loader_schema_validation(monkeypatch) -> None:
    """Loader raises ValueError when required columns are missing from cache."""
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    import pandas as pd
    import pytest
    from chronoq_bench.traces.azure import AzureLoader

    loader = AzureLoader()
    bad_df = pd.DataFrame({"foo": [1, 2, 3]})
    with pytest.raises(ValueError, match="missing required columns"):
        loader._validate_schema(bad_df)


def test_azure_loader_trigger_in_metadata(monkeypatch) -> None:
    """Each TraceJob must carry its trigger type in metadata."""
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from chronoq_bench.traces.azure import AzureLoader

    jobs = AzureLoader().load()
    assert all("trigger" in j.metadata for j in jobs)
    valid_triggers = {"http", "timer", "queue", "event", "storage", "orchestration", "others"}
    assert all(j.metadata["trigger"] in valid_triggers for j in jobs)


def test_azure_loader_multi_type_diversity(monkeypatch) -> None:
    """Azure CI sample must contain multiple unique task_types (serverless functions)."""
    monkeypatch.setenv("CHRONOQ_BENCH_OFFLINE", "1")
    from chronoq_bench.traces.azure import AzureLoader

    jobs = AzureLoader().load()
    unique_types = {j.task_type for j in jobs}
    # Azure has thousands of HashFunction values; even 100 rows should have many types
    assert len(unique_types) >= 10, (
        f"Expected >=10 unique task_types in Azure CI fixture, got {len(unique_types)}"
    )
