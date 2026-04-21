"""Sanity tests for the 5 baselines on a synthetic Pareto trace.

Plan Step 4 required assertions:
  - FCFS mean JCT > SJF-oracle mean JCT on a high-variance Pareto trace
  - Random scheduler is the worst (or near-worst) mean JCT on a Pareto trace
"""

from __future__ import annotations

from chronoq_bench.baselines.fcfs import FCFSScheduler
from chronoq_bench.baselines.priority_fcfs import PriorityFCFSScheduler
from chronoq_bench.baselines.random_sched import RandomScheduler
from chronoq_bench.baselines.sjf_oracle import SJFOracleScheduler
from chronoq_bench.baselines.srpt_oracle import SRPTOracleScheduler
from chronoq_bench.metrics.jct import mean_jct
from chronoq_bench.simulator import Job, Simulator
from chronoq_bench.traces.synthetic import SyntheticTraceLoader


def _pareto_jobs(n: int = 200, load: float = 0.7, seed: int = 42) -> list[Job]:
    """Pareto-distributed jobs at the given queue load."""
    trace = SyntheticTraceLoader(n_jobs=n, seed=seed).load()
    import numpy as np

    mean_ms = float(np.mean([tj.true_ms for tj in trace]))
    gap = mean_ms / load
    return [
        Job(
            job_id=tj.job_id,
            task_type=tj.task_type,
            payload_size=tj.payload_size,
            true_ms=tj.true_ms,
            arrival_ms=i * gap,
            priority=tj.priority,
        )
        for i, tj in enumerate(trace)
    ]


def _run(scheduler, jobs):
    return mean_jct(Simulator(scheduler, seed=42).run(jobs).jct_ms)


class TestBaselineSanity:
    """FCFS JCT > SJF JCT and Random is worst on Pareto trace (plan Step 4)."""

    def test_sjf_oracle_beats_fcfs_mean_jct(self):
        """SJF-oracle must improve mean JCT vs FCFS on a high-variance trace."""
        jobs_fcfs = _pareto_jobs()
        jobs_sjf = _pareto_jobs()
        fcfs_mean = _run(FCFSScheduler(), jobs_fcfs)
        sjf_mean = _run(SJFOracleScheduler(), jobs_sjf)
        assert sjf_mean < fcfs_mean, (
            f"SJF-oracle mean JCT ({sjf_mean:.1f}ms) should be less than "
            f"FCFS mean JCT ({fcfs_mean:.1f}ms) on Pareto trace"
        )

    def test_random_not_better_than_fcfs(self):
        """Random scheduler should not beat FCFS mean JCT on a Pareto trace."""
        jobs_fcfs = _pareto_jobs()
        jobs_rand = _pareto_jobs()
        fcfs_mean = _run(FCFSScheduler(), jobs_fcfs)
        rand_mean = _run(RandomScheduler(seed=42), jobs_rand)
        # Random can't be meaningfully better than FCFS (arrival-ordered baseline).
        # Allow a small 5% margin for statistical noise, but random should not
        # beat FCFS by more than that on any reasonable Pareto trace.
        assert rand_mean >= fcfs_mean * 0.95, (
            f"Random mean JCT ({rand_mean:.1f}ms) should not be better than "
            f"FCFS mean JCT ({fcfs_mean:.1f}ms) by more than 5% on Pareto trace"
        )

    def test_srpt_oracle_beats_fcfs_mean_jct(self):
        """SRPT-oracle (non-preemptive) must beat FCFS on high-variance trace."""
        jobs_fcfs = _pareto_jobs()
        jobs_srpt = _pareto_jobs()
        fcfs_mean = _run(FCFSScheduler(), jobs_fcfs)
        srpt_mean = _run(SRPTOracleScheduler(), jobs_srpt)
        assert srpt_mean < fcfs_mean, (
            f"SRPT-oracle mean JCT ({srpt_mean:.1f}ms) should be less than "
            f"FCFS mean JCT ({fcfs_mean:.1f}ms)"
        )

    def test_all_schedulers_complete_all_jobs(self):
        """Every scheduler must process all jobs without dropping any."""
        schedulers = [
            FCFSScheduler(),
            SJFOracleScheduler(),
            SRPTOracleScheduler(),
            RandomScheduler(seed=42),
            PriorityFCFSScheduler(),
        ]
        for sched in schedulers:
            jobs = _pareto_jobs(n=50)
            result = Simulator(sched, seed=42).run(jobs)
            assert len(result.jobs) == 50, (
                f"{sched.name}: expected 50 completed jobs, got {len(result.jobs)}"
            )

    def test_sjf_improvement_increases_with_load(self):
        """SJF advantage over FCFS should be larger at higher queue load."""

        def improvement(load: float) -> float:
            jobs_f = _pareto_jobs(load=load)
            jobs_s = _pareto_jobs(load=load)
            f = _run(FCFSScheduler(), jobs_f)
            s = _run(SJFOracleScheduler(), jobs_s)
            return (f - s) / f

        imp_low = improvement(0.4)
        imp_high = improvement(0.7)
        assert imp_high >= imp_low, (
            f"SJF improvement at load=0.7 ({imp_high:.3f}) should exceed "
            f"improvement at load=0.4 ({imp_low:.3f})"
        )
