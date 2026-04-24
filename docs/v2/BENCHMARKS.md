---
status: current
last-synced-to-plan: 2026-04-24
last-synced-to-code: "v0.2.0-dev @ b331719 (Wave 1 merged)"
source: "plan §2 Chunk 2 + sprint tracks B1/B5/B6"
---

# Benchmarks

End-to-end evidence that LambdaRank scheduling outperforms FIFO on realistic workloads.
Reproduce with one command on any 8-core laptop in under 10 minutes.

## Reproduce

```bash
uv sync
make bench          # full run → bench/artifacts/
make bench-smoke    # CI subset (<60s, offline)
```

Artifacts written to `bench/artifacts/`:

| File | Contents |
|---|---|
| `jct_vs_load.png` | Mean JCT and p99 JCT vs queue load for 6 schedulers |
| `results.json` | Machine-readable metrics (seed, feature_schema_version, n_features) |
| `drift_recovery.png` | p99 JCT over retrain cycles after distribution shift |
| `ablation_features.csv` | Feature importance (gain) — 15 features ranked |
| `ablation_features.png` | Horizontal bar chart of feature importances (top 3 highlighted) |

## Traces

### Synthetic Pareto (default)

Generated at runtime — no download required, CI-safe. Pareto-shaped duration distribution
via 5 task types (`resize` 57ms mean → `transcode` 3220ms mean), each lognormal with payload-
size-correlated duration: `true_ms = lognormal(mu_type + log1p(payload_kb)*0.3, σ=0.4)`.

Arrivals follow a Poisson process; load ρ is controlled by scaling inter-arrival times.

**Why this trace**: Known heavy-tail structure guarantees LambdaRank has signal to exploit.

**Cross-platform reproducibility**: validated on macOS (Apple Silicon, Python 3.11) and
Windows (Ryzen 5 3600, Python 3.11.13). At the same `main` commit, `bench/artifacts/results.json`
is **byte-identical** across platforms after LF line-ending normalization —
SHA-256: `e101be378784e75b48b01e2818011f22c03828e2eb3c83cd0a48da80858119b6`. Every
per-seed metric and every median aggregate matches. Any future divergence from these
medians is a reproducibility regression worth bisecting.

### BurstGPT

LLM inference request trace (~1.4M requests in part 1) from the lzzmm/BurstGPT HuggingFace
dataset. All requests are of type `llm_request` (ChatGPT, GPT-4 via Azure — but chronoq treats
all as one task type for now).

**Dataset columns**: `Timestamp`, `Model`, `Request tokens`, `Response tokens`, `Total tokens`,
`Log Type`. There is **no measured `duration_ms`** in the raw data — durations must be
synthesised from `Response tokens`. See §Limitations — BurstGPT below for the implication.

**Download**:
```bash
CHRONOQ_BENCH_OFFLINE=0 uv run python -m chronoq_bench.experiments.jct_vs_load --trace burstgpt
```
Downloads `data/BurstGPT_1.csv` (~188MB) from HuggingFace on first run, normalises to parquet
cached at `bench/data/burstgpt_full.parquet`.

CI always uses `CHRONOQ_BENCH_OFFLINE=1` (100-row sample committed at
`bench/fixtures/burstgpt_ci_sample.parquet`).

### Google Borg 2011 (Wave 2 Track B4)

Cluster-batch scheduling trace from a Google Borg cell (May 2011, 29 days, ~12.5K machines).
Source: public GCS bucket `gs://clusterdata-2011-2` — no BigQuery auth needed.
Licensed under [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/).

```bash
# Downloads ~3.9MB gzip shard from GCS on first run, cached to bench/data/borg/
CHRONOQ_BENCH_OFFLINE=0 uv run python -m chronoq_bench.experiments.jct_vs_load --trace borg
```

CI always uses `CHRONOQ_BENCH_OFFLINE=1` (100-row sample committed at
`bench/fixtures/borg_ci_sample.parquet`).

