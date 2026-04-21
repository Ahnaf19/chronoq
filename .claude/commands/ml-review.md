---
description: ML review of ranker changes — feature leakage audit, label integrity, metric selection (ρ/τ/pairwise not MAE), incremental-fit correctness, drift detector sanity. Run on any diff touching ranker/chronoq_ranker/{models,features,drift}.py.
---

Invoke the `ml-engineer` subagent with this task:

> Run the `/ml-review` workflow per your agent spec.
>
> 1. Identify the diff scope: `git diff ranker/chronoq_ranker/{models,features,drift}.py` (plus any new files under that tree). If on a feature branch, also include `git log main..HEAD -- ranker/`.
> 2. For each changed file, audit the following concerns per your agent spec:
>    - **Feature leakage**: does any feature use post-execution information? `actual_ms` must be label-only.
>    - **Label integrity**: groups well-formed? `min_groups ≥ 20` per fit? Group size ≥ 2? Rank labels monotone in `actual_ms` (shortest → highest)?
>    - **Metric selection**: are Spearman ρ, Kendall τ, and pairwise accuracy reported? If MAE/MAPE is the headline, flag it.
>    - **Hyperparameter sanity**: any LGBMRanker param changed from default? Justification attached?
>    - **Incremental fit**: `init_model` wired? `incremental_rounds` bounded? Full-refit cadence intact (default every 20 incrementals)?
>    - **Drift detector**: PSI thresholds (warn >0.2, drift >0.3)? Rolling MAE window reasonable?
>    - **Regression guard**: `retrain()` rejects a new model whose held-out ρ drops >0.1 vs previous?
> 3. Produce the ML review table per your agent spec's format, ending with a single-word verdict: APPROVED or BLOCKED.
>
> If the diff expands the public API surface (new method on `TaskRanker`, new field on `TaskRecord`, new `FeatureSchema` version), stop and escalate to `library-architect` via `/architecture-check` first — don't proceed with ML review until the API shape is signed off.
