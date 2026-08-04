# ── Single-container deploy (Render / Fly.io) ────────────────────────────────
# Runs the FastAPI gateway, the arq ingestion worker, and schema migrations
# in ONE container — a single deployment to keep cold starts and ops simple.
#
# Two stages:
#   builder  — installs Python deps via uv into a venv
#   runtime  — copies the venv only; stays small and fast to boot

FROM python:3.12-slim AS builder

# uv needs these for a fast, reliable install
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Runtime deps for Docling/whisper extraction; keep light so boot is fast
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY . .

# The container owns migrations too, so `render deploy` is one atomic step.
# Entrypoint: apply schema, then run arq worker + uvicorn in the same process group.
CMD ["sh", "-c", \
     "alembic upgrade head && \
      arq app.workers.WorkerSettings & \
      uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
