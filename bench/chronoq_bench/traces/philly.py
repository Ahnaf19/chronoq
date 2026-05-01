"""Microsoft Philly DNN-training cluster trace loader.

Downloads the Philly cluster job log from the msr-fiddle/philly-traces GitHub
repository on first run and caches the processed records as a local parquet
file. Set ``CHRONOQ_BENCH_OFFLINE=1`` to skip the download and use the
committed 100-row CI sample instead.

Source
------
Microsoft Philly cluster trace (October 2017 – August 2018, ~180 days).
Published at: https://github.com/msr-fiddle/philly-traces
Licensed under Creative Commons CC-BY 4.0.
Paper: Jeon et al., "Analysis of Large-Scale Multi-Tenant GPU Clusters for DNN
Training Workloads", USENIX ATC 2019.

Schema
------
The raw ``cluster-job-log.csv`` contains one row per job with the following
columns used here:

- ``submitted_time`` — job submission timestamp, e.g. "2017-10-01 00:03:59"
- ``end_time``       — job completion timestamp
- ``status``         — job outcome: "Pass", "Failed", "Killed"
- ``vc``             — virtual cluster name (maps to ``task_type``)
- ``num_gpu``        — number of GPUs requested (proxy for job size)

Duration derivation
-------------------
Filter to ``status == "Pass"`` (completed jobs only). Parse ``submitted_time``
and ``end_time`` as datetimes. Compute::

    duration_ms = (end_time - submitted_time).total_seconds() * 1000

Jobs with non-positive duration are dropped.

Task-type mapping
-----------------
``vc`` (virtual cluster) is used as ``task_type`` to give
``recent_mean_ms_this_type`` discriminative signal. Philly has a small number
of named VCs (e.g. "default", "elvis", "rr1", "rr2", "rr3", "mlperf") that
group jobs by team/project — similar to how scheduling_class groups Borg tasks.

Payload size
------------
``num_gpu * 1000`` is used as ``payload_size`` — a coarse proxy for job
resource footprint (0 GPUs → payload_size=1 via max clamp).

CI fixture note
---------------
The CI fixture at ``bench/fixtures/philly_ci_sample.parquet`` is a **synthetic
100-row sample** generated from Philly-like distributions (see
``_generate_synthetic_sample``). The full dataset (~1 GB tarball) is too large
to commit. When ``CHRONOQ_BENCH_OFFLINE=0`` and no cache exists, the loader
attempts to download the real CSV; if the download fails or the file is
unavailable, it falls back to generating a synthetic sample and logs a warning.

Synthetic distribution parameters (matching published Philly statistics):
- ``duration_ms`` ~ LogNormal(mean≈30 min, sigma=1.5)
- ``vc`` ∈ {"default", "elvis", "rr1", "rr2", "rr3"} with empirical proportions
- ``num_gpu`` ∈ {1, 2, 4, 8, 16, 32} with empirical proportions
- 100 rows, seed=42
"""

from __future__ import annotations

import urllib.error
import urllib.request

from loguru import logger

from chronoq_bench.traces.base import TraceJob, TraceLoader
from chronoq_bench.traces.cache import (
    PHILLY_CACHE_PATH,
    PHILLY_CI_SAMPLE_PATH,
    PHILLY_CSV_URL,
    PHILLY_DATA_DIR,
    is_offline,
)

# Required columns in the processed Philly parquet cache.
_REQUIRED_COLS = {
    "job_id",
    "duration_ms",
    "vc",
    "num_gpu",
    "submitted_time_ms",
}

# Virtual clusters observed in the Philly trace (from the published paper).
_KNOWN_VCS = {"default", "elvis", "rr1", "rr2", "rr3", "mlperf", "other"}

# Empirical GPU count distribution from Philly paper (Table 1).
_GPU_CHOICES = [1, 2, 4, 8, 16, 32]
_GPU_WEIGHTS = [0.40, 0.15, 0.20, 0.15, 0.07, 0.03]

# Empirical VC distribution (approximate, from the paper).
_VC_CHOICES = ["default", "elvis", "rr1", "rr2", "rr3"]
_VC_WEIGHTS = [0.45, 0.20, 0.15, 0.12, 0.08]

# Philly-like duration parameters: LogNormal(μ, σ) where μ and σ are in log-space.
# Published median ~30 min; we use ln(30*60*1000) as μ with σ=1.5.
_DURATION_LOG_MU = 13.06  # ≈ ln(30 * 60 * 1000 ms)
_DURATION_LOG_SIGMA = 1.5


