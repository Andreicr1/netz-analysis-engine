# Dual-Mode Pipeline Architecture — Local Testing + Golden Validation

## Architecture Overview

```
  ┌─────────────────────────────────────────────────────────────┐
  │              Z13 (Pipeline Orchestration + LLM)              │
  │  ROG Flow Z13 — Ryzen AI MAX+ 395, 64GB unified            │
  │                                                             │
  │  LM Studio Server (localhost:1234)                          │
  │  ├── GPT OSS 20B (text LLM)                                │
  │  │   └── Classification L3, metadata extraction, summary   │
  │  └── Vision model (VLM OCR) — via Legion GPU link          │
  │                                                             │
  │  Pipeline (unified_pipeline.py)                             │
  │    │                                                        │
  │    ├── OCR ──────┬── Cache HIT → SQLite (.data/cache/)     │
  │    │             ├── PyMuPDF (text PDFs, zero cost)         │
  │    │             ├── Local VLM (localhost:1234, Vision)     │
  │    │             └── Mistral API (golden mode)              │
  │    │                                                        │
  │    ├── Classify ─┬── L1 Rules (deterministic, free)        │
  │    │             ├── L2 TF-IDF (deterministic, free)       │
  │    │             ├── L3 Local LLM (localhost:1234)          │
  │    │             └── L3 OpenAI (golden mode)               │
  │    │                                                        │
  │    ├── Chunk ────── Deterministic (free)                    │
  │    │                                                        │
  │    ├── Extract ──┬── Local LLM (localhost:1234)             │
  │    │             └── OpenAI (golden mode)                   │
  │    │                                                        │
  │    ├── Embed ────┬── Cache HIT → SQLite (.data/cache/)     │
  │    │             └── OpenAI API (only cache misses)         │
  │    │                                                        │
  │    ├── Upsert ───── pgvector (local PostgreSQL, free)      │
  │    └── Store ────── LocalStorage (.data/lake/, free)       │
  │                                                             │
  │  Docker: PostgreSQL 16 + TimescaleDB + Redis 7             │
  └─────────────────────────────────────────────────────────────┘
                        │
          ┌─────────────┴──────────────┐
          │  Legion 7i Pro (GPU Link)   │
          │  RTX 5070 Ti (12GB VRAM)   │
          │  Serves Vision models via   │
          │  dedicated hardware link    │
          │  (transparent to app layer) │
          └────────────────────────────┘
```

**Key design:** Z13 runs both pipeline and LM Studio server. Vision models that need NVIDIA CUDA run on Legion's RTX 5070 Ti via dedicated hardware link — this is transparent to the application (appears as localhost to LM Studio). No network URLs or IP addresses in code.

---

## Pipeline Modes

| Mode | OCR | LLM | Embeddings | Cost | Use Case |
|------|-----|-----|------------|------|----------|
| **dry** | Cache → PyMuPDF → Local VLM | Local LLM (localhost) | Cache (OpenAI for misses) | ~$0/day | Large-scale dev testing |
| **golden** | Mistral API | OpenAI API | OpenAI API | ~$5-10/run | Final quality validation |
| **standard** | Whatever configured | Whatever configured | Whatever configured | Variable | Normal development |

---

## Environment Variables

### MODE 1 — Dry / Local Testing (.env.dry)

```bash
# Pipeline mode
PIPELINE_MODE=dry

# Cache (critical for cost reduction)
ENABLE_PIPELINE_CACHE=true
PIPELINE_CACHE_DIR=.data/cache

# LLM → LM Studio local server
USE_LOCAL_LLM=true
LOCAL_LLM_URL=http://localhost:1234/v1

# OCR → cache first, PyMuPDF fallback (zero cost)
OCR_PROVIDER=pymupdf
# OR for scanned PDFs: OCR_PROVIDER=local_vlm (requires Vision model)

# Embeddings → OpenAI API (cached after first run)
OPENAI_API_KEY=sk-...

# Confidence fallback (optional)
LOCAL_CONFIDENCE_THRESHOLD=0.0   # 0.0 = never escalate
```