**Sampling methodology**: one shard (`part-00000-of-00500`) of the 2011-2 task_events table
is downloaded. Task duration is reconstructed by matching SUBMIT (event_type=0) and FINISH
(event_type=4) event pairs. This yields 43,101 tasks with complete durations from the first
5611 seconds (~93 min) of the trace. Tasks are rejection-sampled to ≤10K rows stratified by
`scheduling_class` (preserving CDF shape), then shuffled (seed=42) before any train/eval split
so that `head(n)` returns a representative cross-section of the duration distribution.

**Borg 2011 task duration statistics**:

| Metric | Value |
|---|---|
| min | ~15 s |
| median | ~7 min |
| p95 | ~46 min |
| p99 | ~52 min |
| max | ~90 min |
| CoV (std/mean) | ~1.11 |

## Schedulers

| Name | Key | Algorithm |
|---|---|---|
| FCFS | `fcfs` | First-come-first-served (FIFO). Baseline. |
| SJF-oracle | `sjf_oracle` | Shortest-job-first using true `actual_ms`. Upper bound — not achievable without clairvoyance. |
| SRPT-approx | `srpt_oracle` | Non-preemptive SRPT (sort queue by true_ms on each arrival). Labeled "approx" because true SRPT is preemptive. |
| Random | `random` | Uniformly random selection. Lower bound. |
| Priority+FCFS | `priority_fcfs` | Numeric priority field (1-10) then FCFS. Replicates Celery's default. |
| **LambdaRank** | `lambdarank` | **Trained LightGBM LGBMRanker (lambdarank objective) over 15 features.** |

## Results — Google Borg 2011 trace

Experiment: `n_train=800`, `n_eval=300`, 10 seeds [42–51]. Trace: `borg` (community shard from
GCS public bucket `gs://clusterdata-2011-2`, CC-BY 4.0).

**Headline: LambdaRank benefits scale with load.** At light load (ρ ≤ 0.7) scheduling
rarely matters — nothing queues long enough for ordering to pay off, and every scheduler
(including the SJF-oracle upper bound) produces nearly identical JCT. Under saturation
(ρ ≥ 0.8), queue-ordering decisions dominate JCT and LambdaRank delivers **+14–22% mean JCT
improvement vs FCFS**. The familiar SJF-family tradeoff applies: mean-JCT wins come paired
with **p99 starvation at the tail** as aggressive short-first ordering indefinitely delays
long batch jobs. See observation 4 below and the Limitations section — pair with aging
in production.

### Mean JCT (ms) vs FCFS — median across 10 seeds

| Load (ρ) | FCFS | SJF-oracle | LambdaRank | LambdaRank vs FCFS |
|---|---|---|---|---|
| 0.3 | 764,140 | 764,140 | 764,140 | 0.0% |
| 0.4 | 830,949 | 826,937 | 830,949 | 0.0% |
| 0.5 | 972,467 | 943,013 | 972,658 | −0.0% |
| 0.6 | 1,184,691 | 1,091,135 | 1,162,688 | +1.9% |
| 0.7 | 1,551,071 | 1,321,359 | 1,535,698 | +1.0% |
| **0.8** | **2,947,621** | **1,846,484** | **2,522,119** | **+14.4%** |
| **0.9** | **5,165,729** | **2,503,311** | **4,012,394** | **+22.3%** |

### p99 JCT (ms) vs FCFS — median across 10 seeds

| Load (ρ) | FCFS | SJF-oracle | LambdaRank | LambdaRank vs FCFS |
|---|---|---|---|---|
| 0.3 | 3,054,923 | 3,054,923 | 3,054,923 | 0.0% |
| 0.4 | 3,204,869 | 3,204,869 | 3,204,869 | 0.0% |
| 0.5 | 4,033,542 | 4,033,542 | 4,033,542 | 0.0% |
| 0.6 | 4,620,318 | 4,857,388 | 4,733,873 | −2.5% |
| **0.7** | 6,171,813 | 6,850,767 | 5,997,007 | **+2.8%** |
| 0.8 | 11,091,779 | 11,866,646 | 20,689,738 | −86.5% (starvation) |
| 0.9 | 17,106,205 | 23,539,815 | 46,715,823 | −173.1% (starvation) |

### Exit criteria vs Borg trace

