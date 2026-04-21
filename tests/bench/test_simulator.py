"""Tests for the SimPy discrete-event simulator and baseline schedulers."""

import pytest
from chronoq_bench.baselines.fcfs import FCFSScheduler
from chronoq_bench.baselines.priority_fcfs import PriorityFCFSScheduler
from chronoq_bench.baselines.random_sched import RandomScheduler
from chronoq_bench.baselines.sjf_oracle import SJFOracleScheduler
from chronoq_bench.baselines.srpt_oracle import SRPTOracleScheduler
from chronoq_bench.metrics.jct import mean_jct, p99_jct
from chronoq_bench.simulator import Job, Simulator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jobs(
    n: int,
    true_ms: float = 100.0,
    arrival_gap_ms: float = 10.0,
) -> list[Job]:
    """n identical jobs arriving evenly spaced."""
    return [
        Job(
            job_id=f"j{i}",
            task_type="test",
            payload_size=100,
            true_ms=true_ms,
            arrival_ms=float(i * arrival_gap_ms),
        )
        for i in range(n)
    ]


def _make_mixed_jobs(n_short: int = 10, n_long: int = 10) -> list[Job]:
    """Alternating short (10ms) and long (1000ms) jobs at 1ms intervals."""
    jobs = []
    for i in range(n_short + n_long):
        is_short = i % 2 == 0
        jobs.append(
            Job(
                job_id=f"j{i}",
                task_type="short" if is_short else "long",
                payload_size=100,
                true_ms=10.0 if is_short else 1000.0,
                arrival_ms=float(i),
            )
        )
    return jobs


# ---------------------------------------------------------------------------
# Simulator sanity — queuing theory verification
# ---------------------------------------------------------------------------


def test_fcfs_sanity_all_jobs_complete() -> None:
    """All submitted jobs must be in the result."""
    jobs = _make_jobs(20)
    result = Simulator(FCFSScheduler()).run(jobs)
    assert len(result.jobs) == 20


def test_fcfs_jct_positive() -> None:
    jobs = _make_jobs(10)
    result = Simulator(FCFSScheduler()).run(jobs)
    assert all(j.jct_ms > 0 for j in result.jobs)


def test_fcfs_end_after_start() -> None:
    jobs = _make_jobs(10)
    result = Simulator(FCFSScheduler()).run(jobs)
    assert all(j.end_ms >= j.start_ms for j in result.jobs)


def test_fcfs_start_after_arrival() -> None:
    jobs = _make_jobs(10)
    result = Simulator(FCFSScheduler()).run(jobs)
    assert all(j.start_ms >= j.arrival_ms for j in result.jobs)


def test_fcfs_queuing_theory_identical_jobs() -> None:
    """100 identical 100ms jobs arriving every 200ms (load=0.5).

    With load < 1, mean JCT ≈ true_ms (no queueing delay).
    """
    # arrival_gap=200ms, true_ms=100ms → load=0.5 → mean wait ≈ 0
    jobs = _make_jobs(n=100, true_ms=100.0, arrival_gap_ms=200.0)
    result = Simulator(FCFSScheduler()).run(jobs)
    assert mean_jct(result.jct_ms) == pytest.approx(100.0, rel=0.05)


# ---------------------------------------------------------------------------
# Scheduler ordering invariants
# ---------------------------------------------------------------------------


def test_sjf_beats_fcfs_mean_jct() -> None:
    """SJF always produces lower or equal mean JCT than FCFS on mixed loads."""
    jobs = _make_mixed_jobs(n_short=20, n_long=20)
    fcfs = Simulator(FCFSScheduler()).run(jobs)
    sjf = Simulator(SJFOracleScheduler()).run(jobs)
    assert mean_jct(sjf.jct_ms) <= mean_jct(fcfs.jct_ms)


def test_sjf_beats_fcfs_p99_jct() -> None:
    jobs = _make_mixed_jobs(n_short=20, n_long=20)
    fcfs = Simulator(FCFSScheduler()).run(jobs)
    sjf = Simulator(SJFOracleScheduler()).run(jobs)
    assert p99_jct(sjf.jct_ms) <= p99_jct(fcfs.jct_ms)


def test_srpt_beats_fcfs_mean_jct() -> None:
    jobs = _make_mixed_jobs(n_short=20, n_long=20)
    fcfs = Simulator(FCFSScheduler()).run(jobs)
    srpt = Simulator(SRPTOracleScheduler()).run(jobs)
    assert mean_jct(srpt.jct_ms) <= mean_jct(fcfs.jct_ms)


def test_random_scheduler_completes_all_jobs() -> None:
    jobs = _make_jobs(20)
    result = Simulator(RandomScheduler(seed=42)).run(jobs)
    assert len(result.jobs) == 20


def test_priority_fcfs_high_priority_runs_first() -> None:
    """When two jobs are waiting, the higher-priority one must be picked first."""
    jobs = [
        Job(
            job_id="runner",
            task_type="t",
            payload_size=100,
            true_ms=500.0,
            arrival_ms=0.0,
            priority=1,
        ),
        Job(
            job_id="low_waiter",
            task_type="t",
            payload_size=100,
            true_ms=100.0,
            arrival_ms=1.0,
            priority=1,
        ),
        Job(
            job_id="high_waiter",
            task_type="t",
            payload_size=100,
            true_ms=100.0,
            arrival_ms=2.0,
            priority=9,
        ),
    ]
    result = Simulator(PriorityFCFSScheduler()).run(jobs)
    by_id = {j.job_id: j for j in result.jobs}
    # When runner finishes, high_waiter (priority=9) should start before low_waiter (priority=1)
    assert by_id["high_waiter"].start_ms < by_id["low_waiter"].start_ms


# ---------------------------------------------------------------------------
# Scheduler names
# ---------------------------------------------------------------------------


def test_scheduler_names() -> None:
    assert FCFSScheduler().name == "fcfs"
    assert SJFOracleScheduler().name == "sjf_oracle"
    assert SRPTOracleScheduler().name == "srpt_oracle"
    assert RandomScheduler().name == "random"
    assert PriorityFCFSScheduler().name == "priority_fcfs"


def test_sim_result_scheduler_name() -> None:
    result = Simulator(FCFSScheduler()).run(_make_jobs(5))
    assert result.scheduler_name == "fcfs"
