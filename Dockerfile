FROM python:3.12-slim

# Install system deps for lxml + Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev libxslt1-dev gcc libjpeg-dev zlib1g-dev libwebp-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first (layer caching)
COPY pyproject.toml uv.lock* ./

# Install dependencies
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

# Pre-download nltk data needed by newspaper4k
RUN uv run python -c "import nltk; nltk.download('punkt_tab', quiet=True)"

# Copy app code
COPY app.py ./
COPY templates/ templates/
COPY static/ static/

# Use UvicornWorker for ASGI support
CMD uv run gunicorn app:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 1 \
    --bind "0.0.0.0:${PORT:-8080}" \
    --timeout 120