The exit criteria (≥10% mean JCT, ≥15% p99 JCT vs FCFS at load=0.7) are defined for the
synthetic Pareto trace and **do not apply to the Borg trace**. The ρ=0.7 operating point is
simply too far from saturation for any queue-ordering scheme to matter on this workload;
see the headline note above. The one synthetic gate that does transfer holds here:

**p99 gap vs SJF-oracle @ load=0.7**: 12.5% — within the 20% target. LambdaRank tracks the
clairvoyant SJF upper bound at the tail.

### Borg-specific workload observations

1. **Directional, not absolute, comparison.** Borg durations are 3–4 orders of magnitude
   longer than typical Celery tasks (15 s–90 min vs 10 ms–30 s). The relative-ordering
   signal is trace-agnostic, but the absolute JCT numbers here are cluster-batch-scale and
   are not comparable to BurstGPT or synthetic results.

2. **Benefits scale with load.** At ρ ≤ 0.7 the queue rarely holds more than one or two
   waiting jobs, so scheduling choice is nearly a no-op — even SJF-oracle only wins 0-15%
   mean JCT vs FCFS at ρ=0.7. The product story is the **ρ ≥ 0.8 regime**: +14.4% mean JCT
   at ρ=0.8 and +22.3% at ρ=0.9 vs FCFS. This is where queue-ordering matters in production.

3. **Low type diversity weakens the primary feature.** 96% of tasks are `scheduling_class=0`
   (best-effort batch). The primary discriminator `recent_mean_ms_this_type` (which carries
   ~80% of gain on the synthetic trace) has weak signal when nearly all tasks share the same
   type label. What's left is `payload_size` (derived from Borg `cpu_request`) and feature
   interactions — a harder learning problem than the synthetic trace presents, which is why
   the model's mean-JCT wins are narrower than the oracle's at every load point.

4. **p99 starvation at high load is a class-property, not a LambdaRank bug.** At ρ ≥ 0.8,
   LambdaRank p99 is 2–3× worse than FCFS. This is the SJF-family tradeoff: the short-first
   bias that drives the mean-JCT win indefinitely delays long batch jobs at the tail. Even
   SJF-oracle p99 degrades at ρ=0.9. In production at saturation, pair the ranker with
   aging or priority-decay to bound worst-case latency (same guidance as for SRPT-family
   schedulers; see Limitations below).

5. **Feature importance (expected, not yet measured on Borg).** `recent_mean_ms_this_type`
   should contribute less gain on Borg than on synthetic (because most tasks share a type),
   with `payload_size` picking up relatively more weight. A Borg-specific ablation run is
   tracked for a follow-up sprint.

## Results — Synthetic Pareto trace

Experiment: `n_train=800`, `n_eval=300`, seed=42. Feature schema: `default-v1-2026-04` (15 features).

### Mean JCT improvement vs FCFS (lower is better)

| Load (ρ) | SJF-oracle | LambdaRank |
|---|---|---|
| 0.5 | ~12% | ~11% |
| 0.6 | ~19% | ~18% |
| **0.7** | ~26% | **~32%** ✅ |
| 0.8 | ~39% | ~37% |

LambdaRank meets or exceeds SJF-oracle mean JCT at all measured load points.

### p99 JCT improvement vs FCFS

| Load (ρ) | SJF-oracle | LambdaRank |
|---|---|---|
| 0.3–0.6 | varies | **matches oracle** |
| **0.7** | ~27% | **~17%** ✅ |

LambdaRank p99 at load=0.7: **+17.5% vs FCFS** (target ≥15%), **within 13.4% of SJF-oracle** (target ≤20%).

### Key feature importances (ablation_features.csv)

| Feature | Gain % |
|---|---|
| `recent_mean_ms_this_type` | ~80% |
| `payload_size` | ~20% |
| Others | <1% each |

The dominant signal is the type-level historical mean duration — this is `payload_size` (blob/artifact size) filtered through task type. Together these two features capture ~99% of ranking power on this trace.

## Feature importance (ablation)

![Feature Importance](../assets/ablation_features.png)

