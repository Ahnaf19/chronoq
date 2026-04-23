FROM python:3.11-slim

# Install build tools required by LightGBM and numpy
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
RUN pip install --no-cache-dir "uv>=0.4"

WORKDIR /workspace

# ── Copy workspace definition files (needed for lock resolution) ──────────
COPY pyproject.toml uv.lock ./

# Copy workspace member pyproject.toml files so uv can resolve the
# full workspace dependency graph.
COPY ranker/pyproject.toml ./ranker/pyproject.toml
COPY integrations/celery/pyproject.toml ./integrations/celery/pyproject.toml
COPY bench/pyproject.toml ./bench/pyproject.toml
COPY demo-server/pyproject.toml ./demo-server/pyproject.toml

# Stub out the non-essential workspace members so hatchling can build
# their editable wheels without failing on missing source files.
RUN mkdir -p bench/chronoq_bench demo-server/chronoq_demo_server \
    && touch bench/chronoq_bench/__init__.py \
             demo-server/chronoq_demo_server/__init__.py \
             bench/README.md \
             demo-server/README.md

# ── Copy source for the two packages we actually need ─────────────────────
COPY ranker/ ./ranker/
COPY integrations/celery/ ./integrations/celery/

# ── Create venv and install ONLY ranker + celery deps ─────────────────────
# We create a standalone venv then install the two packages and their
# transitive deps directly, bypassing the full workspace sync that would
# pull in bench/demo-server deps (pandas, simpy, fastapi, etc.).
RUN uv venv /workspace/.venv \
    && uv pip install \
        --python /workspace/.venv/bin/python \
        --no-cache \
        ranker/ \
        integrations/celery/

# Activate the venv for all subsequent RUN/CMD steps
ENV PATH="/workspace/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/workspace/.venv"

# ── Copy the demo scripts ─────────────────────────────────────────────────
COPY examples/celery-docker/ ./examples/celery-docker/

WORKDIR /workspace/examples/celery-docker

# Default: run the Celery worker directly from the venv (no uv run overhead).
# The producer service overrides this CMD in docker-compose.yml.
CMD ["celery", "-A", "worker", "worker", "--loglevel=INFO", "--concurrency=4"]
