# Netz Analysis Engine — Backend + Workers
# Single image, entrypoint differentiates: uvicorn (backend) vs dispatch (workers)
# Target: Cloudflare Containers (linux/amd64, no GPU — CPU-only torch)
#
# Build from repo root: docker build -t netz-backend .

FROM python:3.12-slim AS base

WORKDIR /app

# System dependencies for asyncpg, scipy, scikit-learn
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy all source needed for package install
COPY pyproject.toml ./
COPY backend/ backend/
COPY profiles/ profiles/
COPY calibration/ calibration/

# Install CPU-only torch FIRST (avoids pulling ~3.5GB of CUDA/NVIDIA libs)
# Then install everything else (torch already satisfied, pip skips CUDA deps)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir ".[ai,quant,edgar]"

# Install Playwright Chromium for HTML→PDF rendering
RUN python -m playwright install chromium --with-deps

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Run from backend/ so module resolution matches dev (app.main:app)
WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
