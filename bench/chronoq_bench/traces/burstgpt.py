"""BurstGPT trace loader.

Downloads the BurstGPT dataset from HuggingFace on first run and caches it
as a local parquet file.  Set ``CHRONOQ_BENCH_OFFLINE=1`` to skip the download
and use the committed 100-row CI sample instead.

BurstGPT paper: https://arxiv.org/abs/2401.17644
HF dataset: lzzmm/BurstGPT
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

# Required columns in the BurstGPT dataset.
# Fail loudly if these change between dataset revisions.
_REQUIRED_COLS = {"request_id", "timestamp", "input_length", "output_length", "duration_ms"}


# Mapping BurstGPT columns → TraceJob fields
class BurstGPTLoader(TraceLoader):
    """Load BurstGPT LLM request traces as TraceJob sequences.

    Durations are real end-to-end latencies from a production LLM service —
    heavy-tailed, with a 50–500× spread between fast cache hits and long
    generation requests.
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

        path = hf_hub_download(
            repo_id="lzzmm/BurstGPT",
            filename="BurstGPT.csv",
            repo_type="dataset",
            local_dir=str(DATA_DIR),
        )
        df = pd.read_csv(path)
        df = self._normalise(df)
        df.to_parquet(BURSTGPT_CACHE_PATH, index=False)
        logger.info("BurstGPT: cached {} rows to {}", len(df), BURSTGPT_CACHE_PATH)
        return df

    def _normalise(self, df):
        """Rename BurstGPT columns to the expected schema."""
        rename = {}
        # BurstGPT columns vary by version; try common patterns
        col_lower = {c.lower(): c for c in df.columns}
        candidates = {
            "request_id": ["request_id", "id", "req_id"],
            "timestamp": ["timestamp", "time", "arrival_time", "start_time"],
            "input_length": ["input_length", "prompt_length", "input_tokens"],
            "output_length": ["output_length", "completion_length", "output_tokens"],
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
        if "duration_ms" not in df.columns and "duration" in df.columns:
            df["duration_ms"] = df["duration"] * 1000  # assume seconds
        if "input_length" not in df.columns:
            df["input_length"] = 512
        if "output_length" not in df.columns:
            df["output_length"] = 128

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
        jobs = []
        for row in df.itertuples(index=False):
            jobs.append(
                TraceJob(
                    job_id=str(row.request_id),
                    task_type="llm_request",
                    payload_size=int(getattr(row, "input_length", 512)),
                    true_ms=max(1.0, float(row.duration_ms)),
                    arrival_ms=float(getattr(row, "timestamp", 0.0)),
                    metadata={
                        "output_length": int(getattr(row, "output_length", 128)),
                    },
                )
            )
        return jobs
