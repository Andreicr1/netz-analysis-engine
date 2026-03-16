---
module: FredService
date: 2026-03-15
problem_type: runtime_error
component: service_object
symptoms:
  - "TokenBucketRateLimiter token count drifts under concurrent ThreadPoolExecutor usage"
  - "FRED API rate limit exceeded (429 responses) despite rate limiter configured at 2 req/s"
  - "Inconsistent _last_refill timestamps when multiple threads call acquire()"
root_cause: thread_violation
resolution_type: code_fix
severity: high
tags: [thread-safety, race-condition, rate-limiter, token-bucket, threading-lock, concurrent-futures]
---

# Troubleshooting: Thread-Unsafe TokenBucketRateLimiter in FredService

## Problem

The `TokenBucketRateLimiter` in `fred_service.py` had no synchronization on its `acquire()` method. When shared across threads (EDGAR parallel entity processing with `ThreadPoolExecutor(max_workers=3)`, dashboard FRED multi-fetch with `max_workers=4`), race conditions caused token underflow, refill state corruption, and rate limit violations.

## Environment

- Module: `quant_engine/fred_service.py`
- Python: 3.12+, `concurrent.futures.ThreadPoolExecutor`
- Affected Component: FredService rate limiter (shared across EDGAR + dashboard threads)
- Date: 2026-03-15
- PR: #4 (Credit Engine Quant Architecture Parity)
- Commit: `a443c29`

## Symptoms

- Token count drifts under concurrent usage — two threads consume one token but counter only decrements once
- `_last_refill` timestamp corrupted by interleaved reads/writes from multiple threads
- When `_tokens < 1.0`, multiple threads enter the sleep+reset branch simultaneously, allowing bursts that violate FRED's 120 req/60s limit
- Potential 429 responses from FRED API under parallel load

## What Didn't Work

**Direct solution:** Identified by security sentinel review agent during PR #4 code review. The race condition was latent — would only manifest under concurrent load (EDGAR multi-entity or dashboard multi-series fetches).

## Solution

**Code changes:**

```python
# Before (broken) — fred_service.py:37-69
@dataclass
class TokenBucketRateLimiter:
    max_tokens: float = 10.0
    refill_rate: float = 2.0
    _tokens: float = field(init=False, repr=False)
    _last_refill: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._tokens = self.max_tokens
        self._last_refill = time.monotonic()

    def acquire(self) -> None:
        """Block until a token is available."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.max_tokens, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now
        if self._tokens < 1.0:
            wait = (1.0 - self._tokens) / self.refill_rate
            time.sleep(wait)
            self._tokens = 0.0
            self._last_refill = time.monotonic()
        else:
            self._tokens -= 1.0

# After (fixed) — fred_service.py:37-70
import threading

@dataclass
class TokenBucketRateLimiter:
    max_tokens: float = 10.0
    refill_rate: float = 2.0
    _tokens: float = field(init=False, repr=False)
    _last_refill: float = field(init=False, repr=False)
    _lock: threading.Lock = field(init=False, repr=False, default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self._tokens = self.max_tokens
        self._last_refill = time.monotonic()

    def acquire(self) -> None:
        """Block until a token is available. Thread-safe via threading.Lock."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.max_tokens, self._tokens + elapsed * self.refill_rate)
            self._last_refill = now
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self.refill_rate
                time.sleep(wait)
                self._tokens = 0.0
                self._last_refill = time.monotonic()
            else:
                self._tokens -= 1.0
```

## Why This Works

1. **Root cause:** `acquire()` performs a read-modify-write on `_tokens` and `_last_refill` — a classic TOCTOU race. Without a lock, Thread A and Thread B can read the same `_tokens` value, both decrement, but only one decrement survives.
2. **Three race conditions fixed:**
   - **Token underflow:** Two threads read `_tokens=5.0`, both decrement to 4.0 — should be 3.0
   - **Refill corruption:** Threads overwrite each other's `_last_refill`, making future elapsed calculations wrong
   - **Sleep desync:** Both threads enter `_tokens < 1.0` branch, both sleep, both reset to 0 — burst exceeds rate limit
3. **`threading.Lock`** wraps the entire critical section. `time.sleep()` inside the lock is acceptable — it's bounded by rate limit duration (~0.5s max) and prevents the sleep+reset race.
4. **`default_factory=threading.Lock`** creates one lock per `TokenBucketRateLimiter` instance — lazy initialization via dataclass.

**Multi-threaded consumers:**
- `vertical_engines/credit/edgar/service.py` — `ThreadPoolExecutor(max_workers=3)` for parallel EDGAR entity fetching
- `app/domains/credit/dashboard/routes.py` — `ThreadPoolExecutor(max_workers=4)` for parallel FRED multi-series fetch
- When `FredService` is instantiated once and injected, all threads share the same rate limiter instance

## Prevention

- **CLAUDE.md rule applies:** "No module-level asyncio primitives" — but also applies to thread-safety: any shared mutable state accessed from `ThreadPoolExecutor` threads must be locked.
- **Pattern:** When writing a stateful service class used in `ThreadPoolExecutor`, add `threading.Lock` from day one. Don't wait for production race conditions.
- **Review checklist item:** If a class has mutable fields (`_tokens`, `_last_refill`) AND is used across threads, it MUST have a lock.
- **Test gap:** Current test (`test_phase_a_integration.py:85-94`) tests single-thread burst only. A concurrent stress test would be more robust.

## Related Issues

- See also: [FRED API Key Case Mismatch](fred-api-key-case-mismatch-MarketDataEngine-20260315.md) — fixed in same PR, same service
- See also: [Monolith to Modular Package](../architecture-patterns/monolith-to-modular-package-with-library-migration.md) — Redis distributed rate limiter (separate, complementary mechanism for cross-process rate limiting)
