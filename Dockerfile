# NEXUS Enterprise AI Platform - Dockerfile
# Multi-stage build for minimal production image

# ── Stage 1: Builder ─────────────────────────────────────────────────────────
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | POETRY_HOME=/opt/poetry python3 -
ENV PATH="/opt/poetry/bin:$PATH"

# Copy poetry files
COPY pyproject.toml poetry.lock* ./

# Install dependencies (production only)
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi

# ── Stage 2: Production ──────────────────────────────────────────────────────
FROM python:3.11-slim as production

WORKDIR /app

# Runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash nexus

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=nexus:nexus . .

# Create data directories
RUN mkdir -p /app/data/faiss /app/data/chroma /app/logs \
    && chown -R nexus:nexus /app/data /app/logs

USER nexus

# Expose ports
EXPOSE 8000 8501

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command
CMD ["uvicorn", "nexus.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Stage 3: Development ─────────────────────────────────────────────────────
FROM production as development

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    vim \
    && rm -rf /var/lib/apt/lists/*

USER nexus

# Install dev dependencies
RUN poetry install --no-interaction --no-ansi

# Enable hot reload
ENV PYTHONPATH=/app
CMD ["uvicorn", "nexus.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
