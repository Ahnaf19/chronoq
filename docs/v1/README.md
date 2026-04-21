# Chronoq v1 docs (archived)

These describe **Chronoq v1** — a self-hosted FastAPI + Redis task queue with a point-regression duration predictor. **v1 is superseded by v2; see [`../v2/`](../v2/) for current design.**

The v1 code still exists at `demo-server/` as a reference integration (one way to embed the ranker library inside a FastAPI + Redis stack). It is no longer "the product."

## Contents

| File | Scope |
|---|---|
| [architecture.md](architecture.md) | v1 layered architecture (predictor / server / queue / workers) |
| [user-guide.md](user-guide.md) | v1 setup + usage + integration patterns |
| [api-reference.md](api-reference.md) | v1 REST API (POST/GET /tasks, /metrics) |
| [configuration.md](configuration.md) | v1 env vars + `PredictorConfig` |
| [chronoq-plan.md](chronoq-plan.md) | v1 original design doc |
| [diagrams.md](diagrams.md) | v1 Mermaid + ASCII diagrams |
| [chronoq-architecture.excalidraw](chronoq-architecture.excalidraw) | v1 visual architecture |
| [postman/](postman/) | v1 API Postman collection + environment |

## Name translations (v1 → v2)

When reading these, mentally translate:

- `chronoq_predictor` → `chronoq_ranker`
- `chronoq_server` → `chronoq_demo_server`
- `predictor/` directory → `ranker/`
- `server/` directory → `demo-server/`
- `TaskPredictor` class → `TaskRanker` (renamed in Chunk 1)
- Point regression (sklearn `GradientBoostingRegressor`) → Pairwise ranker (LightGBM `LGBMRanker`, Chunk 1)
- Fixed 4-feature vector → User-declarable `FeatureSchema` (Chunk 1)

The v1 API routes and Redis queue layout remain accurate for `demo-server/`.
