# syntax=docker/dockerfile:1
#
# Backend image for the math-practice FastAPI service.
#
# Build from the REPO ROOT (the build context must include the uv workspace
# root + the common-lib it depends on):
#
#   docker build -f packages/backend/Dockerfile -t math-practice-backend .
#
# Run (supplying production env + a writable volume for file-SQLite):
#
#   docker run --rm -p 8000:8000 \
#     --env-file packages/backend/.env.prod \
#     -v math-data:/data \
#     math-practice-backend
#
# NOTE: the default in-memory / file-SQLite store is per-process, so the image
# runs uvicorn with a SINGLE worker. Use Postgres (and add a driver) before
# scaling to multiple workers/instances.

# ---- builder: resolve + install the backend (and its workspace deps) ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Workspace metadata + members (common-lib is a workspace dependency of backend).
# .dockerignore trims node_modules/dist/.venv so this stays small.
COPY pyproject.toml uv.lock ./
COPY packages/ ./packages/

# Install only the backend package and its dependencies, from the locked set.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package math-practice-backend

# ---- runtime: slim image with just the venv + source ----
FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Non-root user, and a writable data dir for the default file-SQLite volume.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown -R app:app /data

COPY --from=builder --chown=app:app /app /app

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

# Single worker on purpose (see note above). For platforms that inject $PORT,
# override this CMD or wrap it in a shell that reads the port.
CMD ["uvicorn", "math_practice_backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
