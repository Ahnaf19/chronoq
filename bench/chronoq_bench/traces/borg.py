"""Google Borg 2011 trace loader.

Downloads one shard of the ``clusterdata-2011-2`` task_events table from Google
Cloud Storage on first run and caches the processed task-duration records as a
local parquet file.  Set ``CHRONOQ_BENCH_OFFLINE=1`` to skip the download and
use the committed 100-row CI sample instead.

Source
------
Google Borg cluster trace 2011 (``clusterdata-2011-2``).
Stored in the public GCS bucket ``gs://clusterdata-2011-2``.
Licensed under Creative Commons CC-BY 4.0.
Reference: https://github.com/google/cluster-data

Task duration is reconstructed from SUBMIT (event_type=0) and FINISH
(event_type=4) events for tasks where both events appear in the downloaded
shard.  Duration = finish_timestamp − submit_timestamp (converted from
microseconds to milliseconds).

Workload characteristics
------------------------
Borg is cluster-batch scheduling at Google-data-centre scale.  Task durations
are orders of magnitude longer than typical Celery jobs: minimum ~15 s, median
~7 min, p99 ~52 min.  The scheduling-class field (0–3) maps to priority tiers
and serves as ``task_type``.  cpu_request (normalised) maps to ``payload_size``
as a proxy for job size.  This trace exercises the ranker's ability to
distinguish fast ``sched_class=2`` tasks from the dominant ``sched_class=0``
long-tail batch workload.

The dominant workload is sched_class=0 (best-effort batch), which creates
a characteristic heavy tail.  The feature ``recent_mean_ms_this_type`` will
correctly capture the 10× duration difference between sched_class=0 (~7 min
median) and sched_class=2 (~15–30 min, lower count).  However, because ALL
tasks are long-running cluster jobs, the absolute JCT improvements vs FCFS may
be smaller than the BurstGPT trace where short/long task types differ by 500×.
"""

from __future__ import annotations

import gzip
import urllib.request
from typing import TYPE_CHECKING

from loguru import logger

from chronoq_bench.traces.base import TraceJob, TraceLoader
from chronoq_bench.traces.cache import (
    BORG_CACHE_PATH,
    BORG_CI_SAMPLE_PATH,
    BORG_DATA_DIR,
    BORG_GCS_SHARD_URL,
    is_offline,
)

if TYPE_CHECKING:
    from pathlib import Path

# Required columns in the processed Borg parquet.
_REQUIRED_COLS = {
    "job_id",
    "duration_ms",
    "scheduling_class",
    "cpu_request",
    "submit_time_us",
}

# Borg scheduling_class → human-readable task_type label used in the simulator.
# scheduling_class 0: best-effort batch (free tier, delay-insensitive)
# scheduling_class 1: batch with looser latency requirements
# scheduling_class 2: latency-sensitive (interactive / prod-like)
# scheduling_class 3: monitoring (rare; absent in shard 0)
_SCHED_CLASS_TO_TYPE: dict[int, str] = {
    0: "batch",
    1: "batch_prod",
    2: "latency_sensitive",
    3: "monitoring",
}