### MODE 2 — Golden / Final Validation (.env.golden)

```bash
# Pipeline mode
PIPELINE_MODE=golden

# Cache disabled for clean validation
ENABLE_PIPELINE_CACHE=false

# External providers (full quality)
USE_LOCAL_LLM=false
OCR_PROVIDER=mistral
OPENAI_API_KEY=sk-...
MISTRAL_API_KEY=...
```

### Switching Modes

```bash
# Quick switch via copy
cp .env.dry .env     # local testing
cp .env.golden .env  # final validation

# Or override per-run
PIPELINE_MODE=dry USE_LOCAL_LLM=true make test ARGS="-k pipeline"
```

---

## Z13 Setup (Pipeline + Inference)

### LM Studio Server

1. Install LM Studio from https://lmstudio.ai
2. Download GPT OSS 20B model (GGUF format, Q4_K_M quantization)
3. Load model in LM Studio
4. Enable server: **Settings → Local Server → Start Server**
5. Port **1234** (default), host **localhost**
6. Verify:
   ```bash
   curl http://localhost:1234/v1/models
   ```

### Vision Model for OCR

For scanned/image PDFs, load a Vision model (e.g. `qwen2.5-vl-7b-instruct`) in LM Studio. The Vision inference runs on Legion's RTX 5070 Ti via the dedicated hardware link — transparent to LM Studio.

Set `OCR_PROVIDER=local_vlm` in .env to activate.

**Note:** For text-based PDFs, `OCR_PROVIDER=pymupdf` extracts text without any model call (zero cost).

### Verify Local LLM

```bash
curl -X POST http://localhost:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-oss-20b",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 50
  }'
```

---

## Caching Architecture

### OCR Cache

```
Pipeline processes document.pdf
  │
  ├── SHA-256(pdf_bytes) → hash
  ├── Lookup hash in .data/cache/pipeline_cache.db
  │   ├── HIT → return cached OCR text (zero cost)
  │   └── MISS → call OCR provider → store result in cache
  │
  └── Future runs: same PDF = instant cache hit
```

**Impact:** A document OCR'd once is free on every subsequent pipeline run.

### Embedding Cache

```
Pipeline embeds 540 chunks
  │
  ├── SHA-256(chunk_text) → hash per chunk
  ├── Batch lookup in .data/cache/pipeline_cache.db
  │   ├── 530 HITs → return cached vectors
  │   └── 10 MISSes → call OpenAI for 10 chunks only
  │
  └── Cost: $0.001 instead of $0.02 (95% reduction)
```

### Cache Location

```
.data/cache/
  pipeline_cache.db       ← SQLite (WAL mode, thread-safe)
    ├── ocr_cache          (hash, filename, page_count, text, created_at)
    └── embedding_cache    (hash, model, dim, vector, created_at)
```

### Cache Management

```bash
# Check cache stats
python -c "
from ai_engine.cache.provider_cache import ocr_cache, embedding_cache
print('OCR:', ocr_cache.stats())
print('Embed:', embedding_cache.stats())
"

# Clear cache (start fresh)
rm .data/cache/pipeline_cache.db
```

---

## Test Strategy

### A) Dry Test Suite (Large Scale, Local)

```bash
# Run full pipeline tests with local providers
PIPELINE_MODE=dry USE_LOCAL_LLM=true ENABLE_PIPELINE_CACHE=true \
  make test ARGS="-k pipeline"

# Run classification tests (L1/L2 = free, L3 = local LLM)
PIPELINE_MODE=dry USE_LOCAL_LLM=true \
  make test ARGS="-k classifier"
```

