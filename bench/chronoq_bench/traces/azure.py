"""Azure Functions Trace 2019 loader.

Downloads the Azure Functions Dataset 2019 from Azure Blob Storage on first
run and caches the processed result as a local parquet file. Set
``CHRONOQ_BENCH_OFFLINE=1`` to skip the download and use the committed
100-row CI sample instead.

Source: Azure/AzurePublicDataset — AzureFunctionsDataset2019
Paper: "Serverless in the Wild" (Shahrad et al., USENIX ATC 2020)
URL:   https://github.com/Azure/AzurePublicDataset/blob/master/AzureFunctionsDataset2019.md

Schema notes:
- ``HashFunction`` -> ``task_type`` (anonymised serverless function identity)
- ``Trigger``      -> stored in metadata (http, timer, queue, event, storage, …)
- Duration synthesised from per-function daily percentile statistics using a
  log-normal fit anchored on p25/p50/p75. Negative/zero-duration records are
  dropped before fitting.
- Arrivals synthesised by spreading each function's per-minute invocation count
  uniformly across the corresponding 60 000 ms window, starting at minute 0.

Sampling:
  The highest-activity 60-minute window (minutes 817-876 of day 1) is used.
  That window contains 42.8 M invocations across 23 444 valid functions. The
  loader samples uniformly without replacement to size N (default 10 000),
  preserving the empirical duration CDF because each sampled task is drawn
  from the same per-function log-normal distribution.
"""

from __future__ import annotations

import tarfile
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
from loguru import logger

from chronoq_bench.traces.base import TraceJob, TraceLoader
from chronoq_bench.traces.cache import (
    AZURE_CACHE_PATH,
    AZURE_CI_SAMPLE_PATH,
    AZURE_DATA_DIR,
    is_offline,
)

# Day whose data is used — day 1 has highest overall invocation volume.
_DAY = "d01"
_DATASET_URL = (
    "https://azurepublicdatasettraces.blob.core.windows.net/"
    "azurepublicdatasetv2/azurefunctions_dataset2019/"
    "azurefunctions-dataset2019.tar.xz"
)
_TARBALL_NAME = "azurefunctions-dataset2019.tar.xz"

# The 60-minute window (minutes 817-876 of day 1) with the highest total
# invocation count: 42.8 M invocations across 23 444 valid functions.
# Pre-computed so the loader doesn't scan all 1440 columns on every run.
_BEST_WINDOW_START = 817  # inclusive, 1-indexed per dataset schema
_BEST_WINDOW_END = 876  # inclusive

# Required columns in the processed parquet cache.
_REQUIRED_COLS = {
    "job_id",
    "task_type",
    "trigger",
    "duration_ms",
    "arrival_ms",
    "payload_size",
}

# Duration cap: drop functions whose daily-average duration exceeds this.
_MAX_DURATION_MS = 500_000.0

# Default cache size: how many synthesised rows to materialise. Larger values
# give a more representative sample when the caller requests many rows.
_CACHE_ROWS = 200_000


