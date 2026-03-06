Verify the critical package boundary: chronoq-predictor must never import from chronoq-server.

Run these checks:
1. `grep -r "chronoq_server" predictor/` — must return nothing
2. `grep -r "from chronoq_server" tests/predictor/` — must return nothing
3. `grep -r "import redis" predictor/` — must return nothing
4. `grep -r "import fastapi" predictor/` — must return nothing

Report pass/fail for each check. If any fails, identify the offending file and line.
