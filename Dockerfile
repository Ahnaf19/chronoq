FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock ./
COPY chronoq_predictor/ chronoq_predictor/
COPY chronoq_server/ chronoq_server/

# Install dependencies
RUN uv sync --no-dev --frozen

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "chronoq_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