def _generate_synthetic_sample(n: int = 100, seed: int = 42):
    """Generate a synthetic Philly-like DataFrame with ``n`` rows.

    Uses published Philly workload characteristics:
    - duration_ms ~ LogNormal(ln(30min), sigma=1.5)
    - vc sampled from 5 VCs with empirical proportions
    - num_gpu sampled from {1,2,4,8,16,32} with empirical proportions

    This synthetic fixture is used when:
    1. ``CHRONOQ_BENCH_OFFLINE=1`` (CI mode) — CI fixture is this data as parquet.
    2. Full dataset download fails — the loader falls back to this distribution.

    Args:
        n: Number of rows to generate.
        seed: RNG seed for reproducibility.

    Returns:
        DataFrame with columns: job_id, duration_ms, vc, num_gpu, submitted_time_ms.
    """
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)

    durations = rng.lognormal(mean=_DURATION_LOG_MU, sigma=_DURATION_LOG_SIGMA, size=n)
    durations = np.maximum(durations, 1.0)

    vc_idx = rng.choice(len(_VC_CHOICES), size=n, p=_VC_WEIGHTS)
    vcs = [_VC_CHOICES[i] for i in vc_idx]

    gpu_idx = rng.choice(len(_GPU_CHOICES), size=n, p=_GPU_WEIGHTS)
    gpus = [_GPU_CHOICES[i] for i in gpu_idx]

    # Synthetic submitted_time_ms: Poisson arrivals spread over 7 days
    span_ms = 7 * 24 * 60 * 60 * 1000
    arrival_gaps = rng.exponential(scale=span_ms / n, size=n)
    submitted_ms = np.cumsum(arrival_gaps)

    return pd.DataFrame(
        {
            "job_id": [f"philly-syn-{i:05d}" for i in range(n)],
            "duration_ms": durations.astype(float),
            "vc": vcs,
            "num_gpu": [int(g) for g in gpus],
            "submitted_time_ms": submitted_ms.astype(float),
        }
    )


