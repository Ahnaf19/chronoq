Run the full validation suite: lint, format check, and all tests. Report any failures with file paths and line numbers. If everything passes, confirm the counts (tests passed, files checked).

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -v --tb=short
```

If any step fails, diagnose the root cause and suggest a fix — do not just report the error.
