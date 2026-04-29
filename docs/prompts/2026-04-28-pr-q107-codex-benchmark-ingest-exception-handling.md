# PR-Q107 — Codex Auto Review hotfix — benchmark_ingest fail-hard on non-gate exceptions (P1)

**Status:** READY FOR DISPATCH (fresh Opus 4.7 1M session)
**Origin:** Codex Auto Review on PR-Q102 (Wave 6 S09 C-10) — 1 P1 catch
**Target file:** `backend/app/domains/wealth/workers/benchmark_ingest.py`
**Severity:** P1 (worker aborts on unexpected runtime errors that pre-Q102 would have been swallowed by retry loop)

---

## STAGE — Q107 Hotfix

You are implementing PR-Q107, a narrow hotfix for a Codex Auto Review P1 catch on PR-Q102's C-10 fix (benchmark_ingest ExternalProviderGate, Wave 6 Session 09, already shipped to main as commit `ff9e9ad2`).

The Q102 fix replaced the manual retry loop with `ExternalProviderGate.call()` and a single `except ProviderGateError as e:` clause. ExternalProviderGate only wraps timeout and circuit-breaker errors as `ProviderGateError`; any other exception thrown by `_fetch_via_tiingo` (KeyError, JSONDecodeError, network errors not caught by the gate, malformed Tiingo response, etc.) propagates unwrapped and aborts the worker.

Pre-Q102 behavior: `except Exception as e: ... return {... skipped_tickers ...}` — fail-soft.
Post-Q102 behavior: only `except ProviderGateError` — fail-hard on any non-gate exception.

This breaks the intended fail-soft contract for external-provider instability.

## CATCH (verbatim)

> `_do_ingest` now only degrades on `ProviderGateError`, but `ExternalProviderGate.call()` re-raises non-timeout exceptions from `_fetch_via_tiingo` unchanged. If Tiingo returns malformed payloads or any unexpected runtime error bubbles out of `fetch_batch_history`, this path now raises and aborts the worker instead of returning `skipped_tickers` as before, which breaks the intended fail-soft behavior for external-provider instability.

## VERIFIED

`backend/app/domains/wealth/workers/benchmark_ingest.py` (line ~140-148 after Q102):

```python
try:
    async def _tiingo_coro() -> dict[str, pd.DataFrame] | None:
        return await loop.run_in_executor(
            _io_executor, _fetch_via_tiingo, unique_tickers, period,
        )

    hist = await _tiingo_gate.call(
        op_key=f"benchmark:{','.join(sorted(unique_tickers))}",
        coro_factory=_tiingo_coro,
    )
except ProviderGateError as e:
    logger.error("Tiingo batch download failed via gate", error=str(e))
    return {"blocks_updated": 0, "rows_upserted": 0, "stale_blocks": [], "skipped_tickers": unique_tickers}
```

`ExternalProviderGate.call` (per `backend/app/core/runtime/provider_gate.py`) wraps timeouts and circuit-open errors as `ProviderGateError` but does NOT wrap general exceptions raised by the coro. Those propagate.

## REQUIRED FIX

Add a second `except Exception as e:` branch BELOW the `except ProviderGateError as e:` (Python try/except matches in declaration order — gate-specific must come first). The fallback branch logs at `error` level and returns the same fail-soft payload:

```python
try:
    async def _tiingo_coro() -> dict[str, pd.DataFrame] | None:
        return await loop.run_in_executor(
            _io_executor, _fetch_via_tiingo, unique_tickers, period,
        )

    hist = await _tiingo_gate.call(
        op_key=f"benchmark:{','.join(sorted(unique_tickers))}",
        coro_factory=_tiingo_coro,
    )
except ProviderGateError as e:
    logger.error(
        "Tiingo batch download failed via gate (timeout / circuit open)",
        error=str(e),
    )
    return {"blocks_updated": 0, "rows_upserted": 0, "stale_blocks": [], "skipped_tickers": unique_tickers}
except Exception as e:  # Q107: fail-soft on non-gate exceptions (parse / runtime)
    logger.error(
        "Tiingo batch download raised unexpected error",
        error=str(e),
        error_type=type(e).__name__,
    )
    return {"blocks_updated": 0, "rows_upserted": 0, "stale_blocks": [], "skipped_tickers": unique_tickers}
```