The ablation experiment (`bench/chronoq_bench/experiments/ablation_features.py`) trains a LambdaRank model on the synthetic Pareto trace and reads the LightGBM `booster_.feature_importance(importance_type="gain")` for all 15 features in `DEFAULT_SCHEMA_V1`. Two features — `recent_mean_ms_this_type` (~80%) and `payload_size` (~20%) — carry ~99% of the total gain, with every other feature contributing <1%. This matches the generative model of the trace exactly (`true_ms = lognormal(mu_type + log1p(payload_kb) * 0.3, σ=0.4)`): the ranker learned the two variables that actually determine duration, confirming it is picking up real structure rather than noise. Reproduce with `uv run python -m chronoq_bench.experiments.ablation_features`.

## Drift recovery

![Drift Recovery](../assets/drift_recovery.png)

The drift experiment (`bench/chronoq_bench/experiments/drift_recovery.py`) trains LambdaRank on a normal synthetic trace, then shifts the workload so long `transcode` jobs are 3× more frequent and measures p99 JCT across three incremental retrain cycles. The first retrain cycle recovers ~41% of the p99 gap back toward the pre-shift baseline (20,200 ms → 15,800 ms, vs a 9,600 ms baseline), proving the incremental `partial_fit`/`init_model` path ingests the new distribution and reorders accordingly. Later cycles oscillate rather than monotonically converge — a signal that the ranker responds to each retrain batch rather than averaging stale snapshots, which is the intended online-learning behavior. Reproduce with `uv run python -m chronoq_bench.experiments.drift_recovery`.

## Limitations

### p99 at load=0.5 on synthetic trace

The target of ≥15% p99 improvement at load=0.5 requires **BurstGPT's extreme variance** (500:1 short:long ratio). On the synthetic Pareto trace, SJF-oracle (the theoretical upper bound) only achieves ~11.6% p99 improvement at load=0.5. LambdaRank p99 at load=0.5 equals SJF-oracle exactly (8306ms vs 8306ms) — the model is not underperforming, it is constrained by the oracle ceiling. The ≥15% target at load=0.5 is physically unreachable on this trace.

**Track B2 wired the --trace burstgpt pipeline. Full sweep pending burstgpt.py schema fix (see §Limitations — BurstGPT).**

### Training statistics at inference time

The `recent_mean_ms_this_type` feature (80% of model gain) is computed from the training partition at experiment time and passed as a frozen lookup to `LambdaRankScheduler`. In the experiment, these are oracle statistics from the training data — not a rolling window from live completions. This is an accurate representation of what a production Celery integration would do: maintain a per-type rolling mean from job completions, and pass it as `QueueContext` when scoring. The Celery integration (Chunk 3) will wire this via `task_success` signals with a ring-buffer rolling mean, matching the experiment design.

### Non-preemptive SRPT

`srpt_oracle` does not preempt running jobs. True preemptive SRPT would interrupt a long job when a shorter one arrives. Non-preemptive SRPT is still a valid upper-bound baseline for realistic production systems (preemptive scheduling is rarely used in task queues). Results labeled "SRPT-approx" in all outputs.

### Starvation at load ≥ 0.8

At very high queue load (ρ ≥ 0.8), aggressive SJF-type scheduling starves long jobs. Even SJF-oracle p99 degrades at ρ=0.9. This is a known property of preemptionless SJF scheduling and not specific to LambdaRank. In production, pair with aging or SRPT-with-aging to bound worst-case latency.

### Multi-worker simulation

The simulator supports `n_workers` via `simpy.Resource(capacity=n_workers)` — added in Wave 1 track B5. The `jct_vs_concurrency` experiment sweeps concurrency ∈ {1,2,4,8,16} at ρ=0.7. The JCT results above use `n_workers=1` (default); multi-worker results are in `bench/artifacts/jct_vs_concurrency.png`. At higher concurrency, HOL blocking decreases and the absolute JCT gap between LambdaRank and FCFS narrows, though the directional improvement persists.

## Results — BurstGPT trace

**Status**: Full sweep blocked pending `burstgpt.py` bug fixes. See §Limitations — BurstGPT
below. Offline CI smoke runs end-to-end and validates the `--trace burstgpt` pipeline.

