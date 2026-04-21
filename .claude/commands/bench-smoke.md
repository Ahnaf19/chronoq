Invoke the `benchmark-analyst` subagent with this task:

> Run `/bench-smoke`: execute the CI smoke benchmark and verify it completes without error.
>
> 1. Run `make bench-smoke` (should complete in <60s).
> 2. Verify all three experiment scripts ran without exceptions.
> 3. Verify `bench/artifacts/results.json` was written and is valid JSON with required keys:
>    feature_schema_version, n_features, seed, trace, load_points, schedulers.
> 4. Report: PASS (all three experiments completed, results.json valid) or FAIL with error detail.
>
> Note: smoke mode uses reduced data (n_train=200, n_eval=100). Numbers will not hit
> exit-criteria targets — only check for runtime errors and artifact completeness.