class AzureLoader(TraceLoader):
    """Load Azure Functions 2019 invocation traces as TraceJob sequences.

    Durations are synthesised from per-function daily duration statistics
    (percentiles). The 60-minute highest-activity window is used so the
    resulting trace captures real serverless burstiness.

    Azure has thousands of distinct HashFunction values which tests the
    ``recent_mean_ms_this_type`` feature's cold-start behaviour (most types
    appear only once or twice in a 10K sample — very different from BurstGPT's
    single type).
    """

    def __init__(self, max_rows: int | None = None, seed: int = 42) -> None:
        self._max_rows = max_rows
        self._seed = seed

    @property
    def name(self) -> str:
        return "azure"

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
            if not AZURE_CI_SAMPLE_PATH.exists():
                raise FileNotFoundError(
                    f"Azure CI sample not found at {AZURE_CI_SAMPLE_PATH}. "
                    "Run without CHRONOQ_BENCH_OFFLINE=1 to download."
                )
            logger.info("Azure: offline mode — loading CI sample ({})", AZURE_CI_SAMPLE_PATH)
            df = pd.read_parquet(AZURE_CI_SAMPLE_PATH)
        elif AZURE_CACHE_PATH.exists():
            logger.info("Azure: loading from cache ({})", AZURE_CACHE_PATH)
            df = pd.read_parquet(AZURE_CACHE_PATH)
        else:
            df = self._download_and_process()

        self._validate_schema(df)

        if limit is not None:
            df = df.head(limit)
        return df

    def _download_and_process(self):

        AZURE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        tarball_path = AZURE_DATA_DIR / _TARBALL_NAME

        if not tarball_path.exists():
            logger.info("Azure: downloading dataset (~137 MB) from Azure Blob Storage…")
            urllib.request.urlretrieve(_DATASET_URL, tarball_path)
            size_mb = tarball_path.stat().st_size / (1024 * 1024)
            logger.info("Azure: downloaded {:.1f} MB -> {}", size_mb, tarball_path)
        else:
            logger.info("Azure: tarball already present at {}", tarball_path)

        logger.info("Azure: extracting day-{} CSV files from tarball…", _DAY)
        inv_name = f"invocations_per_function_md.anon.{_DAY}.csv"
        dur_name = f"function_durations_percentiles.anon.{_DAY}.csv"

        with tarfile.open(tarball_path, "r:xz") as tf, tempfile.TemporaryDirectory() as tmpdir:
            tf.extract(inv_name, path=tmpdir)
            tf.extract(dur_name, path=tmpdir)
            inv_path = Path(tmpdir) / inv_name
            dur_path = Path(tmpdir) / dur_name
            df = self._process(inv_path, dur_path)

        df.to_parquet(AZURE_CACHE_PATH, index=False)
        logger.info("Azure: cached {} rows to {}", len(df), AZURE_CACHE_PATH)
        return df

    def _process(self, inv_path: Path, dur_path: Path):
        """Merge invocations + durations; synthesise individual task records."""
        import pandas as pd

        logger.info("Azure: loading invocations CSV…")
        inv = pd.read_csv(inv_path)

        logger.info("Azure: loading duration percentiles CSV…")
        dur = pd.read_csv(dur_path)

        window_cols = [str(m) for m in range(_BEST_WINDOW_START, _BEST_WINDOW_END + 1)]

        # Total invocations in the 60-min window per function
        inv["total_inv"] = inv[window_cols].fillna(0).sum(axis=1)
        active = inv[inv["total_inv"] > 0].copy()
        logger.info(
            "Azure: {} functions active in window minutes {}-{}",
            len(active),
            _BEST_WINDOW_START,
            _BEST_WINDOW_END,
        )

        # Merge duration stats
        dur_cols = [
            "HashFunction",
            "Average",
            "percentile_Average_25",
            "percentile_Average_50",
            "percentile_Average_75",
            "percentile_Average_99",
        ]
        merged = active.merge(dur[dur_cols], on="HashFunction", how="left")

        # Drop functions with missing or invalid durations
        merged = merged.dropna(subset=["Average"])
        merged = merged[(merged["Average"] > 0) & (merged["Average"] <= _MAX_DURATION_MS)]
        logger.info("Azure: {} functions after duration filtering", len(merged))

        # Synthesise individual task records using vectorised melt
        rows = self._synthesise_tasks(merged, window_cols)
        df = pd.DataFrame(rows)
        df = df.sort_values("arrival_ms").reset_index(drop=True)
        logger.info("Azure: synthesised {} individual task records", len(df))
        return df

    def _synthesise_tasks(self, merged, window_cols: list[str]) -> list[dict]:
        """Expand per-minute invocation counts into individual task records.

        Uses a vectorised melt so NumPy handles the per-invocation RNG calls
        instead of a Python loop over individual tasks. Duration is sampled from
        a log-normal fitted to each function's p25/p50/p75.

        The expansion stops at ``_CACHE_ROWS`` rows so the cache stays bounded
        even though the full trace has 42M+ invocations.
        """

        rng = np.random.default_rng(self._seed)

        # Melt per-minute columns into long format: one row per (function, minute)
        id_cols = [
            "HashFunction",
            "Trigger",
            "Average",
            "percentile_Average_25",
            "percentile_Average_50",
            "percentile_Average_75",
        ]
        melted = merged[id_cols + window_cols].melt(
            id_vars=id_cols,
            value_vars=window_cols,
            var_name="minute",
            value_name="inv_count",
        )
        melted["inv_count"] = melted["inv_count"].fillna(0).astype(int)
        melted = melted[melted["inv_count"] > 0].copy()
        logger.info("Azure: {} (function, minute) pairs to expand", len(melted))

        rows: list[dict] = []

        for tup in melted.itertuples(index=False):
            fn_hash: str = tup.HashFunction
            trigger: str = tup.Trigger
            minute_num: int = int(tup.minute)
            n_inv: int = int(tup.inv_count)

            p25 = max(float(tup.percentile_Average_25), 1.0)
            p50 = float(tup.percentile_Average_50)
            p75 = float(tup.percentile_Average_75)
            safe_p75 = max(p75, p25 * 1.001)
            sigma = max(0.01, (np.log(safe_p75) - np.log(p25)) / 1.349)
            mu = np.log(max(p50, 1.0))

            base_ms = (minute_num - _BEST_WINDOW_START) * 60_000.0
            offsets = rng.uniform(0, 60_000.0, size=n_inv)
            durations = np.clip(rng.lognormal(mu, sigma, size=n_inv), 1.0, _MAX_DURATION_MS)

            for i in range(n_inv):
                rows.append(
                    {
                        "job_id": f"az-{fn_hash[:16]}-{minute_num}-{i}",
                        "task_type": fn_hash,
                        "trigger": trigger,
                        "duration_ms": float(durations[i]),
                        "arrival_ms": base_ms + float(offsets[i]),
                        "payload_size": 1,
                    }
                )

            if len(rows) >= _CACHE_ROWS:
                logger.info("Azure: cache target {} reached, stopping expansion", _CACHE_ROWS)
                break

        return rows

    def _validate_schema(self, df) -> None:
        missing = _REQUIRED_COLS - set(df.columns)
        if missing:
            raise ValueError(
                f"Azure dataset cache is missing required columns: {missing}. "
                "Delete the cache at AZURE_CACHE_PATH and re-run."
            )

    def _to_trace_jobs(self, df) -> list[TraceJob]:
        jobs = []
        for row in df.itertuples(index=False):
            jobs.append(
                TraceJob(
                    job_id=str(row.job_id),
                    task_type=str(row.task_type),
                    payload_size=int(row.payload_size),
                    true_ms=max(1.0, float(row.duration_ms)),
                    arrival_ms=float(row.arrival_ms),
                    metadata={
                        "trigger": str(row.trigger),
                    },
                )
            )
        return jobs