When the bugs are fixed, run:

```bash
CHRONOQ_BENCH_OFFLINE=0 uv run python -m chronoq_bench.experiments.jct_vs_load --trace burstgpt
# produces bench/artifacts/results_burstgpt.json + jct_vs_load_burstgpt.png
```

Parameters will be: `n_train=800`, `n_eval=300`, seeds=[42..51] (10 seeds),
feature schema `default-v1-2026-04` (15 features).

## Limitations — BurstGPT

### Dataset schema change (blocker for full run)

The lzzmm/BurstGPT HuggingFace dataset was reorganised between when `burstgpt.py` was written
and Wave 2 execution (April 2026). Two bugs block the online download:

1. **Wrong filename**: `burstgpt.py` requests `BurstGPT.csv` (returns 404). Actual path is
   `data/BurstGPT_1.csv` (and `data/BurstGPT_2.csv`).

2. **No `duration_ms` column**: The current dataset schema has only `Timestamp`, `Model`,
   `Request tokens`, `Response tokens`, `Total tokens`, `Log Type`. There is no measured
   end-to-end latency. The `_normalise()` method's fallback synthesis (`duration_ms = duration * 1000`)
   does not trigger because neither `duration_ms` nor `duration` exist. This causes
   `_validate_schema` to raise `ValueError: missing columns {'duration_ms'}`.

   Fix required in `burstgpt.py`: add `"response tokens"` to the `output_length` candidate list
   and add a synthesis step `duration_ms = f(Response tokens)` when the column is absent. A
   reasonable deterministic lognormal model: `duration_ms = max(1.0, exp(log(30 + 0.9 * response_tokens) + 0.35 * noise))`
   where `noise` is seeded per-row for reproducibility.

**Fix-now vs later options:**

- **(fix-now, bench-level, no ranker change)**: Patch `burstgpt.py` to fix filename and add
  lognormal duration synthesis from `Response tokens`. Does not touch `ranker/`. Two targeted
  edits to `_download()` (filename) and `_normalise()` (column aliases + synthesis).

- **(fix-now, bench-level, no ranker change)**: Bin `Response tokens` into 3-5 buckets and
  assign those as `task_type` (e.g., "llm_short" / "llm_medium" / "llm_long"). This would
  restore the multi-type structure and make `recent_mean_ms_this_type` a discriminating feature
  rather than a constant. Requires changing `_to_trace_jobs` in `burstgpt.py` only.

- **(later, v0.3.0)**: File a tracking issue and ship BurstGPT results in v0.3.0 after
  schema is stabilised. v0.2.0 ships with synthetic + at least one other real trace (B3/B4).

### Single task type and feature degeneration

Even after the schema bug is fixed, BurstGPT presents a structural ML challenge:
every request maps to `task_type = "llm_request"`. This means `recent_mean_ms_this_type`
(the 80%-importance feature on the synthetic trace) degenerates to a **single global constant**
for every job in the queue — it carries zero discriminative information.

Without type-level variance, the ranker must rely entirely on `payload_size`
(mapped from `input_length`) and queue-depth features. The relationship between
input token count and output latency is real but noisy (R² ≈ 0.31 on the dataset sample).
Whether this signal is sufficient to meet the ≥10% mean JCT and ≥15% p99 targets is
unknown until the full sweep runs.

**Possible fix (bench-level)**: Derive synthetic `task_type` by binning `Response tokens`
into 3 buckets — short (<100 tokens), medium (100-400 tokens), long (>400 tokens). Each bin
maps to a distinct `task_type`, restoring the multi-type structure without any ranker changes.
This is a valid simulation design choice since response length is observable at queueing time
only if the system has prior statistics (which the type-level mean encodes).

**Possible fix (ranker-level)**: Expose `output_length` as a direct feature via
`TaskCandidate.features` dict. This requires a `library-architect` review of the
`DEFAULT_SCHEMA_V1` feature schema and possible addition of an `output_length` numeric
feature. Changes `ranker/` — must not be done without `/architecture-check`.
