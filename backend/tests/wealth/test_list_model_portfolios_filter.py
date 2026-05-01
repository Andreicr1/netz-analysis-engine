"""PR-BE-2 — GET /model-portfolios profile filter + bounded keyset list.

Covers six surfaces (Builder Workspace redesign §4.1 / §5.3 / §10
P1 Bounded). Each test calls the route handler ``list_model_portfolios``
directly with an ``AsyncSession`` stub so we exercise the param
validation, ordering, and cursor round-trip without standing up Postgres.

A live-DB smoke is intentionally out of scope here — the integration
suite covers that path via the existing ``model_portfolios`` fixtures.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.domains.wealth.models.model_portfolio import ModelPortfolio
from app.domains.wealth.routes.model_portfolios import (
    _LIST_PORTFOLIOS_MAX_LIMIT,
    _decode_portfolio_cursor,
    _encode_portfolio_cursor,
    list_model_portfolios,
)

_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _make_portfolio(
    *,
    profile: str,
    created_at: datetime,
    portfolio_id: uuid.UUID | None = None,
    display_name: str = "Test Portfolio",
) -> ModelPortfolio:
    """Construct an in-memory ModelPortfolio without touching the DB.

    ``ModelPortfolioRead.model_validate(portfolio)`` walks ORM
    attributes via ``from_attributes=True``; we set the minimum set the
    schema reads so serialization succeeds.
    """
    p = ModelPortfolio(
        organization_id=_ORG_ID,
        profile=profile,
        display_name=display_name,
        description=None,
        benchmark_composite=None,
        inception_date=None,
        backtest_start_date=None,
        status="draft",
        created_by="tester",
    )
    p.id = portfolio_id or uuid.uuid4()
    p.created_at = created_at
    p.state = "draft"
    p.state_metadata = {}
    p.state_changed_at = None
    p.state_changed_by = None
    p.fund_selection_schema = None
    p.backtest_result = None
    p.stress_result = None
    p.inception_nav = 100
    return p


def _make_db_returning(portfolios: list[ModelPortfolio]) -> AsyncMock:
    """Stub the AsyncSession.execute() call sequence the handler issues.

    Calls in order:
      1. ``execute(select_portfolios)`` → scalars().all() → list
      2. (per-portfolio) ``execute(select latest run validation)`` →
         ``one_or_none()`` → ``None`` (no construction runs)
      3. ``ConfigService.get(...)`` is patched separately to return a
         missing config so the default ``ApprovalPolicy`` is used.
    """
    db = AsyncMock()

    portfolios_result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = portfolios
    portfolios_result.scalars.return_value = scalars

    no_run_result = MagicMock()
    no_run_result.one_or_none.return_value = None

    call_count = {"n": 0}

    async def _execute(stmt: Any, params: dict | None = None) -> Any:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return portfolios_result
        return no_run_result

    db.execute = AsyncMock(side_effect=_execute)
    return db


def _make_user() -> Any:
    user = MagicMock()
    user.name = "tester"
    return user


@pytest.fixture(autouse=True)
def _stub_approval_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass ConfigService — the handler uses defaults on miss anyway."""
    async def _resolve(db: Any, org_id: Any) -> Any:  # noqa: ANN401
        from vertical_engines.wealth.model_portfolio.state_machine import (
            ApprovalPolicy,
        )
        return ApprovalPolicy()

    monkeypatch.setattr(
        "app.domains.wealth.routes.model_portfolios._resolve_approval_policy",
        _resolve,
    )


# ── 1. Profile filter — only matching rows returned ──────────────────


@pytest.mark.asyncio
async def test_profile_growth_filters_to_growth_only() -> None:
    """``?profile=growth`` only returns growth portfolios.

    The stub mimics SQL: WHERE clause filtering is done by passing
    only the matching rows from the fixture set.
    """
    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    growth = _make_portfolio(profile="growth", created_at=base)
    db = _make_db_returning([growth])

    resp = await list_model_portfolios(
        profile="growth",
        limit=100,
        cursor=None,
        db=db,
        user=_make_user(),
        org_id=_ORG_ID,
    )

    assert len(resp.items) == 1
    assert resp.items[0].profile == "growth"
    assert resp.next_cursor is None


