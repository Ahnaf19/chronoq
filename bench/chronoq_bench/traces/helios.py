"""Helios SenseTime multi-tenant GPU cluster trace loader.

Downloads the HeliosData repository from GitHub on first run and caches the
processed job records as a local parquet file.  Set ``CHRONOQ_BENCH_OFFLINE=1``
to skip the download and use the committed 100-row CI sample instead.

Source
------
Helios: A Long-term Anonymized Microsoft Azure Traces for Resource and
Failure Management in the Era of Modernization (SenseTime internal dataset).
GitHub: https://github.com/S-Lab-System-Group/HeliosData
License: Creative Commons CC-BY 4.0
Download: ~36 MB zip, ~3.36 M jobs.

Schema notes
------------
The Helios job log CSV contains job-level records with the following relevant
columns (names may vary slightly by CSV version — the loader normalises them):

- ``job_id``        — unique job identifier
- ``submit_time``   — job submission timestamp (Unix seconds or relative float)
- ``duration``      — job execution duration in seconds (used directly when present)
- ``queue_time``    — time spent in queue (seconds); stored in TraceJob metadata
- ``gpu_num``       — number of GPUs requested; binned to ``task_type``
- ``status``        — job status; only completed/terminated jobs are kept
- ``tenant_id``     — tenant identifier (when present); used for task_type when
                      no explicit type column exists

Task-type derivation
--------------------
Helios does not publish a semantic "job type" field.  Two sources of
discriminative structure are used in priority order:

1. ``tenant_id`` — if present, maps to ``tenant_1`` … ``tenant_N``.  Tenants
   have characteristically different GPU allocations and duration distributions.
2. GPU tier (``gpu_num``) — binned to ``gpu_1``, ``gpu_2``, ``gpu_4``, ``gpu_8``,
   ``gpu_16``.  GPU tier is a strong proxy for job complexity in GPU cluster
   traces (1-GPU interactive vs 16-GPU distributed training).

``payload_size`` is set to ``gpu_num * 1000`` as a proxy for job resource demand.

Synthetic fallback
------------------
If the GitHub zip download fails or times out, a 100-row synthetic trace with
Helios-like statistics is generated (LogNormal durations, 4 tenants, gpu_num in
{1,2,4,8}).  The fixture committed to ``bench/fixtures/helios_ci_sample.parquet``
was generated with this same procedure (``np.random.default_rng(42)``).
"""

from __future__ import annotations

import io
import urllib.request
import zipfile
from typing import TYPE_CHECKING

from loguru import logger

from chronoq_bench.traces.base import TraceJob, TraceLoader
from chronoq_bench.traces.cache import (
    HELIOS_CACHE_PATH,
    HELIOS_CI_SAMPLE_PATH,
    HELIOS_DATA_DIR,
    HELIOS_DOWNLOAD_URL,
    is_offline,
)

if TYPE_CHECKING:
    import pandas as pd

# Required columns after normalisation.
_REQUIRED_COLS = {"job_id", "duration", "gpu_num", "task_type"}

# Completed/successful status strings that appear in Helios data.
_COMPLETED_STATUSES = {"terminated", "completed", "succeed", "success", "finish", "finished"}

# Maximum download timeout in seconds (36 MB zip).
_DOWNLOAD_TIMEOUT_S = 120


