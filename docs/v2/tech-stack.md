---
status: current
last-synced-to-plan: 2026-04-24
source: "plan §5–§6"
---

# Tech stack — Chronoq v2

## Decisions (what, rejected alternatives, why, cost)

| Layer | Pick | Rejected | Why | Cost |
|---|---|---|---|---|
| Language | Python 3.11 | 3.10, 3.12 | Matches v1; Celery 5 support | $0 |
| Packaging | `uv` workspace (continue v1) | Poetry, Rye | v1 already on it; fast; supports 5-package layout | $0 |
| **Ranker ML** | **LightGBM `LGBMRanker` (lambdarank)** | XGBoost Ranker, sklearn GBR, CatBoost, RankNet/PyTorch | `init_model` warm-start, <2s retrain on 100k, categorical-native, BSD-3, small wheel | $0 |
| Numerics | NumPy + stdlib | Pandas in ranker | No pandas in runtime (15MB anchor); Parquet→numpy direct. Pandas allowed in `bench/` only | $0 |
| Storage | SQLite + Parquet export for bench | Postgres | SQLite = right level for single-process library; Parquet 10× faster than SQLite rowscan for bench | $0 |
| Validation | Pydantic v2 (continue v1) | attrs, msgspec | v1 already on it; FastAPI free in demo-server | $0 |
| Logging | loguru (continue v1) | stdlib, structlog | Zero-config; `bind` for structured logs | $0 |
| Simulator | SimPy | Custom DES, OMNeT++ | Pure-Python, maintained, MIT, removes bespoke-sim risk | $0 |
| Traces | BurstGPT + Google Borg 2011 + Azure Functions 2019 + synthetic Pareto | Alibaba (too large) | Multiple real-workload types; all public; laptop-fits | $0 |
| **Integration target** | **Celery 5.4+** | Hatchet (no plugin API), RQ, Dramatiq | Only Python queue with documented pluggable scheduler interface; 10M+ weekly downloads | $0 |
| Plotting | matplotlib | Plotly, seaborn | PNG lingua franca; transitive via LightGBM | $0 |
| Testing | pytest + pytest-asyncio + hypothesis | — | hypothesis for rank-invariance property tests | $0 |
| Lint | ruff (continue v1) | black+flake8 | v1 config already tight | $0 |
| CI | GitHub Actions + bench-smoke | CircleCI, GitLab | Free minutes, already wired | $0 |
| Release | PyPI via `uv publish` | GitHub Releases only | T2 adopters discover via PyPI search | $0 |

**Total: $0.** Free tiers used: GitHub Actions minutes, HuggingFace token, PyPI.

## Dependencies to install

| Dep | Purpose | Size | License | Workspace |
|---|---|---|---|---|
| `lightgbm>=4.3` | Ranker | ~5MB | MIT | `ranker/` |
| `numpy>=1.26` | Matrix math | ~15MB | BSD | `ranker/` |
| `pydantic>=2.7` | Schemas | ~2MB | MIT | `ranker/` |
| `loguru>=0.7` | Logs | <1MB | MIT | `ranker/` |
| `simpy>=4.1` | DES simulator | <1MB | MIT | `bench/` |
| `matplotlib>=3.8` | Plots | ~10MB | PSF-compat | `bench/` |
| `pyarrow>=15` | Parquet | ~50MB | Apache-2 | `bench/` |
| `pandas>=2.2` | Trace munging | ~15MB | BSD | `bench/` only |
| `huggingface_hub>=0.23` | BurstGPT download | ~1MB | Apache-2 | `bench/` |
| `celery>=5.4` | Integration | ~5MB | BSD | `integrations/celery/` |
| `redis>=5` | Celery broker (v1 transitive) | 500KB | MIT | `integrations/celery/`, `demo-server/` |
| `hypothesis>=6.100` | Property tests | ~2MB | MPL-2 | root dev |
| `pre-commit>=3.7` | Git hooks (optional) | <1MB | MIT | root dev |

## Datasets

- **BurstGPT** via `huggingface_hub.snapshot_download("lzzmm/BurstGPT")` — 188MB, cached to `bench/data/` (.gitignored). 100-row sample committed for CI smoke tests.
- **Google Borg 2011** from GCS `gs://clusterdata-2011-2` (public, CC-BY 4.0). ~3.9MB shard. 100-row sample committed.
- **Azure Functions 2019** from `Azure/AzurePublicDataset` (public, CC-BY 4.0). ~137MB tarball. 100-row sample committed.
- **Synthetic Pareto trace** — generated at runtime, no download.

**No paid accounts required.** Free HF token optional (raises rate limits).

## Paid upgrade path (post-v0.2.0)

Triggers: v0.2.0 published AND at least one of — 50 stars, an interview based on the project, real staging adoption.

| Upgrade | Cost | Unlocks |
|---|---|---|
| Modal / RunPod / Vast.ai T4 | ~$10–20/mo | Train vLLM-LTR ranker on real LLM trace; ship vLLM integration |
| HuggingFace Pro (optional) | $9/mo | Publish `chronoq-traces` dataset card; faster downloads |
| Railway/Fly.io hobby | ~$5/mo | Host live demo server |

**Don't pay for:** GitHub Pro, Codecov, Sentry, Anthropic/OpenAI API.