The `error_type` log field is added to the catch-all branch to aid post-hoc diagnosis (which exception type bubbled). The `ProviderGateError` branch is untouched.

## CONSTRAINTS

- Do NOT remove `ExternalProviderGate.call` or the gate config; only add the second except branch.
- Do NOT change the return shape; both branches return identical payloads.
- Place the new except AFTER the gate-specific one; Python except ordering matters.
- Do NOT broaden the existing per-ticker `try/except (KeyError, TypeError)` blocks (line ~252) — they are already specific by design and out of scope.
- Lint clean: `.venv/Scripts/python.exe -m ruff check backend/app/domains/wealth/workers/benchmark_ingest.py backend/tests/wealth/workers/test_benchmark_ingest.py` (if test file exists; otherwise just the worker file).

## REQUIRED TEST

Add or extend `backend/tests/wealth/workers/test_benchmark_ingest_fail_soft.py` (create file if absent):

```python
"""Q107 — benchmark_ingest fail-soft on non-ProviderGateError exceptions."""

from unittest.mock import patch, AsyncMock
import pytest

from app.domains.wealth.workers import benchmark_ingest as mod


@pytest.mark.asyncio
async def test_do_ingest_returns_skipped_on_keyerror():
    """Non-gate exception inside _fetch_via_tiingo must produce skipped_tickers,
    not raise. Pre-Q107 only ProviderGateError was caught — KeyError aborted."""
    with patch.object(mod, "_fetch_via_tiingo", side_effect=KeyError("malformed payload")):
        async with mod.async_session() as db:
            result = await mod._do_ingest(db, lookback_days=30)
    assert "skipped_tickers" in result
    assert result["blocks_updated"] == 0
    assert result["rows_upserted"] == 0


@pytest.mark.asyncio
async def test_do_ingest_returns_skipped_on_provider_gate_error():
    """Q102 invariant preserved — ProviderGateError still produces skipped_tickers."""
    from app.core.runtime.provider_gate import ProviderGateError

    with patch.object(
        mod._tiingo_gate,
        "call",
        side_effect=ProviderGateError("circuit open"),
    ):
        async with mod.async_session() as db:
            result = await mod._do_ingest(db, lookback_days=30)
    assert "skipped_tickers" in result
    assert result["blocks_updated"] == 0
```

The KeyError mock is a synthetic stand-in for the malformed-payload class of bug Codex flagged. Pre-Q107 it would raise; post-Q107 it must produce a degraded result.

## ACCEPTANCE

- New `except Exception as e:` branch added with logger.error + skipped_tickers return
- 2 new tests pass (or 1 if you can't easily mock ProviderGateError; the KeyError test is the primary invariant)
- All existing benchmark_ingest tests still pass
- Lint clean
- Manual smoke (optional): patch `_fetch_via_tiingo` to raise locally, run `python -m app.domains.wealth.workers.benchmark_ingest`, observe degraded log + non-raising exit

## PR DESCRIPTION

Title: `fix(wealth): PR-Q107 — Codex P1 — benchmark_ingest fail-hard on non-gate exceptions`

Body sketch:

```markdown
## Codex Auto Review on PR-Q102 commit `ff9e9ad2` — 1 P1 catch

Q102 replaced the manual retry loop with `ExternalProviderGate.call()`.
The new `except ProviderGateError` only catches gate-wrapped errors
(timeouts + circuit-open). Non-gate exceptions raised by
`_fetch_via_tiingo` (malformed Tiingo response, parse errors, etc.) now
propagate and abort the worker — pre-Q102 behavior was fail-soft via
`except Exception` in the retry loop.

## Fix

Add `except Exception` branch after `except ProviderGateError`. Same
fail-soft payload (`skipped_tickers=unique_tickers`). New `error_type`
log field for diagnosis.

## Test plan

- [x] New tests: KeyError + ProviderGateError both produce skipped_tickers
- [x] Existing tests still pass
- [x] make lint clean
```

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.

## DISPATCH NOTES (for Andrei)

Branch: `fix/pr-q107-benchmark-ingest-fail-soft`
After agent push, return to me — I open the PR.