# ── 2. Aggressive alias rewrite + deprecation log ────────────────────


@pytest.mark.asyncio
async def test_profile_aggressive_alias_resolves_to_growth(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``?profile=aggressive`` is rewritten to growth (sunset 2026-10-30).

    The legacy alias must emit ``legacy_profile_url_alias`` so the
    sunset dashboard can track residual usage. structlog writes
    through its own processor pipeline (not stdlib logging), so we
    assert against ``capsys`` rather than ``caplog``.
    """
    growth = _make_portfolio(
        profile="growth",
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    db = _make_db_returning([growth])

    resp = await list_model_portfolios(
        profile="aggressive",
        limit=100,
        cursor=None,
        db=db,
        user=_make_user(),
        org_id=_ORG_ID,
    )

    assert len(resp.items) == 1
    assert resp.items[0].profile == "growth"
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "legacy_profile_url_alias" in combined
    assert "received=aggressive" in combined or "received='aggressive'" in combined


# ── 3. Limit cap honoured ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_limit_50_caps_response_size() -> None:
    """The handler honours ``?limit=`` by issuing ``LIMIT n+1``.

    The stub returns exactly ``limit`` rows so ``has_next`` is False and
    ``next_cursor`` is None.
    """
    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    rows = [
        _make_portfolio(
            profile="moderate",
            created_at=base - timedelta(seconds=i),
            display_name=f"P{i}",
        )
        for i in range(50)
    ]
    db = _make_db_returning(rows)

    resp = await list_model_portfolios(
        profile=None,
        limit=50,
        cursor=None,
        db=db,
        user=_make_user(),
        org_id=_ORG_ID,
    )

    assert len(resp.items) == 50
    assert resp.next_cursor is None


# ── 4. Limit > 200 rejected with 422 ─────────────────────────────────


def test_limit_above_max_is_invalid() -> None:
    """``?limit=201`` is rejected by FastAPI's ``Query(le=...)``.

    We can't easily exercise the FastAPI request layer in a unit test,
    but the contract is encoded in ``_LIST_PORTFOLIOS_MAX_LIMIT`` —
    asserting it pins the public guarantee.
    """
    assert _LIST_PORTFOLIOS_MAX_LIMIT == 200


@pytest.mark.asyncio
async def test_limit_201_rejected_via_http(client: Any) -> None:
    """HTTP-level test — FastAPI returns 422 when ``limit`` exceeds the cap.

    Uses the conftest ``client`` fixture (httpx + ASGITransport) and the
    dev actor header so the route resolves auth without a real Clerk
    JWT. Doesn't need a real DB because validation runs before the
    handler body.
    """
    import json

    headers = {
        "X-DEV-ACTOR": json.dumps(
            {
                "actor_id": "test-user",
                "roles": ["ADMIN", "INVESTMENT_TEAM"],
                "fund_ids": [],
                "org_id": str(_ORG_ID),
            },
        ),
    }
    resp = await client.get(
        "/api/v1/model-portfolios",
        params={"limit": 201},
        headers=headers,
    )
    assert resp.status_code == 422
    body = resp.json()
    # FastAPI's standard 422 shape carries a list of error dicts under
    # ``detail`` — the entry pointing at the offending field tells the
    # client what to fix.
    assert any(
        "limit" in (e.get("loc") or []) for e in body.get("detail", [])
    )


# ── 5. Keyset pagination round-trip ──────────────────────────────────


@pytest.mark.asyncio
async def test_keyset_pagination_no_overlap_and_correct_order() -> None:
    """Page 1 (limit=2) → next_cursor → page 2 yields disjoint, ordered rows.

    Mimics the SQL: page 1 returns 3 rows (limit+1), the handler trims
    to 2 and emits a cursor pointing at the 2nd row's ``(created_at, id)``.
    Page 2's stub honours that cursor by returning only rows strictly
    after it.
    """
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    p1 = _make_portfolio(
        profile="moderate",
        created_at=base,
        display_name="P1",
    )
    p2 = _make_portfolio(
        profile="moderate",
        created_at=base - timedelta(seconds=1),
        display_name="P2",
    )
    p3 = _make_portfolio(
        profile="moderate",
        created_at=base - timedelta(seconds=2),
        display_name="P3",
    )
    p4 = _make_portfolio(
        profile="moderate",
        created_at=base - timedelta(seconds=3),
        display_name="P4",
    )

    # Page 1: stub returns p1, p2, p3 (limit+1=3) so handler trims to
    # [p1, p2] and emits a cursor on p2.
    db1 = _make_db_returning([p1, p2, p3])
    resp1 = await list_model_portfolios(
        profile=None,
        limit=2,
        cursor=None,
        db=db1,
        user=_make_user(),
        org_id=_ORG_ID,
    )
    assert [it.display_name for it in resp1.items] == ["P1", "P2"]
    assert resp1.next_cursor is not None

    # Round-trip: cursor must decode to p2's (created_at, id).
    decoded_at, decoded_id = _decode_portfolio_cursor(resp1.next_cursor)
    assert decoded_at == p2.created_at
    assert decoded_id == p2.id

    # Page 2: stub returns p3, p4 (no overflow) — final page.
    db2 = _make_db_returning([p3, p4])
    resp2 = await list_model_portfolios(
        profile=None,
        limit=2,
        cursor=resp1.next_cursor,
        db=db2,
        user=_make_user(),
        org_id=_ORG_ID,
    )
    assert [it.display_name for it in resp2.items] == ["P3", "P4"]
    assert resp2.next_cursor is None

    page1_ids = {it.id for it in resp1.items}
    page2_ids = {it.id for it in resp2.items}
    assert page1_ids.isdisjoint(page2_ids)


def test_cursor_round_trip_is_lossless() -> None:
    """Encoder/decoder pair is a left-inverse on ``(datetime, UUID)``."""
    when = datetime(2026, 4, 30, 10, 15, 30, 123456, tzinfo=timezone.utc)
    pid = uuid.uuid4()
    encoded = _encode_portfolio_cursor(when, pid)
    assert isinstance(encoded, str)
    assert _decode_portfolio_cursor(encoded) == (when, pid)


def test_decode_malformed_cursor_returns_400() -> None:
    """Malformed cursor → 400, never a 500."""
    with pytest.raises(HTTPException) as exc:
        _decode_portfolio_cursor("not-base64-at-all!@#")
    assert exc.value.status_code == 400


# ── 6. Default ordering when no params ───────────────────────────────


@pytest.mark.asyncio
async def test_default_order_is_created_at_desc() -> None:
    """With no params, items come back in ``created_at DESC`` order.

    The stub returns rows in the order it was constructed, so we
    verify the handler does not re-sort them client-side and the SQL
    ``ORDER BY`` is the only ordering authority.
    """
    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    newest = _make_portfolio(
        profile="moderate",
        created_at=base,
        display_name="newest",
    )
    middle = _make_portfolio(
        profile="moderate",
        created_at=base - timedelta(days=1),
        display_name="middle",
    )
    oldest = _make_portfolio(
        profile="moderate",
        created_at=base - timedelta(days=2),
        display_name="oldest",
    )
    db = _make_db_returning([newest, middle, oldest])

    resp = await list_model_portfolios(
        profile=None,
        limit=100,
        cursor=None,
        db=db,
        user=_make_user(),
        org_id=_ORG_ID,
    )

    assert [it.display_name for it in resp.items] == [
        "newest",
        "middle",
        "oldest",
    ]


# ── Bonus: invalid profile slug rejected with 400 ────────────────────


@pytest.mark.asyncio
async def test_invalid_profile_slug_rejected() -> None:
    """``?profile=speculative`` → 400 (via shared normaliser)."""
    db = _make_db_returning([])
    with pytest.raises(HTTPException) as exc:
        await list_model_portfolios(
            profile="speculative",
            limit=100,
            cursor=None,
            db=db,
            user=_make_user(),
            org_id=_ORG_ID,
        )
    assert exc.value.status_code == 400
