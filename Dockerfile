FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Layer 1: dependency metadata only (changes rarely)
COPY pyproject.toml uv.lock ./
COPY chronoq_predictor/pyproject.toml chronoq_predictor/pyproject.toml
COPY chronoq_server/pyproject.toml chronoq_server/pyproject.toml

# Layer 2: install deps (cached unless pyproject.toml or uv.lock change)
# Stub out the packages so uv sync can resolve workspace members
RUN mkdir -p chronoq_predictor/chronoq_predictor chronoq_server/chronoq_server && \
    touch chronoq_predictor/chronoq_predictor/__init__.py chronoq_server/chronoq_server/__init__.py && \
    uv sync --no-dev --frozen

# Layer 3: actual source code (changes often, but deps are cached above)
COPY chronoq_predictor/ chronoq_predictor/
COPY chronoq_server/ chronoq_server/

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "chronoq_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
