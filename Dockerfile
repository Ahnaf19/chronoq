FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Layer 1: dependency metadata only (changes rarely)
COPY pyproject.toml uv.lock ./
COPY predictor/pyproject.toml predictor/pyproject.toml
COPY server/pyproject.toml server/pyproject.toml

# Layer 2: install deps (cached unless pyproject.toml or uv.lock change)
# Stub out the packages so uv sync can resolve workspace members
RUN mkdir -p predictor/chronoq_ranker server/chronoq_demo_server && \
    touch predictor/chronoq_ranker/__init__.py server/chronoq_demo_server/__init__.py && \
    uv sync --no-dev --frozen

# Layer 3: actual source code (changes often, but deps are cached above)
COPY predictor/ predictor/
COPY server/ server/

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "chronoq_demo_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
