# Prompt: Z13 Dual-Mode Pipeline Setup

## Context

This repo (netz-analysis-engine) has a dual-mode pipeline architecture implemented. The code changes are already in place. This prompt is for setting up the Z13 machine to run the pipeline locally.

## What was implemented

1. **Pipeline cache layer** (`backend/ai_engine/cache/provider_cache.py`):
   - OCR cache: SHA-256(pdf_bytes) → cached text in SQLite
   - Embedding cache: SHA-256(chunk_text) → cached vector in SQLite
   - Location: `.data/cache/pipeline_cache.db`

2. **OCR routing** (`backend/ai_engine/pipeline/unified_pipeline.py`):
   - Cache check before any provider call
   - `OCR_PROVIDER=pymupdf` — zero-cost text extraction for text PDFs
   - `OCR_PROVIDER=local_vlm` — Vision model via LM Studio
   - `OCR_PROVIDER=mistral` — paid API (golden mode)

3. **Embedding cache** (`backend/ai_engine/openai_client.py`):
   - `create_embedding()` checks cache per-text before calling OpenAI
   - Partial-miss support: only uncached chunks are sent to API
   - After API call, new vectors stored in cache

4. **Settings** (`backend/app/core/config/settings.py`):
   - `enable_pipeline_cache: bool` — enables SQLite cache
   - `pipeline_cache_dir: str` — cache directory (.data/cache)
   - `pipeline_mode: str` — dry | golden | standard
   - `local_confidence_threshold: float` — confidence escalation knob

5. **PPM classifier fix** (`backend/ai_engine/classification/hybrid_classifier.py`):
   - `legal_lpa` TF-IDF exemplar enriched with PPM/CIM-specific vocabulary
   - Improves L2 confidence for PPMs from 0.28 to higher

6. **Copilot migrated to pgvector** (`backend/app/domains/credit/modules/ai/copilot.py`):
   - Replaced dead Azure Search stub with pgvector + cross-encoder reranker
   - `retrieve()` and `answer()` now functional with tenant isolation

## Machine setup

Z13 runs pipeline + LM Studio server (localhost). Vision models run on Legion's RTX 5070 Ti via dedicated hardware link (transparent to LM Studio — appears as localhost).

## Tasks

1. **Clone/sync the repo** on Z13
2. **Install Python dependencies**: `pip install -e ".[dev,ai,quant]"`
3. **Install LM Studio** and load:
   - GPT OSS 20B (GGUF, Q4_K_M) — text LLM for classification L3, metadata, summary
   - Vision model (e.g. Qwen2.5-VL-7B) — for OCR of scanned PDFs
4. **Start LM Studio server** on localhost:1234
5. **Create `.env.dry`**:
   ```bash
   PIPELINE_MODE=dry
   USE_LOCAL_LLM=true
   LOCAL_LLM_URL=http://localhost:1234/v1
   ENABLE_PIPELINE_CACHE=true
   OCR_PROVIDER=pymupdf
   OPENAI_API_KEY=sk-...
   DATABASE_URL=postgresql+asyncpg://netz:password@localhost:5434/netz_engine
   REDIS_URL=redis://localhost:6379/0
   ```
6. **Copy to .env**: `cp .env.dry .env`
7. **Start infrastructure**: `make up` (PostgreSQL + Redis via docker-compose)
8. **Run migrations**: `make migrate`
9. **Verify**:
   ```bash
   curl http://localhost:1234/v1/models    # LM Studio
   make test ARGS="-k pipeline"            # Pipeline tests
   ```

## Validation

After setup, run:
```bash
# First run — populates OCR + embedding cache (may use OpenAI for embeddings)
PIPELINE_MODE=dry make test ARGS="-k pipeline"

# Second run — should be near-instant (all from cache)
PIPELINE_MODE=dry make test ARGS="-k pipeline"

# Classification tests (L1/L2 free, L3 via local LLM)
PIPELINE_MODE=dry make test ARGS="-k classifier"

# Check cache stats
python -c "
import sys; sys.path.insert(0, 'backend')
from ai_engine.cache.provider_cache import ocr_cache, embedding_cache
print('OCR:', ocr_cache.stats())
print('Embed:', embedding_cache.stats())
"
```

## Reference

- Architecture doc: `docs/reference/dual-mode-pipeline-architecture.md`
- Pipeline validation: `docs/reference/pipeline-quality-validation-2026-03-19.md`
