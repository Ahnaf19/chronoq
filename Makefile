.PHONY: help bench bench-smoke celery-demo test lint fix sync clean

help:
	@echo "Chronoq v2 — top-level targets:"
	@echo "  make sync         — uv sync (install workspace deps)"
	@echo "  make test         — run all tests"
	@echo "  make lint         — ruff check + format check"
	@echo "  make fix          — ruff check --fix + format"
	@echo "  make bench        — full benchmark harness (~5 min, writes bench/artifacts/)"
	@echo "  make bench-smoke  — CI smoke bench (<60s, OFFLINE mode)"
	@echo "  make celery-demo  — run 200-task fifo vs active JCT comparison"
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
	@echo "==> jct_vs_load experiment"
	uv run python -m chronoq_bench.experiments.jct_vs_load
	@echo "==> drift_recovery experiment"
	uv run python -m chronoq_bench.experiments.drift_recovery
	@echo "==> ablation_features experiment"
	uv run python -m chronoq_bench.experiments.ablation_features
	@echo "==> artifacts written to bench/artifacts/"

bench-smoke:
	CHRONOQ_BENCH_SMOKE=1 CHRONOQ_BENCH_OFFLINE=1 uv run python -m chronoq_bench.experiments.jct_vs_load
	CHRONOQ_BENCH_SMOKE=1 CHRONOQ_BENCH_OFFLINE=1 uv run python -m chronoq_bench.experiments.drift_recovery
	CHRONOQ_BENCH_SMOKE=1 CHRONOQ_BENCH_OFFLINE=1 uv run python -m chronoq_bench.experiments.ablation_features

celery-demo:
	uv run python integrations/celery/demo.py

clean:
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
