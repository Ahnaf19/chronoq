"""chronoq-bench — benchmark harness for chronoq-ranker.

SimPy discrete-event simulator + BurstGPT/synthetic traces + 5 baselines +
JCT/ranking metrics + experiments → bench/artifacts/jct_vs_load.png.

Usage:
    make bench        # full run, ~10 min
    make bench-smoke  # 1k-record CI subset, <60s
"""

__version__ = "0.2.0"
