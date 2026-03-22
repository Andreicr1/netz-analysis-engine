# Netz Analysis Engine — Backend + Workers
# Single image, entrypoint differentiates: uvicorn (backend) vs dispatch (workers)
# Target: Cloudflare Containers (linux/amd64)

FROM python:3.12-slim AS base

WORKDIR /app

# System dependencies for asyncpg, scipy, scikit-learn, torch
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies (cached layer)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[ai,quant,edgar]"

# Application code
COPY backend/ backend/
COPY profiles/ profiles/
COPY calibration/ calibration/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Run from backend/ so module resolution matches dev (app.main:app)
WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
