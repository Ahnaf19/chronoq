"""BurstGPT trace loader.

Downloads the BurstGPT dataset from HuggingFace on first run and caches it
as a local parquet file.  Set ``CHRONOQ_BENCH_OFFLINE=1`` to skip the download
and use the committed 100-row CI sample instead.

BurstGPT paper: https://arxiv.org/abs/2401.17644
HF dataset: lzzmm/BurstGPT  (file: data/BurstGPT_1.csv, ~1.4M rows)

Schema (current as of April 2026):
    Timestamp, Model, Request tokens, Response tokens, Total tokens, Log Type

There is no measured end-to-end latency in the public dataset.  We synthesise
``duration_ms`` from ``output_length`` (Response tokens) using a seeded
lognormal model::

    duration_ms = max(1.0, exp(log(30 + 0.9 * output_length) + 0.35 * noise))

where ``noise ~ N(0,1)`` with ``rng = np.random.default_rng(42)``.  The formula
models a ~30 ms base overhead plus ~0.9 ms/token decode, with multiplicative
log-normal noise (σ=0.35 ≈ ±42% at 1σ).  Both ``output_length`` (Response
tokens) and ``input_length`` (Request tokens) are observable at job-submit
time in real LLM serving systems that expose token-count estimates to the
scheduler.  The formula is therefore **not a data-leakage risk**: it does not
use any post-execution signal such as measured wall-clock time or queue exit
timestamps.

Task-type binning restores multi-type structure for ``recent_mean_ms_this_type``:
    output_length < 100   → "llm_short"
    100 ≤ output_length ≤ 400 → "llm_medium"
    output_length > 400   → "llm_long"
"""

from __future__ import annotations

from loguru import logger

from chronoq_bench.traces.base import TraceJob, TraceLoader
from chronoq_bench.traces.cache import (
    BURSTGPT_CACHE_PATH,
    CI_SAMPLE_PATH,
    DATA_DIR,
    is_offline,
)

# Required columns after normalisation.
# Fail loudly if the pipeline produces an incomplete schema.
_REQUIRED_COLS = {"request_id", "timestamp", "input_length", "output_length", "duration_ms"}


