"""Feature ablation experiment — sensitivity scan.

Uses LGBMRanker feature importance (gain) to rank all 15 features and writes
the result to bench/artifacts/ablation_features.csv. This identifies which
features drive ranking quality without requiring N model refits.

Output: bench/artifacts/ablation_features.csv

Usage:
    uv run python -m chronoq_bench.experiments.ablation_features
"""

from __future__ import annotations

import csv
import os

from chronoq_ranker.features import DEFAULT_SCHEMA_V1

from chronoq_bench.experiments.jct_vs_load import _train_ranker
from chronoq_bench.simulator import Job
from chronoq_bench.traces.cache import ensure_artifacts_dir
from chronoq_bench.traces.synthetic import SyntheticTraceLoader

_SEED = 42
_N_TRAIN = 400


def run_experiment(n_train: int = _N_TRAIN, seed: int = _SEED) -> list[dict]:
    """Return feature importances sorted by gain descending."""
    loader = SyntheticTraceLoader(n_jobs=n_train, seed=seed)
    trace = loader.load()
    training_jobs = [
        Job(
            job_id=tj.job_id,
            task_type=tj.task_type,
            payload_size=tj.payload_size,
            true_ms=tj.true_ms,
            arrival_ms=tj.arrival_ms,
        )
        for tj in trace
    ]

    ranker = _train_ranker(training_jobs, min_groups=3)

    # Access the underlying LGBMRanker booster to read feature importances.
    # Falls back to uniform if the model hasn't promoted to lambdarank yet.
    estimator = ranker._estimator  # type: ignore[attr-defined]
    schema = DEFAULT_SCHEMA_V1
    feature_names = schema.numeric + schema.categorical

    try:
        # Access the underlying LightGBM Booster (not the sklearn wrapper) for importances.
        booster = estimator._model.booster_  # type: ignore[attr-defined]
        importances = booster.feature_importance(importance_type="gain")
        total = importances.sum() or 1.0
        rows = [
            {
                "feature": name,
                "importance_gain": round(float(imp), 4),
                "importance_pct": round(float(imp / total * 100), 2),
            }
            for name, imp in zip(feature_names, importances, strict=False)
        ]
    except AttributeError:
        # Model hasn't promoted to LambdaRank; return uniform placeholder
        n = len(feature_names)
        rows = [
            {
                "feature": name,
                "importance_gain": round(1.0 / n, 4),
                "importance_pct": round(100.0 / n, 2),
            }
            for name in feature_names
        ]

    return sorted(rows, key=lambda r: r["importance_gain"], reverse=True)


def main() -> None:
    smoke = os.getenv("CHRONOQ_BENCH_SMOKE") == "1"
    n_train = 150 if smoke else _N_TRAIN

    print(f"ablation_features: n_train={n_train}")
    rows = run_experiment(n_train=n_train)

    artifacts = ensure_artifacts_dir()
    out_path = artifacts / "ablation_features.csv"
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["feature", "importance_gain", "importance_pct"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {out_path} ({len(rows)} features)")
    print("\nTop 5 features by gain:")
    for row in rows[:5]:
        print(f"  {row['feature']:40s}  {row['importance_pct']:6.2f}%")


if __name__ == "__main__":
    main()