**Validates:**
- Prompt formatting and template rendering
- Classification L1/L2 rule accuracy (100% deterministic)
- Classification L3 fallback (local LLM quality)
- Pipeline flow integrity (all stages execute in order)
- Validation gates (OCR quality, chunk sizing, embedding dims)
- Storage routing and dual-write ordering
- Tenant isolation (pgvector WHERE clauses)

### B) Golden Test Suite (Small, External APIs)

```bash
# Run golden validation on curated dataset
PIPELINE_MODE=golden ENABLE_PIPELINE_CACHE=false \
  make test ARGS="-k golden"

# Run E2E smoke test (requires all external APIs)
PIPELINE_MODE=golden \
  python backend/tests/e2e_smoke_test.py
```

**Validates:**
- OCR quality on real PDFs (Mistral vs local)
- Classification accuracy on ambiguous documents
- Metadata extraction quality (gpt-4.1 vs local 20B)
- Embedding cosine similarity thresholds
- End-to-end pipeline correctness

---

## Fallback Logic

### Confidence-Based Escalation (Optional)

When `LOCAL_CONFIDENCE_THRESHOLD > 0`, the classifier can escalate to OpenAI if the local LLM returns low confidence:

```
Layer 3 (LLM Fallback):
  ├── Call local LLM
  ├── If confidence >= threshold → accept
  └── If confidence < threshold → call OpenAI (paid, but rare)
```

**Note:** Not currently wired into the classifier code. Settings knob ready for future implementation. L1/L2 layers catch ~90% of documents deterministically.

---

## Cost Analysis

### Before (current state)

| Step | Provider | Cost/doc | Daily (50 docs x 10 runs) |
|------|----------|----------|--------------------------|
| OCR | Mistral | $0.03 | $15.00 |
| Classification L3 | OpenAI | $0.01 | $0.50 |
| Metadata | OpenAI | $0.05 | $25.00 |
| Summary | OpenAI | $0.01 | $5.00 |
| Embeddings | OpenAI | $0.02 | $10.00 |
| **Total** | | | **$55.50/day** |

### After (dry mode with cache)

| Step | Provider | Cost | Daily (50 docs x 10 runs) |
|------|----------|------|--------------------------|
| OCR | Cache / PyMuPDF | $0.00 | $0.00 |
| Classification L3 | Local LLM | $0.00 | $0.00 |
| Metadata | Local LLM | $0.00 | $0.00 |
| Summary | Local LLM | $0.00 | $0.00 |
| Embeddings | Cache (OpenAI 1st run only) | $0.00 | ~$1.00 first run |
| **Total** | | | **~$0/day** |

Golden validation: ~$5.55 per run (once per release cycle).

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/core/config/settings.py` | Added `enable_pipeline_cache`, `pipeline_cache_dir`, `pipeline_mode`, `local_confidence_threshold` |
| `backend/ai_engine/cache/__init__.py` | New package |
| `backend/ai_engine/cache/provider_cache.py` | New: OCR + embedding cache (SQLite, thread-safe) |
| `backend/ai_engine/pipeline/unified_pipeline.py` | OCR cache check before API call, PyMuPDF fallback, cache store after OCR |
| `backend/ai_engine/openai_client.py` | Embedding cache: check before API, store after API, partial-miss support |

---

## Quick Start (on Z13)

```bash
# 1. Start LM Studio → Load GPT OSS 20B → Start Server (localhost:1234)

# 2. Configure environment
cat > .env.dry <<EOF
PIPELINE_MODE=dry
USE_LOCAL_LLM=true
LOCAL_LLM_URL=http://localhost:1234/v1
ENABLE_PIPELINE_CACHE=true
OCR_PROVIDER=pymupdf
OPENAI_API_KEY=sk-...
EOF
cp .env.dry .env

# 3. Verify local server
curl http://localhost:1234/v1/models

# 4. Run pipeline (first run caches OCR + embeddings)
make test ARGS="-k pipeline"

# 5. Re-run (cache hits = zero API cost)
make test ARGS="-k pipeline"
```
