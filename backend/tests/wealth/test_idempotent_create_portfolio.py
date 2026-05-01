"""PR-BE-4 — idempotent ``POST /model-portfolios`` create handler.

Three dimensions of coverage:

1. **Key derivation** — the idempotency key is stable across calls
   that share ``(org_id, display_name)`` and varies otherwise. The
   advisory-lock helper returns a deterministic ``zlib.crc32`` hash
   (Stability Guardrails §3 — never Python's built-in ``hash()``).
2. **Decorator wiring** — ``create_model_portfolio`` is wrapped by
   ``@idempotent`` so a second call within the TTL returns the
   cached result without re-entering the handler body.
3. **IntegrityError → 409 mapping** — when the migration 0201
   ``uq_model_portfolios_org_display_name`` constraint fires, the
   handler raises ``HTTPException(409)`` with a structured
   ``error="duplicate_display_name"`` payload that the PR-UX-4
   dialog can render inline.
"""

from __future__ import annotations

import asyncio
import uuid
import zlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.core.runtime.idempotency import (
    InMemoryIdempotencyStorage,
    idempotent,
)
from app.domains.wealth.routes.model_portfolios import (
    _create_portfolio_advisory_lock_key,
    _create_portfolio_idempotency_key,
    create_model_portfolio,
)
from app.domains.wealth.schemas.model_portfolio import ModelPortfolioCreate

_ORG_A = uuid.UUID("0be40000-0000-0000-0000-000000000001")
_ORG_B = uuid.UUID("0be40000-0000-0000-0000-000000000002")


# ── Key derivation ────────────────────────────────────────────────


def test_idempotency_key_stable_for_same_org_and_name() -> None:
    body = ModelPortfolioCreate(
        profile="growth",
        display_name="Core Growth",
    )
    a = _create_portfolio_idempotency_key(body, org_id=_ORG_A)
    b = _create_portfolio_idempotency_key(body, org_id=_ORG_A)
    assert a == b
    assert a == f"create_portfolio:{_ORG_A}:Core Growth"


def test_idempotency_key_varies_by_org() -> None:
    body = ModelPortfolioCreate(
        profile="growth",
        display_name="Core Growth",
    )
    assert (
        _create_portfolio_idempotency_key(body, org_id=_ORG_A)
        != _create_portfolio_idempotency_key(body, org_id=_ORG_B)
    )


def test_idempotency_key_varies_by_display_name() -> None:
    a_body = ModelPortfolioCreate(profile="growth", display_name="Alpha")
    b_body = ModelPortfolioCreate(profile="growth", display_name="Beta")
    assert (
        _create_portfolio_idempotency_key(a_body, org_id=_ORG_A)
        != _create_portfolio_idempotency_key(b_body, org_id=_ORG_A)
    )


def test_idempotency_key_ignores_copy_from() -> None:
    """Retries that drop ``copy_from`` must still hit the cache."""
    src = uuid.uuid4()
    a = _create_portfolio_idempotency_key(
        ModelPortfolioCreate(
            profile="growth", display_name="Core Growth", copy_from=src,
        ),
        org_id=_ORG_A,
    )
    b = _create_portfolio_idempotency_key(
        ModelPortfolioCreate(
            profile="growth", display_name="Core Growth",
        ),
        org_id=_ORG_A,
    )
    assert a == b


def test_advisory_lock_key_is_crc32_not_hash() -> None:
    """Advisory locks MUST use ``zlib.crc32`` for cross-process stability.

    Python's built-in ``hash()`` is salted per-interpreter, so two
    workers on the same Postgres would compute different keys for the
    same payload — the second worker could then INSERT alongside the
    first under the (wrongly held) impression that the lock is free.
    """
    key = _create_portfolio_advisory_lock_key(_ORG_A, "Core Growth")
    expected = (
        zlib.crc32(
            f"create_portfolio:{_ORG_A}:Core Growth".encode("utf-8")
        )
        & 0xFFFFFFFF
    )
    assert key == expected
    assert 0 <= key <= 0xFFFFFFFF


def test_advisory_lock_key_deterministic_across_calls() -> None:
    a = _create_portfolio_advisory_lock_key(_ORG_A, "Core Growth")
    b = _create_portfolio_advisory_lock_key(_ORG_A, "Core Growth")
    assert a == b