class PhillyLoader(TraceLoader):
    """Load Microsoft Philly DNN-training cluster trace as TraceJob sequences.

    Durations are measured wall-clock time from ``submitted_time`` to
    ``end_time`` for ``status == "Pass"`` jobs.  ``vc`` (virtual cluster)
    serves as ``task_type``; ``num_gpu * 1000`` serves as ``payload_size``.

    See module docstring for full schema, distribution, and CI-fixture notes.
    """

    def __init__(self, max_rows: int | None = None) -> None:
        self._max_rows = max_rows

    @property
    def name(self) -> str:
        return "philly"

    def load(self, n: int | None = None) -> list[TraceJob]:
        """Return up to ``n`` TraceJob records (all if ``n`` is None)."""
        limit = n or self._max_rows
        df = self._get_dataframe(limit)
        return self._to_trace_jobs(df)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_dataframe(self, limit: int | None):
        import pandas as pd

        if is_offline():
            if not PHILLY_CI_SAMPLE_PATH.exists():
                raise FileNotFoundError(
                    f"Philly CI sample not found at {PHILLY_CI_SAMPLE_PATH}. "
                    "Run `make bench` without CHRONOQ_BENCH_OFFLINE=1 to regenerate."
                )
            logger.info("Philly: offline mode — loading CI sample ({})", PHILLY_CI_SAMPLE_PATH)
            df = pd.read_parquet(PHILLY_CI_SAMPLE_PATH)
        elif PHILLY_CACHE_PATH.exists():
            logger.info("Philly: loading from cache ({})", PHILLY_CACHE_PATH)
            df = pd.read_parquet(PHILLY_CACHE_PATH)
        else:
            df = self._download()

        self._validate_schema(df)

        # Shuffle so head(n) yields a representative sample of the duration CDF
        # rather than the first time window (which skews toward short jobs).
        df = df.sample(frac=1, random_state=42).reset_index(drop=True)

        if limit is not None:
            df = df.head(limit)
        return df

    def _download(self):
        """Download the Philly CSV tarball and process it.

        Falls back to a synthetic sample if the download fails (e.g. the file
        has moved or is too large for the CI environment). Logs a warning when
        falling back so the caller knows real data was not used.
        """
        PHILLY_DATA_DIR.mkdir(parents=True, exist_ok=True)

        logger.info("Philly: attempting to download cluster-job-log from {}", PHILLY_CSV_URL)
        try:
            df = self._download_and_parse()
        except (urllib.error.URLError, OSError, Exception) as exc:
            logger.warning(
                "Philly: download failed ({}) — falling back to synthetic sample. "
                "Set CHRONOQ_BENCH_OFFLINE=1 to silence this warning.",
                exc,
            )
            df = self._generate_and_cache_synthetic()

        df.to_parquet(PHILLY_CACHE_PATH, index=False)
        logger.info("Philly: cached {} rows to {}", len(df), PHILLY_CACHE_PATH)
        return df

    def _download_and_parse(self):
        """Download the tarball and parse the cluster-job-log CSV."""
        import io
        import tarfile

        import pandas as pd

        tarball_path = PHILLY_DATA_DIR / "cluster-job-log.csv.tar.gz"

        logger.info("Philly: downloading (~0.98 GB tarball)...")
        urllib.request.urlretrieve(PHILLY_CSV_URL, tarball_path)
        size_mb = tarball_path.stat().st_size / (1024 * 1024)
        logger.info("Philly: downloaded {:.1f} MB -> {}", size_mb, tarball_path)

        logger.info("Philly: extracting CSV from tarball...")
        with tarfile.open(tarball_path, "r:gz") as tf:
            member = next((m for m in tf.getmembers() if m.name.endswith(".csv")), None)
            if member is None:
                raise ValueError("No CSV found in Philly tarball")
            fh = tf.extractfile(member)
            if fh is None:
                raise ValueError(f"Cannot extract member {member.name}")
            raw = fh.read()

        df_raw = pd.read_csv(io.BytesIO(raw), low_memory=False)
        logger.info("Philly: read {} raw rows, columns: {}", len(df_raw), df_raw.columns.tolist())
        return self._normalise(df_raw)

    def _generate_and_cache_synthetic(self):
        """Generate a synthetic Philly-like DataFrame and log clearly."""
        logger.warning(
            "Philly: using SYNTHETIC data (Philly-like LogNormal distribution). "
            "Results on this trace are NOT from real Philly measurements."
        )
        return _generate_synthetic_sample(n=10_000, seed=42)

    def _normalise(self, df):
        """Normalise raw Philly CSV columns to the standard internal schema.

        Filters to ``status == "Pass"`` jobs, parses timestamps, computes
        ``duration_ms``, and drops invalid rows.
        """
        import pandas as pd

        # Normalise column names: lowercase + strip spaces
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

        # Filter to completed jobs only
        if "status" in df.columns:
            df = df[df["status"].str.strip().str.lower() == "pass"].copy()
        else:
            logger.warning("Philly: no 'status' column found — using all rows")

        # Parse timestamps
        for col in ("submitted_time", "end_time"):
            if col not in df.columns:
                raise ValueError(
                    f"Philly CSV missing expected column '{col}'. "
                    "The dataset schema may have changed. "
                    "Check https://github.com/msr-fiddle/philly-traces"
                )
            df[col] = pd.to_datetime(df[col], errors="coerce")

        df = df.dropna(subset=["submitted_time", "end_time"])

        # Compute duration in milliseconds
        df["duration_ms"] = (df["end_time"] - df["submitted_time"]).dt.total_seconds() * 1000.0
        df = df[df["duration_ms"] > 0].copy()

        # Normalise vc: fill missing with "other"
        if "vc" not in df.columns:
            df["vc"] = "other"
        else:
            df["vc"] = df["vc"].fillna("other").astype(str).str.strip()

        # Normalise num_gpu
        if "num_gpu" not in df.columns:
            df["num_gpu"] = 1
        else:
            df["num_gpu"] = pd.to_numeric(df["num_gpu"], errors="coerce").fillna(1).astype(int)

        # Convert submitted_time to ms from epoch 0 for arrival_ms
        submitted_ms = df["submitted_time"].astype("int64") / 1_000_000.0
        submitted_ms = submitted_ms - submitted_ms.min()
        df["submitted_time_ms"] = submitted_ms

        # Build job_id if missing
        if "job_id" not in df.columns:
            df["job_id"] = [f"philly-{i:07d}" for i in range(len(df))]

        result = df[["job_id", "duration_ms", "vc", "num_gpu", "submitted_time_ms"]].copy()
        result = result.reset_index(drop=True)

        logger.info(
            "Philly: normalised {} pass-status rows (duration range [{:.0f}ms, {:.0f}ms])",
            len(result),
            float(result["duration_ms"].min()),
            float(result["duration_ms"].max()),
        )
        return result

    def _validate_schema(self, df) -> None:
        """Raise ValueError if required columns are missing."""
        missing = _REQUIRED_COLS - set(df.columns)
        if missing:
            raise ValueError(
                f"Philly dataset is missing required columns: {missing}. "
                "The cached parquet may be stale — delete "
                f"{PHILLY_CACHE_PATH} and re-run to regenerate."
            )

    def _to_trace_jobs(self, df) -> list[TraceJob]:
        """Convert a normalised Philly DataFrame to TraceJob instances."""
        jobs = []
        for i, row in enumerate(df.itertuples(index=False)):
            vc = str(getattr(row, "vc", "default"))
            num_gpu = int(getattr(row, "num_gpu", 1))

            # payload_size: num_gpu * 1000 as proxy for job resource footprint
            payload_size = max(1, num_gpu * 1000)

            jobs.append(
                TraceJob(
                    job_id=str(getattr(row, "job_id", f"philly-{i:07d}")),
                    task_type=vc,
                    payload_size=payload_size,
                    true_ms=max(1.0, float(row.duration_ms)),
                    arrival_ms=float(getattr(row, "submitted_time_ms", 0.0)),
                    metadata={
                        "num_gpu": num_gpu,
                        "vc": vc,
                    },
                )
            )
        return jobs
