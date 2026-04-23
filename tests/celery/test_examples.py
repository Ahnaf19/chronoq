"""Tests for integrations/celery/examples/toggle_demo.py.

Validates that the eager-mode demo runs end-to-end without errors and produces
meaningful JCT output. Does not assert specific JCT numbers (flaky due to
time.sleep jitter) — only that the demo exits cleanly within time budget.
"""

from __future__ import annotations

import subprocess
import sys
import time


def test_toggle_demo_runs() -> None:
    """toggle_demo.py exits 0 in under 60 seconds (both fifo + active modes).

    Runs as a subprocess to avoid Celery signal leakage between test cases.
    The demo is expected to complete in ~15 seconds; the 60s budget is generous
    to accommodate CI variance.
    """
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "integrations.celery.examples.toggle_demo"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(
            __import__("pathlib").Path(__file__).parent.parent.parent
        ),
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0, (
        f"toggle_demo.py exited with code {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert elapsed < 60.0, f"Demo took {elapsed:.1f}s, expected < 60s"

    # Sanity-check that both modes ran and produced output
    assert "fifo" in result.stdout, "Expected 'fifo' in demo output"
    assert "active" in result.stdout, "Expected 'active' in demo output"
    assert "mean_jct_ms" in result.stdout, "Expected JCT table header in output"
    assert "tasks captured" in result.stdout, "Expected completion count in output"