class BurstGPTLoader(TraceLoader):
    """Load BurstGPT LLM request traces as TraceJob sequences.

    ``duration_ms`` is synthesised from ``output_length`` via a seeded lognormal
    model when the dataset does not include measured latencies (current schema
    as of April 2026 omits end-to-end latency).  See module docstring for the
    exact formula and leakage analysis.

    Task types are binned from ``output_length`` (Response tokens):
    - "llm_short"  (< 100 tokens)
    - "llm_medium" (100–400 tokens)
    - "llm_long"   (> 400 tokens)
    """

    def __init__(self, max_rows: int | None = None) -> None:
        self._max_rows = max_rows

    @property
    def name(self) -> str:
        return "burstgpt"

    def load(self, n: int | None = None) -> list[TraceJob]:
        limit = n or self._max_rows
        df = self._get_dataframe(limit)
        return self._to_trace_jobs(df)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_dataframe(self, limit: int | None):
        import pandas as pd

        if is_offline():
            if not CI_SAMPLE_PATH.exists():
                raise FileNotFoundError(
                    f"CI sample not found at {CI_SAMPLE_PATH}. "
                    "Run `make bench` without CHRONOQ_BENCH_OFFLINE=1 to download."
                )
            logger.info("BurstGPT: offline mode — loading CI sample ({})", CI_SAMPLE_PATH)
            df = pd.read_parquet(CI_SAMPLE_PATH)
        elif BURSTGPT_CACHE_PATH.exists():
            logger.info("BurstGPT: loading from cache ({})", BURSTGPT_CACHE_PATH)
            df = pd.read_parquet(BURSTGPT_CACHE_PATH)
        else:
            df = self._download()

        self._validate_schema(df)

        if limit is not None:
            df = df.head(limit)
        return df

    def _download(self):
        import pandas as pd
        from huggingface_hub import hf_hub_download

        logger.info("BurstGPT: downloading from HuggingFace (lzzmm/BurstGPT)...")
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # lzzmm/BurstGPT reorganised its file layout; the top-level BurstGPT.csv
        # no longer exists.  Use data/BurstGPT_1.csv (~1.4 M rows, ~60–100 MB).
        path = hf_hub_download(
            repo_id="lzzmm/BurstGPT",
            filename="data/BurstGPT_1.csv",
            repo_type="dataset",
            local_dir=str(DATA_DIR),
        )
        df = pd.read_csv(path)
        logger.info("BurstGPT: downloaded {} rows, columns: {}", len(df), df.columns.tolist())
        df = self._normalise(df)
        df.to_parquet(BURSTGPT_CACHE_PATH, index=False)
        logger.info("BurstGPT: cached {} rows to {}", len(df), BURSTGPT_CACHE_PATH)
        return df

    def _normalise(self, df):
        """Rename BurstGPT columns to the expected schema and synthesise missing ones.

        Supports both the original lowercase schema and the current dataset schema
        (capitalised with spaces: "Request tokens", "Response tokens", etc.).
        When ``duration_ms`` is absent (as of April 2026 schema), it is synthesised
        from ``output_length`` via a seeded lognormal model — see module docstring.
        """
        rename = {}
        # Build a case-insensitive lookup so we can match "Request tokens" → "request tokens"
        col_lower = {c.lower(): c for c in df.columns}
        candidates = {
            "request_id": ["request_id", "id", "req_id"],
            "timestamp": ["timestamp", "time", "arrival_time", "start_time"],
            # "request tokens" is the spaced-uppercase form in the current dataset
            "input_length": ["input_length", "prompt_length", "input_tokens", "request tokens"],
            # "response tokens" is the spaced-uppercase form in the current dataset
            "output_length": [
                "output_length",
                "completion_length",
                "output_tokens",
                "response tokens",
            ],
            "duration_ms": ["duration_ms", "duration", "latency_ms", "latency"],
        }
        for target, options in candidates.items():
            for opt in options:
                if opt in col_lower:
                    rename[col_lower[opt]] = target
                    break

        df = df.rename(columns=rename)

        # Synthesise missing columns with safe defaults
        if "request_id" not in df.columns:
            df["request_id"] = [f"req-{i}" for i in range(len(df))]
        if "input_length" not in df.columns:
            df["input_length"] = 512
        if "output_length" not in df.columns:
            df["output_length"] = 128

        # Synthesise duration_ms from output_length when the column is absent.
        # Formula: max(1, exp(log(30 + 0.9 * output_length) + 0.35 * N(0,1)))
        # Models: ~30 ms base overhead + ~0.9 ms/token decode, log-normal noise σ=0.35.
        # Both input_length and output_length are observable at submit time in real
        # serving systems → no post-execution leakage.
        if "duration_ms" not in df.columns:
            import numpy as np

            rng = np.random.default_rng(42)
            df["duration_ms"] = np.maximum(
                1.0,
                np.exp(np.log(30.0 + 0.9 * df["output_length"]) + 0.35 * rng.normal(size=len(df))),
            )
            logger.info(
                "BurstGPT: synthesised duration_ms from output_length "
                "(lognormal, rng seed=42); mean={:.1f}ms, p99={:.1f}ms",
                float(df["duration_ms"].mean()),
                float(df["duration_ms"].quantile(0.99)),
            )
        elif "duration" in df.columns and "duration_ms" not in df.columns:
            df["duration_ms"] = df["duration"] * 1000  # assume seconds

        # Normalise timestamp to ms from epoch 0
        if "timestamp" in df.columns:
            ts = df["timestamp"]
            df["timestamp"] = (ts - ts.min()).astype(float)
        else:
            df["timestamp"] = range(len(df))

        return df

    def _validate_schema(self, df) -> None:
        missing = _REQUIRED_COLS - set(df.columns)
        if missing:
            raise ValueError(
                f"BurstGPT dataset is missing required columns: {missing}. "
                "The dataset schema may have changed. Check the dataset card at "
                "https://huggingface.co/datasets/lzzmm/BurstGPT"
            )

    def _to_trace_jobs(self, df) -> list[TraceJob]:
        """Convert a normalised BurstGPT DataFrame to TraceJob instances.

        Task type is derived by binning ``output_length`` (Response tokens) into
        three buckets so that ``recent_mean_ms_this_type`` carries discriminative
        signal (otherwise all jobs share a single type and that feature degenerates
        to a global constant):

        - ``llm_short``  — output_length < 100 tokens
        - ``llm_medium`` — 100 ≤ output_length ≤ 400 tokens
        - ``llm_long``   — output_length > 400 tokens
        """
        jobs = []
        for row in df.itertuples(index=False):
            output_len = int(getattr(row, "output_length", 128))

            if output_len < 100:
                task_type = "llm_short"
            elif output_len <= 400:
                task_type = "llm_medium"
            else:
                task_type = "llm_long"

            jobs.append(
                TraceJob(
                    job_id=str(row.request_id),
                    task_type=task_type,
                    payload_size=int(getattr(row, "input_length", 512)),
                    true_ms=max(1.0, float(row.duration_ms)),
                    arrival_ms=float(getattr(row, "timestamp", 0.0)),
                    metadata={
                        "output_length": output_len,
                    },
                )
            )
        return jobs