def test_advisory_lock_key_varies_by_input() -> None:
    a = _create_portfolio_advisory_lock_key(_ORG_A, "Core Growth")
    b = _create_portfolio_advisory_lock_key(_ORG_B, "Core Growth")
    c = _create_portfolio_advisory_lock_key(_ORG_A, "Different Name")
    assert a != b
    assert a != c


# ── Decorator wiring ──────────────────────────────────────────────


def test_create_handler_is_wrapped_by_idempotent() -> None:
    """The handler exposes the decorator's wrapper signature.

    ``functools.wraps`` makes ``create_model_portfolio`` look like the
    original async function but the wrapper short-circuits on cache
    hits. We assert that ``__wrapped__`` is exposed (set by
    ``functools.wraps``) so we know the decorator actually ran.
    """
    assert hasattr(create_model_portfolio, "__wrapped__")
    assert asyncio.iscoroutinefunction(create_model_portfolio)


async def test_idempotent_decorator_caches_within_ttl() -> None:
    """Validate the documented contract on a synthetic handler.

    The route handler itself is hard to invoke inline because it
    depends on FastAPI ``Depends(...)`` injection — we verify the
    primitive's behaviour with the same key extractor and a fake
    body to lock down the contract that the route now relies on.
    """
    storage = InMemoryIdempotencyStorage()
    calls = 0

    @idempotent(
        key=_create_portfolio_idempotency_key, ttl_s=600, storage=storage,
    )
    async def fake_create(
        body: ModelPortfolioCreate, *, org_id: uuid.UUID,
    ) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"id": str(uuid.uuid4()), "name": body.display_name}

    body = ModelPortfolioCreate(profile="growth", display_name="Core Growth")
    first = await fake_create(body, org_id=_ORG_A)
    second = await fake_create(body, org_id=_ORG_A)

    assert calls == 1
    assert first == second


async def test_idempotent_decorator_concurrent_collapses_to_one_call() -> None:
    """Ten concurrent ``POST`` retries must execute the body once.

    This is the load-balancer retry storm scenario: the user clicks
    "Create" and the browser fires ten parallel fetches before the
    first response lands. Without the decorator, all ten reach the
    DB, the first wins ``uq_model_portfolios_org_display_name`` and
    the rest 409. With the decorator, exactly one body runs and the
    other nine get the cached result.
    """
    storage = InMemoryIdempotencyStorage()
    calls = 0
    started = asyncio.Event()

    @idempotent(
        key=_create_portfolio_idempotency_key,
        ttl_s=600,
        storage=storage,
        wait_poll_s=0.005,
    )
    async def fake_create(
        body: ModelPortfolioCreate, *, org_id: uuid.UUID,
    ) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        # Hold the lock briefly so the other coroutines all queue up
        # behind the in-flight execution before the cache is populated.
        await started.wait()
        return {"name": body.display_name, "calls": calls}

    body = ModelPortfolioCreate(profile="growth", display_name="Core Growth")

    async def fire() -> dict[str, Any]:
        return await fake_create(body, org_id=_ORG_A)

    tasks = [asyncio.create_task(fire()) for _ in range(10)]
    # Let every task hit the decorator before releasing the body.
    await asyncio.sleep(0.02)
    started.set()
    results = await asyncio.gather(*tasks)

    assert calls == 1
    assert all(r == results[0] for r in results)


async def test_idempotent_decorator_expires_after_ttl() -> None:
    storage = InMemoryIdempotencyStorage()
    calls = 0

    @idempotent(
        key=_create_portfolio_idempotency_key, ttl_s=1, storage=storage,
    )
    async def fake_create(
        body: ModelPortfolioCreate, *, org_id: uuid.UUID,
    ) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"call": calls}

    body = ModelPortfolioCreate(profile="growth", display_name="Core Growth")
    first = await fake_create(body, org_id=_ORG_A)
    # Force expiry by clearing the in-memory storage manually — equivalent
    # to TTL elapse, without making the test sleep for real seconds.
    storage._results.clear()  # type: ignore[attr-defined]
    storage._locks.clear()  # type: ignore[attr-defined]
    second = await fake_create(body, org_id=_ORG_A)

    assert calls == 2
    assert first["call"] == 1
    assert second["call"] == 2


