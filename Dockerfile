FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first (layer caching)
COPY pyproject.toml uv.lock* ./

# Install dependencies (all pure-Python — no gcc/build deps needed)
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

# Copy app code
COPY app.py ./
COPY templates/ templates/
COPY static/ static/

# --preload: share memory via copy-on-write
# --max-requests: recycle worker to prevent memory leaks
CMD uv run gunicorn app:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 1 \
    --preload \
    --bind "0.0.0.0:${PORT:-8080}" \
    --timeout 120 \
    --max-requests 400 \
    --max-requests-jitter 50
