# E2E Deep Review — CUDA Reranker Validation (Continuation)

> Execute on the NVIDIA machine (RTX 5070 Ti) after `git pull origin main`.

---

## Context

PR #89 merged to main. The deep review retrieval pipeline is fully migrated to pgvector + CrossEncoder reranker. An E2E retrieval-only run was completed on an AMD machine (CPU-only PyTorch) and validated signal differentiation:

- 2 HIGH + 3 MODERATE + 9 AMBIGUOUS (was 14/14 AMBIGUOUS in baseline)
- 5 SATURATED + 9 CONTESTED (was 14/14 CONTESTED)
- Reranker was on CPU: 691s retrieval time

This session re-runs the same E2E on the NVIDIA machine with CUDA to:
1. Validate CrossEncoder runs on GPU (should see `Use pytorch device: cuda`)
2. Measure GPU retrieval timing (expect ~30-60s vs 691s CPU)
3. Confirm signal differentiation is identical (same deal, same DB, same embeddings)
4. If time permits, run full pipeline (Stages 1-14) with LLM

## Pre-Flight

### 1. Pull and verify

```bash
git checkout main && git pull origin main
make check  # 1507+ tests expected
```

### 2. Verify CUDA

```python
import torch
print(f"CUDA: {torch.cuda.is_available()}")
print(f"Device: {torch.cuda.get_device_name(0)}")
```

If `torch.cuda.is_available() == False`, install CUDA torch:
```bash
pip install torch==2.10.0 --index-url https://download.pytorch.org/whl/cu128 --force-reinstall --no-deps
```

### 3. Verify CrossEncoder loads on GPU

```python
from sentence_transformers import CrossEncoder
model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
# Should print: Use pytorch device: cuda
scores = model.predict([("test query", "test passage")])
print(f"Score: {scores}")  # Should work without errors
```

### 4. Verify DB connectivity

The `.env` should have `DATABASE_URL` pointing to Timescale Cloud. The sync engine in `pgvector_search_service.py` derives from this with `?sslmode=require`.

```bash
make up  # docker-compose for local PG + Redis (needed for some imports)
```

### 5. LM Studio (optional — only if running full pipeline)

Load `qwen/qwen3-14b` with:
- Context length: 32768
- GPU layers: -1 (all on GPU)
- Flash Attention: ON
- Thinking: disabled (to match baseline config)

## Run: Retrieval-Only E2E

```python
import sys, os, uuid, json, time, logging
sys.path.insert(0, 'backend')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

from app.core.config.settings import settings
from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import Session, sessionmaker

sync_cloud_url = settings.database_url.replace(
    'postgresql+asyncpg://', 'postgresql+psycopg://'
).replace('?ssl=require', '?sslmode=require')
cloud_engine = create_engine(sync_cloud_url, echo=False, pool_size=5,
    max_overflow=5, pool_pre_ping=True, pool_recycle=300)
cloud_session_factory = sessionmaker(cloud_engine, class_=Session, expire_on_commit=False)

import app.core.db.session as session_mod
session_mod.sync_session_factory = cloud_session_factory
session_mod.sync_engine = cloud_engine

import ai_engine.extraction.pgvector_search_service as pgv_mod
pgv_mod._sync_engine = cloud_engine

import app.domains.credit.modules.ai.models
import app.domains.credit.modules.ai as _ai_pkg
_ai_pkg._assembled = True

with cloud_session_factory() as db, db.begin():
    db.execute(text("SET LOCAL app.current_organization_id = '70f19993-b0d9-42ff-b3c7-cf2bb0728cec'"))

    from app.domains.credit.modules.deals.models import PipelineDeal as Deal
    deal = db.execute(select(Deal).where(
        Deal.id == uuid.UUID('66b1ed07-8274-4d96-806f-1515bb0e148b'),
        Deal.fund_id == uuid.UUID('a1b2c3d4-e5f6-7890-abcd-ef1234567890'),
    )).scalar_one()

    from vertical_engines.credit.deep_review.corpus import _gather_deal_texts
    from vertical_engines.credit.deep_review.prompts import _pre_classify_from_corpus

    start = time.time()
    context = _gather_deal_texts(db,
        fund_id=uuid.UUID('a1b2c3d4-e5f6-7890-abcd-ef1234567890'),
        deal=deal,
        organization_id=uuid.UUID('70f19993-b0d9-42ff-b3c7-cf2bb0728cec'),
    )
    elapsed = time.time() - start

    corpus = context['corpus_text']
    ce = context.get('chapter_evidence', {})

    print(f"Retrieval: {elapsed:.1f}s | Corpus: {len(corpus)} chars")
    print(f"{'Chapter':<25} {'Chunks':>7} {'Docs':>5} {'Coverage':<22} {'Confidence':<12} {'top1':>8} {'delta':>8}")
    for k, v in sorted(ce.items()):
        sig = v.get('retrieval_signal', {})
        st = v.get('stats', {})
        print(f"{k:<25} {st.get('chunk_count','?'):>7} {st.get('unique_docs','?'):>5} "
              f"{v.get('coverage_status','?'):<22} {sig.get('confidence','N/A'):<12} "
              f"{sig.get('top1_score',0):>8.4f} {sig.get('delta_top1_top2',0):>8.4f}")

    db.rollback()
```

## Expected Results

| Metric | CPU Run (AMD) | GPU Run (NVIDIA) | Expected |
|---|---|---|---|
| Retrieval time | 691s | **~30-60s** | 10-20x speedup |
| CrossEncoder device | cpu | **cuda** | Check logs |
| Signal distribution | 2H + 3M + 9A | **2H + 3M + 9A** | Identical |
| Coverage distribution | 5 SAT + 9 CONT | **5 SAT + 9 CONT** | Identical |
| Corpus chars | 100,289 | **~100,289** | Same (±10) |

## After Validation

Update `docs/reference/deep-review-post-optimization-metrics-2026-03-20.md` with:
- GPU timing
- Confirmation that signals match CPU run
- Updated "Known Limitations" section (remove "Reranker on CPU is slow")

## Optional: Full Pipeline Run

If retrieval validates, run the full pipeline (all 14 stages) to complete the E2E:

```python
from vertical_engines.credit.deep_review.service import run_deal_deep_review_v4

result = run_deal_deep_review_v4(db,
    fund_id=uuid.UUID('a1b2c3d4-e5f6-7890-abcd-ef1234567890'),
    deal_id=uuid.UUID('66b1ed07-8274-4d96-806f-1515bb0e148b'),
    organization_id=uuid.UUID('70f19993-b0d9-42ff-b3c7-cf2bb0728cec'),
    actor_id='e2e-comparison',
    force=True,
    full_mode=False,
)
```

This requires LM Studio with qwen3-14b loaded (32K context, thinking disabled).
Capture memo metrics (chapters_generated, memo_chars, citations, recommendation, confidence_score, underwriting_score, instrument_type) and compare against baseline.