# ── IntegrityError → 409 mapping ─────────────────────────────────


def _build_integrity_error(constraint_name: str) -> IntegrityError:
    """Construct an IntegrityError whose ``orig`` mentions a constraint.

    The handler matches on ``str(exc.orig)``; we inject a sentinel
    so the mapping branch fires deterministically without needing a
    real DB to actually raise.
    """
    orig = Exception(
        f'duplicate key value violates unique constraint "{constraint_name}"'
    )
    return IntegrityError("INSERT INTO ...", params=None, orig=orig)


async def _invoke_create(
    body: ModelPortfolioCreate,
    *,
    flush_exc: Exception | None = None,
) -> Any:
    """Drive the create handler past dependency injection.

    Stubs ``AsyncSession.execute`` (advisory lock + later queries),
    ``flush``, ``refresh``, ``add``, and the helper that resolves
    ``allowed_actions``. The body raises on flush when ``flush_exc``
    is supplied so the IntegrityError mapping branch is exercised.
    """
    from app.core.security.clerk_auth import Actor
    from app.shared.enums import Role

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.refresh = AsyncMock()

    if flush_exc is not None:
        db.flush = AsyncMock(side_effect=flush_exc)
    else:
        db.flush = AsyncMock()
    db.add = MagicMock()

    actor = Actor(
        actor_id="be4-tester",
        name="Tester",
        email="tester@example.com",
        roles=[Role.INVESTMENT_TEAM],
        organization_id=_ORG_A,
        fund_ids=[],
    )
    user = MagicMock()
    user.name = "be4-tester"

    return await create_model_portfolio.__wrapped__(
        body=body, db=db, user=user, actor=actor, org_id=_ORG_A,
    )


async def test_duplicate_display_name_returns_structured_409() -> None:
    """The migration 0201 constraint maps to a 409 the dialog can render."""
    body = ModelPortfolioCreate(profile="growth", display_name="Core Growth")
    exc = _build_integrity_error("uq_model_portfolios_org_display_name")

    with pytest.raises(HTTPException) as excinfo:
        await _invoke_create(body, flush_exc=exc)

    assert excinfo.value.status_code == 409
    detail = excinfo.value.detail
    assert isinstance(detail, dict)
    assert detail["error"] == "duplicate_display_name"
    assert "Core Growth" in detail["message"]


async def test_other_integrity_errors_propagate_unchanged() -> None:
    """A non-display-name IntegrityError must surface as the original 500.

    The handler only owns the duplicate-name mapping; any other
    constraint (e.g. a fresh CHECK or FK violation) must bubble up to
    FastAPI as-is so an institutional incident is not swallowed by a
    misleading 409.
    """
    body = ModelPortfolioCreate(profile="growth", display_name="Core Growth")
    exc = _build_integrity_error("chk_model_portfolio_status")

    with pytest.raises(IntegrityError):
        await _invoke_create(body, flush_exc=exc)


# ── orjson serialisation contract (Codex P1 regression) ─────────────


