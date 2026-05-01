"""Mooncake cross-provider LLM trace loader (Kimi FAST'25, synthetic CI fixture).

The Mooncake paper ("Mooncake: A KVCache-centric Disaggregated Architecture for
LLM Serving", Qin et al., FAST'25) describes a cross-provider prefill/decode
disaggregation system deployed on Kimi (moonshot-ai).  The public dataset is
not freely redistributable as a downloadable parquet; this loader always uses
the committed 100-row synthetic CI fixture.

Fixture generation (``bench/fixtures/mooncake_ci_sample.parquet``):
    rng = np.random.default_rng(42)
    output_tokens drawn uniformly per bin:
        kv_short  — [10,  100)  tokens   (36 rows, mirrors BurstGPT P65)
        kv_medium — [100, 500)  tokens   (40 rows, mirrors BurstGPT P25–P90)
        kv_long   — [500, 2000) tokens   (24 rows, mirrors BurstGPT top 10%)

Duration formula (deterministic, no noise):
    duration_ms = 20.0 + 8.0 * output_tokens

Constants:
    20.0 ms — base TTFT overhead (network + prefill dispatch latency)
    8.0 ms  — per-token decode rate at Mooncake target hardware utilisation

Both ``output_tokens`` and ``input_tokens`` are observable at job-submit time
in systems that expose token-count estimates (e.g. speculative decoding, prompt
caching).  The formula is therefore not a data-leakage risk.

Task-type binning gives ``recent_mean_ms_this_type`` discriminative signal:
    kv_short  — output_tokens < 100   (mean duration ~(20+8*55)=460 ms)
    kv_medium — 100 ≤ output_tokens < 500  (mean ~(20+8*300)=2420 ms)
    kv_long   — output_tokens ≥ 500   (mean ~(20+8*1250)=10020 ms)

Smoke mode note:
    The synthetic CI fixture only has 100 rows.  ``jct_vs_load`` smoke mode
    uses ``n_train=60, n_eval=30`` when ``trace == "mooncake"`` to stay within
    the 100-row budget.  Full-run mode uses the same fixture; callers wanting
    a larger corpus should supply a real Mooncake dataset and update this loader.
"""

from __future__ import annotations

from loguru import logger

from chronoq_bench.traces.base import TraceJob, TraceLoader
from chronoq_bench.traces.cache import MOONCAKE_CI_SAMPLE_PATH

# Required columns in the CI fixture parquet.
_REQUIRED_COLS = {
    "request_id",
    "input_tokens",
    "output_tokens",
    "duration_ms",
    "arrival_ms",
    "task_type",
}


class MooncakeLoader(TraceLoader):
    """Load the Mooncake synthetic CI fixture as TraceJob sequences.

    This loader is CI-fixture-only: it always reads
    ``bench/fixtures/mooncake_ci_sample.parquet`` (100 rows, committed).
    There is no live download path in this release.

    Duration formula: ``duration_ms = 20.0 + 8.0 * output_tokens``.
    Task types: ``kv_short`` / ``kv_medium`` / ``kv_long`` (binned by output_tokens).
    """

    def __init__(self, max_rows: int | None = None) -> None:
        self._max_rows = max_rows

    @property
    def name(self) -> str:
        return "mooncake"

    def load(self, n: int | None = None) -> list[TraceJob]:
        """Return up to ``n`` TraceJob records from the CI fixture.

        Args:
            n: Maximum number of jobs to return.  When ``None``, all 100
               fixture rows are returned.  Requesting more than 100 rows raises
               ``ValueError`` — callers must respect the fixture budget.

        Returns:
            List of TraceJob instances with ``true_ms`` set from the
            deterministic formula, arrival times from the fixture, and
            task_type from the three-bin scheme.

        Raises:
            FileNotFoundError: If the CI fixture parquet is not present.
            ValueError: If the fixture is missing required columns, or if
                ``n`` exceeds the fixture row count.
        """
        limit = n if n is not None else self._max_rows
        df = self._load_fixture(limit)
        return self._to_trace_jobs(df)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_fixture(self, limit: int | None):
        import pandas as pd

        if not MOONCAKE_CI_SAMPLE_PATH.exists():
            raise FileNotFoundError(
                f"Mooncake CI fixture not found at {MOONCAKE_CI_SAMPLE_PATH}. "
                "Re-checkout bench/fixtures/mooncake_ci_sample.parquet from the repo."
            )

        logger.info("Mooncake: loading CI fixture ({})", MOONCAKE_CI_SAMPLE_PATH)
        df = pd.read_parquet(MOONCAKE_CI_SAMPLE_PATH)
        self._validate_schema(df)

        if limit is not None:
            if limit > len(df):
                raise ValueError(
                    f"Requested {limit} rows from Mooncake fixture but fixture only has "
                    f"{len(df)} rows.  Reduce n_train + n_eval for this trace."
                )
            df = df.head(limit)

        logger.info("Mooncake: loaded {} rows", len(df))
        return df

    def _validate_schema(self, df) -> None:
        missing = _REQUIRED_COLS - set(df.columns)
        if missing:
            raise ValueError(
                f"Mooncake CI fixture is missing required columns: {missing}. "
                "Regenerate the fixture by running the generation snippet in "
                "bench/chronoq_bench/traces/mooncake.py."
            )

    def _to_trace_jobs(self, df) -> list[TraceJob]:
        jobs = []
        for row in df.itertuples(index=False):
            jobs.append(
                TraceJob(
                    job_id=str(row.request_id),
                    task_type=str(row.task_type),
                    payload_size=int(row.input_tokens),
                    true_ms=max(1.0, float(row.duration_ms)),
                    arrival_ms=float(row.arrival_ms),
                    metadata={
                        "output_tokens": int(row.output_tokens),
                    },
                )
            )
        return jobs