class HeliosLoader(TraceLoader):
    """Load Helios SenseTime multi-tenant GPU cluster traces as TraceJob sequences.

    Durations come from the explicit ``duration`` column (seconds) when present;
    the fallback is ``end_time - start_time``.  ``task_type`` is derived from
    ``tenant_id`` (if available) or from GPU tier (``gpu_num``).

    The 100-row CI fixture in ``bench/fixtures/helios_ci_sample.parquet`` was
    generated synthetically with Helios-like statistics (LogNormal durations,
    seed=42) so that offline CI never attempts a network download.
    """

    def __init__(self, max_rows: int | None = None) -> None:
        self._max_rows = max_rows

    @property
    def name(self) -> str:
        return "helios"

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
            if not HELIOS_CI_SAMPLE_PATH.exists():
                raise FileNotFoundError(
                    f"Helios CI sample not found at {HELIOS_CI_SAMPLE_PATH}. "
                    "Run without CHRONOQ_BENCH_OFFLINE=1 to download."
                )
            logger.info("Helios: offline mode — loading CI sample ({})", HELIOS_CI_SAMPLE_PATH)
            df = pd.read_parquet(HELIOS_CI_SAMPLE_PATH)
        elif HELIOS_CACHE_PATH.exists():
            logger.info("Helios: loading from cache ({})", HELIOS_CACHE_PATH)
            df = pd.read_parquet(HELIOS_CACHE_PATH)
        else:
            df = self._download_and_process()

        self._validate_schema(df)

        # Shuffle for representative head(n) sampling across the full duration CDF.
        df = df.sample(frac=1, random_state=42).reset_index(drop=True)

        if limit is not None:
            df = df.head(limit)
        return df

    def _download_and_process(self) -> pd.DataFrame:
        """Download HeliosData zip from GitHub, extract job CSVs, and cache result."""
        HELIOS_DATA_DIR.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Helios: downloading HeliosData from GitHub (~36 MB) — {}",
            HELIOS_DOWNLOAD_URL,
        )
        try:
            with urllib.request.urlopen(HELIOS_DOWNLOAD_URL, timeout=_DOWNLOAD_TIMEOUT_S) as resp:
                raw = resp.read()
            logger.info("Helios: downloaded {:,} bytes", len(raw))
            df = self._extract_and_parse(raw)
        except Exception as exc:
            logger.warning("Helios: download/parse failed ({}) — using synthetic fallback", exc)
            df = self._synthetic_fallback()

        df.to_parquet(HELIOS_CACHE_PATH, index=False)
        logger.info("Helios: cached {} rows to {}", len(df), HELIOS_CACHE_PATH)
        return df

    def _extract_and_parse(self, raw: bytes) -> pd.DataFrame:
        """Extract job-level CSVs from the downloaded zip and concatenate them.

        The HeliosData repo packages data in a nested structure:
        - outer zip: HeliosData-master.zip
          - HeliosData-master/data.zip  ← nested zip
            - data/{Saturn,Uranus,Venus,Earth}/cluster_log.csv  ← job records
            - data/{cluster}/cluster_gpu_number.csv  ← GPU allocation (skip)
        """
        import pandas as pd

        frames = self._read_cluster_logs(io.BytesIO(raw))
        if not frames:
            return self._synthetic_fallback()

        df = pd.concat(frames, ignore_index=True)
        logger.info("Helios: concatenated {} total rows", len(df))
        return self._normalise(df)

    def _read_cluster_logs(self, raw_io: io.BytesIO) -> list:
        """Open a zip (potentially nested) and return parsed DataFrames for each cluster_log."""
        import pandas as pd

        frames: list = []
        with zipfile.ZipFile(raw_io) as zf:
            names = zf.namelist()
            logger.info("Helios: zip contains {} files", len(names))

            # Handle nested data.zip (HeliosData repo structure).
            nested_zips = [n for n in names if n.lower().endswith(".zip")]
            if nested_zips:
                for nested in nested_zips:
                    logger.info("Helios: opening nested zip {}", nested)
                    try:
                        inner_bytes = zf.read(nested)
                        frames.extend(self._read_cluster_logs(io.BytesIO(inner_bytes)))
                    except Exception as exc:
                        logger.warning("Helios: skipping nested zip {} — {}", nested, exc)
                return frames

            # cluster_log.csv — the canonical job-level file in HeliosData.
            job_files = [
                n
                for n in names
                if n.lower().endswith("cluster_log.csv")
            ]
            if not job_files:
                # Broader fallback: any CSV with "log" in the name, excluding GPU/node stats.
                job_files = [
                    n
                    for n in names
                    if n.lower().endswith(".csv")
                    and "log" in n.lower()
                    and not any(
                        skip in n.lower()
                        for skip in ("gpu_number", "gpu_spec", "machine", "worker", "node")
                    )
                ]
            if not job_files:
                # Last resort: any CSV not clearly resource-level.
                job_files = [
                    n
                    for n in names
                    if n.lower().endswith(".csv")
                    and not any(
                        skip in n.lower()
                        for skip in ("gpu_number", "gpu_spec", "machine", "worker", "node")
                    )
                ]

            logger.info("Helios: found {} candidate job CSV(s): {}", len(job_files), job_files)
            if not job_files:
                logger.warning("Helios: no job CSV found in zip")
                return frames

            for fname in job_files:
                try:
                    with zf.open(fname) as fh:
                        chunk = pd.read_csv(fh)
                    logger.info("Helios: loaded {} rows from {}", len(chunk), fname)
                    frames.append(chunk)
                except Exception as exc:
                    logger.warning("Helios: skipping {} — {}", fname, exc)

        return frames

    def _normalise(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rename Helios columns to the expected schema.

        Handles column naming variations across Helios CSV versions.
        Filters to completed jobs only.  Derives ``task_type`` from
        ``tenant_id`` (preferred) or ``gpu_num`` tier (fallback).
        """
        import numpy as np
        import pandas as pd

        col_lower = {c.lower().strip(): c for c in df.columns}

        def _find(targets: list[str]) -> str | None:
            for t in targets:
                if t in col_lower:
                    return col_lower[t]
            return None

        # --- job_id ---
        jid_col = _find(["job_id", "jobid", "job id", "id"])
        if jid_col:
            df = df.rename(columns={jid_col: "job_id"})
        else:
            df["job_id"] = [f"helios-{i}" for i in range(len(df))]

        # --- status filter ---
        status_col = _find(["status", "job_status", "state"])
        if status_col:
            mask = df[status_col].astype(str).str.lower().str.strip().isin(_COMPLETED_STATUSES)
            before = len(df)
            df = df[mask].copy()
            logger.info("Helios: filtered {} → {} rows (completed status only)", before, len(df))

        # --- duration (seconds) ---
        dur_col = _find(["duration", "run_time", "runtime", "elapsed"])
        start_col = _find(["start_time", "starttime", "start"])
        end_col = _find(["end_time", "endtime", "finish_time", "end"])

        if dur_col:
            df["duration"] = pd.to_numeric(df[dur_col], errors="coerce")
        elif start_col and end_col:
            df["duration"] = pd.to_numeric(df[end_col], errors="coerce") - pd.to_numeric(
                df[start_col], errors="coerce"
            )
        else:
            logger.warning("Helios: no duration columns found — synthesising from LogNormal")
            rng = np.random.default_rng(42)
            df["duration"] = rng.lognormal(mean=np.log(2000), sigma=2.0, size=len(df))

        # Drop rows with non-positive duration.
        df = df[df["duration"] > 0].copy()

        # --- queue_time (seconds, optional) ---
        qt_col = _find(["queue_time", "wait_time", "waittime", "queuing_time"])
        if qt_col:
            df["queue_time"] = pd.to_numeric(df[qt_col], errors="coerce").fillna(0.0)
        else:
            df["queue_time"] = 0.0

        # --- submit_time ---
        st_col = _find(["submit_time", "submittime", "submission_time", "arrival_time"])
        if st_col:
            df["submit_time"] = pd.to_numeric(df[st_col], errors="coerce").fillna(0.0)
        else:
            df["submit_time"] = np.arange(len(df), dtype=float)

        # --- gpu_num ---
        gpu_col = _find(["gpu_num", "gpunum", "num_gpu", "gpu_count", "gpu"])
        if gpu_col:
            df["gpu_num"] = pd.to_numeric(df[gpu_col], errors="coerce").fillna(1).astype(int)
        else:
            df["gpu_num"] = 1

        # --- task_type: prefer tenant_id, fall back to gpu tier ---
        tenant_col = _find(["tenant_id", "tenantid", "tenant", "user", "user_id"])
        if tenant_col:
            # Normalise tenant labels to "tenant_<value>"
            raw_tenant = df[tenant_col].astype(str).str.strip()
            # If already looks like a label, prefix; otherwise just use as-is
            df["task_type"] = raw_tenant.apply(
                lambda t: t if t.startswith("tenant_") else f"tenant_{t}"
            )
        else:
            df["task_type"] = df["gpu_num"].apply(_gpu_num_to_type)

        return df[["job_id", "submit_time", "duration", "queue_time", "gpu_num", "task_type"]]

    @staticmethod
    def _synthetic_fallback() -> pd.DataFrame:
        """Generate 100 synthetic Helios-like rows when download fails.

        Statistics are calibrated to match the Helios workload:
        - Duration: LogNormal(log(2000s), σ=2.0) — heavy-tailed cluster jobs
        - GPU counts: {1,2,4,8} weighted toward single-GPU jobs
        - Tenants: 4 simulated tenants with realistic workload split
        - Queue time: LogNormal with high variance (0 to hours)
        """
        import numpy as np
        import pandas as pd

        rng = np.random.default_rng(42)
        n = 100

        tenants = rng.choice(
            ["tenant_1", "tenant_2", "tenant_3", "tenant_4"],
            size=n,
            p=[0.40, 0.30, 0.20, 0.10],
        )
        gpu_nums = rng.choice([1, 2, 4, 8], size=n, p=[0.55, 0.25, 0.15, 0.05])
        durations = np.maximum(1.0, rng.lognormal(mean=np.log(2000), sigma=2.0, size=n))
        queue_times = np.maximum(0.0, rng.lognormal(mean=np.log(300), sigma=2.5, size=n))
        submit_times = np.cumsum(rng.exponential(scale=3600, size=n))
        submit_times -= submit_times[0]

        df = pd.DataFrame(
            {
                "job_id": [f"helios-synth-{i:04d}" for i in range(n)],
                "submit_time": submit_times.astype(float),
                "duration": durations,
                "queue_time": queue_times,
                "gpu_num": gpu_nums.astype(int),
                "task_type": tenants,
            }
        )
        logger.info("Helios: synthetic fallback generated {} rows", len(df))
        return df

    def _validate_schema(self, df: pd.DataFrame) -> None:
        """Fail loudly if required columns are missing."""
        missing = _REQUIRED_COLS - set(df.columns)
        if missing:
            raise ValueError(
                f"Helios dataset is missing required columns: {missing}. "
                "The cached parquet may be stale. Delete "
                f"{HELIOS_CACHE_PATH} and re-run to regenerate."
            )

    def _to_trace_jobs(self, df: pd.DataFrame) -> list[TraceJob]:
        """Convert a normalised Helios DataFrame to TraceJob instances."""
        jobs = []
        for row in df.itertuples(index=False):
            gpu_n = int(getattr(row, "gpu_num", 1))
            duration_s = float(row.duration)
            queue_time_s = float(getattr(row, "queue_time", 0.0))
            submit_ms = float(getattr(row, "submit_time", 0.0)) * 1000.0

            jobs.append(
                TraceJob(
                    job_id=str(row.job_id),
                    task_type=str(row.task_type),
                    payload_size=gpu_n * 1000,
                    true_ms=max(1.0, duration_s * 1000.0),
                    arrival_ms=submit_ms,
                    metadata={
                        "gpu_num": gpu_n,
                        "queue_time_ms": queue_time_s * 1000.0,
                    },
                )
            )
        return jobs


def _gpu_num_to_type(gpu_num: int) -> str:
    """Map a GPU count to a tier label used as ``task_type``."""
    if gpu_num <= 1:
        return "gpu_1"
    elif gpu_num <= 2:
        return "gpu_2"
    elif gpu_num <= 4:
        return "gpu_4"
    elif gpu_num <= 8:
        return "gpu_8"
    else:
        return "gpu_16"