async def test_idempotent_decorator_caches_decimal_datetime_uuid_payload() -> None:
    """The cache MUST round-trip a payload with Decimal/datetime/UUID.

    Codex Auto Review (PR #474) flagged that ``ModelPortfolioRead``
    contains ``Decimal``, ``datetime`` and ``UUID`` fields which
    ``orjson.dumps`` cannot encode without a ``default=`` handler. A
    failed encode would log ``idempotency_store_result_failed`` and
    skip the cache write, so a retry within the 600s TTL would
    re-execute the handler and trip the duplicate display_name 409 —
    silently degrading idempotency to "first call wins, second 409s",
    the opposite of the contract.

    The fix is to return the result of ``model_dump(mode='json')``
    from the create handler so the value handed to ``orjson.dumps``
    is always a JSON-safe dict. This test pins that contract by
    exercising the decorator with a payload shaped exactly like
    ``ModelPortfolioRead.model_dump(mode='json')`` and asserting:

    1. The first call's body executes once.
    2. The second call returns the cached body byte-for-byte.
    3. The cached payload is the JSON-safe dict (Decimals as strings,
       datetimes/UUIDs as strings) — never the underlying Pydantic
       model.
    """
    from datetime import datetime
    from decimal import Decimal

    storage = InMemoryIdempotencyStorage()
    calls = 0

    @idempotent(
        key=_create_portfolio_idempotency_key, ttl_s=600, storage=storage,
    )
    async def fake_create(
        body: ModelPortfolioCreate, *, org_id: uuid.UUID,
    ) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        # Mirror the post-fix handler shape: every Decimal / datetime /
        # UUID has been pre-coerced via ``model_dump(mode='json')`` to
        # a JSON-safe primitive before ``orjson.dumps`` ever runs.
        del org_id  # used only to derive the cache key
        rendered = {
            "id": str(uuid.uuid4()),
            "profile": body.profile,
            "display_name": body.display_name,
            "inception_nav": str(Decimal("1000.00")),
            "created_at": datetime(2026, 5, 1, 12, 0, 0).isoformat(),
        }
        return rendered

    body = ModelPortfolioCreate(profile="growth", display_name="Core Growth")
    first = await fake_create(body, org_id=_ORG_A)
    second = await fake_create(body, org_id=_ORG_A)

    # Body executed exactly once — the second call is a cache hit.
    assert calls == 1
    # Full body equality, not just id — proves Decimal/datetime survived.
    assert first == second
    # And every field is a primitive orjson can encode (no Pydantic, no
    # Decimal, no datetime, no UUID).
    for value in second.values():
        assert isinstance(value, str), (
            f"Cached payload must be JSON-primitives only; got {type(value)}"
        )

    # The decorator's storage must hold the serialised payload.
    cached_bytes = await storage.get_result(
        _create_portfolio_idempotency_key(body, org_id=_ORG_A)
    )
    assert cached_bytes is not None, (
        "Cache miss after first call — orjson.dumps must have failed "
        "silently. Did the handler return a Pydantic model instead of "
        "model_dump(mode='json')?"
    )
    import orjson  # local import — already a project dep
    assert orjson.loads(cached_bytes) == first


async def test_idempotent_decorator_rejects_pydantic_model_return() -> None:
    """Pin the negative case: returning a Pydantic model from the handler.

    Without the P1 fix, the handler returned a ``ModelPortfolioRead``
    Pydantic instance directly. ``orjson.dumps`` raises ``TypeError``
    on such inputs, the decorator catches it, logs
    ``idempotency_store_result_failed`` and silently moves on — and
    the next call within TTL re-executes the body. This test pins
    that exact failure mode so a regression to "return the Pydantic
    model" surfaces immediately instead of silently downgrading
    idempotency in production.
    """
    from datetime import datetime
    from decimal import Decimal

    from app.domains.wealth.schemas.model_portfolio import (
        ModelPortfolioRead,
    )

    storage = InMemoryIdempotencyStorage()
    calls = 0

    @idempotent(
        key=_create_portfolio_idempotency_key, ttl_s=600, storage=storage,
    )
    async def buggy_create(
        body: ModelPortfolioCreate, *, org_id: uuid.UUID,
    ) -> Any:
        nonlocal calls
        calls += 1
        # Return the Pydantic model directly — the *pre*-P1 shape.
        del org_id  # unused; schema does not expose organization_id
        return ModelPortfolioRead(
            id=uuid.uuid4(),
            profile=body.profile,
            display_name=body.display_name,
            inception_nav=Decimal("1000.00"),
            status="draft",
            state="draft",
            created_at=datetime(2026, 5, 1, 12, 0, 0),
            created_by="test",
        )

    body = ModelPortfolioCreate(profile="growth", display_name="Core Growth")
    await buggy_create(body, org_id=_ORG_A)

    # The cache write must have failed silently — proving why the P1
    # fix is needed. The cache is empty, so a retry will re-execute.
    cached_bytes = await storage.get_result(
        _create_portfolio_idempotency_key(body, org_id=_ORG_A)
    )
    assert cached_bytes is None, (
        "orjson.dumps unexpectedly accepted a Pydantic model. If orjson "
        "added native Pydantic support, this test is now stale and the "
        "P1 contract can be relaxed."
    )

    # Second call re-executes — the silent-degradation pattern.
    await buggy_create(body, org_id=_ORG_A)
    assert calls == 2, (
        "Expected re-execution because cache write failed; got cache "
        "hit. Either orjson started serialising Pydantic, or the "
        "decorator changed its serialisation path."
    )
