# Fix: CrossEncoder Meta Tensor Error (Thread-Safety Race Condition)

> Execute in a fresh session on branch `refactor/deep-review-legacy-blob-removal`.

---

## Problem

`_get_cross_encoder()` in `backend/ai_engine/extraction/local_reranker.py` has a race condition. When `evidence.py` calls `search_and_rerank_deal_sync()` from multiple `ThreadPoolExecutor` threads simultaneously, two threads can enter `_get_cross_encoder()` at the same time and both try to instantiate `CrossEncoder(_MODEL_NAME)`. PyTorch's model initialization is not thread-safe — the second thread gets a model in "meta" state (placeholder tensors without data), causing:

```
NotImplementedError: Cannot copy out of meta tensor; no data!
Please use torch.nn.Module.to_empty() instead of torch.nn.Module.to()
when moving module from meta
```

This sets `_load_failed = True`, and **all subsequent calls** in the process fall back to cosine scores (graceful degradation). The reranker is permanently disabled for the rest of the process lifetime.

The model loads fine in single-threaded tests. The error only manifests under concurrent thread access.

## File

`backend/ai_engine/extraction/local_reranker.py`

## Fix

Add a `threading.Lock` to protect the lazy singleton initialization:

```python
import threading

_cross_encoder = None
_load_failed = False
_load_lock = threading.Lock()


def _get_cross_encoder():
    global _cross_encoder, _load_failed

    if _load_failed:
        return None
    if _cross_encoder is not None:
        return _cross_encoder

    with _load_lock:
        # Double-check after acquiring lock
        if _load_failed:
            return None
        if _cross_encoder is not None:
            return _cross_encoder

        try:
            from sentence_transformers import CrossEncoder

            t0 = time.time()
            _cross_encoder = CrossEncoder(_MODEL_NAME)
            logger.info(
                "CrossEncoder loaded: model=%s, time=%.1fs",
                _MODEL_NAME,
                time.time() - t0,
            )
            return _cross_encoder
        except ImportError:
            logger.warning(
                "sentence-transformers not installed — reranker disabled, "
                "falling back to cosine similarity scores. "
                "Install with: pip install -e '.[reranker]'"
            )
            _load_failed = True
            return None
        except Exception:
            logger.exception("Failed to load CrossEncoder model %s", _MODEL_NAME)
            _load_failed = True
            return None
```

Key points:
- `threading.Lock` (not `asyncio.Lock`) — this runs in `ThreadPoolExecutor` threads, not async
- Double-checked locking pattern: fast path (no lock) when already loaded, lock only on first load
- `_load_lock` at module level is safe — `threading.Lock()` is GIL-atomic and has no event loop dependency (unlike `asyncio.Lock` which must not be at module level per CLAUDE.md rules)

## Acceptance Criteria

- `make check` passes
- CrossEncoder loads exactly once even under concurrent thread access
- No `meta tensor` errors in logs when `evidence.py` runs with `ThreadPoolExecutor(max_workers=6)`
- `reranker_score` values in retrieval results are logits (range ~[-11, +8]), not cosine (range [0, 1])

## Commit

```
fix(reranker): add threading.Lock to prevent concurrent CrossEncoder init

Race condition: multiple ThreadPoolExecutor threads calling _get_cross_encoder()
simultaneously caused PyTorch meta tensor error. Double-checked locking ensures
exactly one thread loads the model, others wait and reuse the singleton.
```
