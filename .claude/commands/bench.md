Invoke the `benchmark-analyst` subagent with this task:

> Run `/bench`: execute the full benchmark harness and analyze results.
>
> 1. Run `make bench` (captures output).
> 2. Read `bench/artifacts/results.json`.
> 3. Evaluate all Chunk 2 exit criteria (see your agent spec).
> 4. Check for regressions vs any previously committed results.json (use git show HEAD:bench/artifacts/results.json if available).
> 5. Read `bench/artifacts/ablation_features.csv` — report top 3 features.
> 6. Produce the standard benchmark report: pass/fail table + verdict (MERGE-READY or BLOCKED).
