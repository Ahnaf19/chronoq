Run tests for a specific scope. If no argument is given, run all tests.

Usage: /test [scope]
- /test → all tests
- /test predictor → tests/predictor/ only
- /test server → tests/server/ only
- /test <filename> → specific test file by name pattern

Argument: $ARGUMENTS

Based on the argument:
- If empty or "all": run `uv run pytest -v --tb=short`
- If "predictor": run `uv run pytest tests/predictor/ -v --tb=short`
- If "server": run `uv run pytest tests/server/ -v --tb=short`
- Otherwise: run `uv run pytest -k "$ARGUMENTS" -v --tb=short`

After running, summarize: total passed, total failed, and any failure details with file:line references.
