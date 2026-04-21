.PHONY: help bench bench-smoke test lint fix sync clean

help:
	@echo "Chronoq v2 — top-level targets:"
	@echo "  make sync         — uv sync (install workspace deps)"
	@echo "  make test         — run all tests"
	@echo "  make lint         — ruff check + format check"
	@echo "  make fix          — ruff check --fix + format"
	@echo "  make bench        — run full benchmark harness (stub until Chunk 2)"
	@echo "  make bench-smoke  — run 1k-record smoke bench (<60s, stub until Chunk 2)"
	@echo "  make clean        — remove caches"

sync:
	uv sync

test:
	uv run pytest -v

lint:
	uv run ruff check .
	uv run ruff format --check .

fix:
	uv run ruff check --fix .
	uv run ruff format .

bench:
	@echo "⚠️  make bench is a stub. Real harness lands in Chunk 2."
	@echo "    See /Users/ahnaftanjid/.claude/plans/ok-i-want-golden-knuth.md §4 Chunk 2."

bench-smoke:
	@echo "⚠️  make bench-smoke is a stub. Real harness lands in Chunk 2."

clean:
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