class BorgLoader(TraceLoader):
    """Load Google Borg 2011 cluster-trace tasks as TraceJob sequences.

    Durations are cluster-batch task lifetimes reconstructed from SUBMIT and
    FINISH events in one shard of the official 2011-2 task_events table.  They
    are 3–4 orders of magnitude longer than typical Celery tasks; see module
    docstring for workload characteristics and caveats.
    """

    def __init__(self, max_rows: int | None = None) -> None:
        self._max_rows = max_rows

    @property
    def name(self) -> str:
        return "borg"

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
            if not BORG_CI_SAMPLE_PATH.exists():
                raise FileNotFoundError(
                    f"Borg CI sample not found at {BORG_CI_SAMPLE_PATH}. "
                    "Run `make bench` without CHRONOQ_BENCH_OFFLINE=1 to download."
                )
            logger.info("Borg: offline mode — loading CI sample ({})", BORG_CI_SAMPLE_PATH)
            df = pd.read_parquet(BORG_CI_SAMPLE_PATH)
        elif BORG_CACHE_PATH.exists():
            logger.info("Borg: loading from cache ({})", BORG_CACHE_PATH)
            df = pd.read_parquet(BORG_CACHE_PATH)
        else:
            df = self._download_and_process()

        self._validate_schema(df)

        # Shuffle so that head(n) yields a representative sample across the
        # full duration CDF rather than the first time-window (which clusters
        # tasks with similar durations due to the time-sorted raw trace).
        df = df.sample(frac=1, random_state=42).reset_index(drop=True)

        if limit is not None:
            df = df.head(limit)
        return df

    def _download_and_process(self):
        """Download one task_events shard from GCS and extract task durations."""
        BORG_DATA_DIR.mkdir(parents=True, exist_ok=True)
        raw_gz = BORG_DATA_DIR / "task_events_part-00000.csv.gz"

        logger.info("Borg: downloading task_events shard from GCS ({})", BORG_GCS_SHARD_URL)
        urllib.request.urlretrieve(BORG_GCS_SHARD_URL, raw_gz)
        logger.info("Borg: downloaded {} bytes", raw_gz.stat().st_size)

        df = self._parse_shard(raw_gz)

        # Rejection-sample to ≤10K rows preserving duration CDF
        if len(df) > 10_000:
            df = self._rejection_sample(df, target=10_000, seed=42)

        df.to_parquet(BORG_CACHE_PATH, index=False)
        logger.info("Borg: cached {} rows to {}", len(df), BORG_CACHE_PATH)
        return df

    @staticmethod
    def _parse_shard(raw_gz: Path):
        """Parse a gzip-compressed task_events CSV shard.

        Extracts task records with both SUBMIT (event_type=0) and FINISH
        (event_type=4) events and computes duration in milliseconds.

        task_events column schema (clusterdata-2011-2 v2.1):
          0: time (μs), 1: missing_info, 2: job_id, 3: task_index,
          4: machine_id, 5: event_type, 6: user, 7: scheduling_class,
          8: priority, 9: cpu_request, 10: memory_request,
          11: disk_request, 12: different_machine_constraint
        """
        import pandas as pd

        submits: dict[tuple[str, str], int] = {}
        finishes: dict[tuple[str, str], int] = {}
        sched_classes: dict[tuple[str, str], int] = {}
        priorities_map: dict[tuple[str, str], int] = {}
        cpu_requests: dict[tuple[str, str], float] = {}
        mem_requests: dict[tuple[str, str], float] = {}

        with gzip.open(raw_gz, "rt") as fh:
            for line in fh:
                parts = line.strip().split(",")
                if len(parts) < 6:
                    continue
                try:
                    ts = int(parts[0])
                    job_id = parts[2]
                    task_idx = parts[3]
                    event_type = int(parts[5]) if parts[5] else -1
                    key: tuple[str, str] = (job_id, task_idx)
                    if event_type == 0:  # SUBMIT
                        submits[key] = ts
                        sched_classes[key] = int(parts[7]) if len(parts) > 7 and parts[7] else 0
                        priorities_map[key] = int(parts[8]) if len(parts) > 8 and parts[8] else 0
                        cpu_requests[key] = float(parts[9]) if len(parts) > 9 and parts[9] else 0.0
                        mem_requests[key] = (
                            float(parts[10]) if len(parts) > 10 and parts[10] else 0.0
                        )
                    elif event_type == 4:  # FINISH
                        finishes[key] = ts
                except (ValueError, IndexError):
                    pass

        records = []
        for key, finish_ts in finishes.items():
            if key not in submits:
                continue
            submit_ts = submits[key]
            dur_us = finish_ts - submit_ts
            if dur_us <= 0:
                continue
            job_id, task_idx = key
            records.append(
                {
                    "job_id": job_id,
                    "task_index": int(task_idx) if task_idx else 0,
                    "submit_time_us": submit_ts,
                    "finish_time_us": finish_ts,
                    "duration_ms": dur_us / 1000.0,
                    "scheduling_class": sched_classes.get(key, 0),
                    "priority": priorities_map.get(key, 0),
                    "cpu_request": cpu_requests.get(key, 0.0),
                    "memory_request": mem_requests.get(key, 0.0),
                }
            )

        df = pd.DataFrame(records)
        df = df.sort_values("submit_time_us").reset_index(drop=True)
        return df

    @staticmethod
    def _rejection_sample(df, target: int = 10_000, seed: int = 42):
        """Downsample to ``target`` rows preserving the duration CDF shape.

        Stratifies by ``scheduling_class`` so rare classes retain representation
        proportional to their share in the full dataset.
        """
        import numpy as np
        import pandas as pd

        rng = np.random.default_rng(seed)
        classes = sorted(df["scheduling_class"].unique())
        total = len(df)
        n_per_class = {
            cls: max(1, int(target * len(df[df["scheduling_class"] == cls]) / total))
            for cls in classes
        }
        # Adjust to hit target exactly
        allocated = sum(n_per_class.values())
        remaining = target - allocated
        for cls in classes:
            if remaining <= 0:
                break
            n_per_class[cls] += 1
            remaining -= 1

        parts = []
        for cls in classes:
            subset = df[df["scheduling_class"] == cls]
            n = min(n_per_class[cls], len(subset))
            idx = rng.choice(len(subset), size=n, replace=False)
            parts.append(subset.iloc[idx])

        return pd.concat(parts).reset_index(drop=True).head(target)

    def _validate_schema(self, df) -> None:
        """Fail loudly if required columns are missing."""
        missing = _REQUIRED_COLS - set(df.columns)
        if missing:
            raise ValueError(
                f"Borg dataset is missing required columns: {missing}. "
                "The cached parquet may be stale. Delete "
                f"{BORG_CACHE_PATH} and re-run to regenerate."
            )

    def _to_trace_jobs(self, df) -> list[TraceJob]:
        """Convert Borg dataframe rows to TraceJob records."""
        jobs = []
        for row in df.itertuples(index=False):
            sched_cls = int(getattr(row, "scheduling_class", 0))
            task_type = _SCHED_CLASS_TO_TYPE.get(sched_cls, f"sched_class_{sched_cls}")

            # cpu_request is normalised [0.0, 1.0]; scale to int proxy for payload_size
            cpu_req = float(getattr(row, "cpu_request", 0.0))
            payload_size = max(1, int(cpu_req * 1_000_000))

            # arrival_ms: submit_time_us converted from μs to ms, relative to trace start
            submit_us = float(getattr(row, "submit_time_us", 0.0))
            jobs.append(
                TraceJob(
                    job_id=f"{row.job_id}_{getattr(row, 'task_index', 0)}",
                    task_type=task_type,
                    payload_size=payload_size,
                    true_ms=max(1.0, float(row.duration_ms)),
                    arrival_ms=submit_us / 1000.0,
                    priority=int(getattr(row, "priority", 0)),
                    metadata={
                        "scheduling_class": sched_cls,
                        "memory_request": float(getattr(row, "memory_request", 0.0)),
                    },
                )
            )
        return jobs
