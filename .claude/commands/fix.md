Auto-fix all lint and format issues, then verify tests still pass.

Steps:
1. Run `uv run ruff check . --fix` to auto-fix lint issues
2. Run `uv run ruff format .` to format all files
3. Run `uv run pytest --tb=short -q` to verify nothing broke
4. Run `git diff --stat` to show what changed

If tests fail after auto-fix, investigate and fix manually rather than reverting the lint fixes.
