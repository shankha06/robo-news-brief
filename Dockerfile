FROM python:3.12-slim

# Install system deps for lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev libxslt1-dev gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first (layer caching)
COPY pyproject.toml uv.lock ./

# Install dependencies (no venv needed inside container)
RUN uv sync --frozen --no-dev

# Copy app code
COPY app.py ./
COPY templates/ templates/
COPY static/ static/

# Production settings
ENV PORT=8080
ENV FLASK_DEBUG=0

EXPOSE 8080

CMD ["uv", "run", "gunicorn", "app:app", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--timeout", "120"]
