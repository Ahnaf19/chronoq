"""Shared cache path helpers for trace loaders."""

from __future__ import annotations

import os
from pathlib import Path

# Root of the bench package (bench/)
_BENCH_ROOT = Path(__file__).parent.parent.parent

DATA_DIR = _BENCH_ROOT / "data"
ARTIFACTS_DIR = _BENCH_ROOT / "artifacts"

CI_SAMPLE_PATH = DATA_DIR / "burstgpt_ci_sample.parquet"
BURSTGPT_CACHE_PATH = DATA_DIR / "burstgpt_full.parquet"


def is_offline() -> bool:
    """True when CHRONOQ_BENCH_OFFLINE=1 — use CI sample, skip HF download."""
    return os.environ.get("CHRONOQ_BENCH_OFFLINE", "0") == "1"


def ensure_artifacts_dir() -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_DIR
