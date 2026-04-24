"""Shared cache path helpers for trace loaders."""

from __future__ import annotations

import os
from pathlib import Path

# Root of the bench package (bench/)
_BENCH_ROOT = Path(__file__).parent.parent.parent

DATA_DIR = _BENCH_ROOT / "data"
ARTIFACTS_DIR = _BENCH_ROOT / "artifacts"

# BurstGPT paths
CI_SAMPLE_PATH = _BENCH_ROOT / "fixtures" / "burstgpt_ci_sample.parquet"
BURSTGPT_CACHE_PATH = DATA_DIR / "burstgpt_full.parquet"

# Google Borg 2011 trace paths (clusterdata-2011-2, GCS public bucket, CC-BY 4.0)
BORG_DATA_DIR = DATA_DIR / "borg"
BORG_CACHE_PATH = BORG_DATA_DIR / "borg_task_durations.parquet"
BORG_CI_SAMPLE_PATH = _BENCH_ROOT / "fixtures" / "borg_ci_sample.parquet"
# GCS source: one shard of task_events from the 2011-2 Borg cluster trace
BORG_GCS_SHARD_URL = (
    "https://storage.googleapis.com/clusterdata-2011-2/task_events/part-00000-of-00500.csv.gz"
)


def is_offline() -> bool:
    """True when CHRONOQ_BENCH_OFFLINE=1 — use CI sample, skip HF download."""
    return os.environ.get("CHRONOQ_BENCH_OFFLINE", "0") == "1"


def ensure_artifacts_dir() -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_DIR
