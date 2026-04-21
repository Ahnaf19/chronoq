Run tests for a specific scope. If no argument is given, run all tests.

Usage: /test [scope]
- /test → all tests
- /test ranker → tests/ranker/ only
- /test server → tests/server/ only
- /test bench → tests/bench/ only (Chunk 2+)
- /test celery → tests/celery/ only (Chunk 3+)
- /test <filename> → specific test file or -k name pattern

Argument: $ARGUMENTS

Based on the argument:
- If empty or "all": run `uv run pytest -v --tb=short`
- If "ranker" (or legacy alias "predictor"): run `uv run pytest tests/ranker/ -v --tb=short`
- If "server": run `uv run pytest tests/server/ -v --tb=short`
- If "bench": run `uv run pytest tests/bench/ -v --tb=short`
- If "celery": run `uv run pytest tests/celery/ -v --tb=short`
- Otherwise: run `uv run pytest -k "$ARGUMENTS" -v --tb=short`

After running, summarize: total passed, total failed, and any failure details with file:line references.
