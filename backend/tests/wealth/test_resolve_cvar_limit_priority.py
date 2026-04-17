"""PR-A12.3 round-2 — _resolve_cvar_limit priority-chain regression tests.

Before this PR: ``_resolve_cvar_limit`` consulted only the ConfigService
profile default, making the ``portfolio_calibration.cvar_limit`` column
(seeded by PR-A12.2 migration 0143) a dead field in the construction hot
path. Observed on 2026-04-17: Conservative (operator 2.5%) → LP enforced
8% (3.2× overshoot) because ConfigService's default is -0.08 for the
conservative profile.

These tests close the integration gap A12.2 missed — the A12.2 test suite
validated only that the migration updated the COLUMN (SELECT ... → 0.025),
not that the optimizer consumed that value. Here we exercise the helper
directly against a mocked DB so the priority chain is locked.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.wealth.routes.model_portfolios import _resolve_cvar_limit


class _StubResult:
    """Mimic ``sqlalchemy.Result.scalar_one_or_none``."""

    def __init__(self, value: Any = None) -> None:  # type: ignore[name-defined]
        self._value = value

    def scalar_one_or_none(self) -> Any:  # type: ignore[override]
        return self._value


from typing import Any  # noqa: E402 — after helper class for clarity


def _make_db_with_calibration(cvar_limit_value: Any) -> MagicMock:
    """Return a session whose execute() yields the given calibration row."""
    db = MagicMock()
    db.execute = AsyncMock(return_value=_StubResult(cvar_limit_value))
    return db


# ── Layer 1 — per-portfolio override wins ─────────────────────────────


@pytest.mark.asyncio
async def test_per_portfolio_override_wins_over_config(monkeypatch) -> None:
    """A row in portfolio_calibration with a non-null cvar_limit is the
    authoritative source. ConfigService must NOT be consulted."""
    pid = uuid.uuid4()
    db = _make_db_with_calibration(Decimal("0.017"))

    # Sentinel that fails the test if ConfigService is called.
    def _explode(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("ConfigService must not be called when Layer 1 hits")

    monkeypatch.setattr(
        "app.core.config.config_service.ConfigService",
        _explode,
    )

    resolved = await _resolve_cvar_limit(
        db, "conservative", portfolio_id=pid, org_id="org-a",
    )
    assert resolved == pytest.approx(0.017)


@pytest.mark.asyncio
async def test_per_portfolio_override_normalized_to_positive(monkeypatch) -> None:
    """A negative-signed calibration value is canonicalised to positive."""
    pid = uuid.uuid4()
    db = _make_db_with_calibration(Decimal("-0.025"))

    resolved = await _resolve_cvar_limit(
        db, "conservative", portfolio_id=pid, org_id="org-a",
    )
    assert resolved == pytest.approx(0.025)


# ── Layer 2 — ConfigService fallback when calibration is NULL ─────────


@pytest.mark.asyncio
async def test_falls_back_to_config_when_calibration_null(monkeypatch) -> None:
    """When the calibration row exists but cvar_limit is NULL, ConfigService
    is consulted. Signed values are normalised to positive."""
    pid = uuid.uuid4()
    db = _make_db_with_calibration(None)  # Layer 1 miss

    stub_cfg = type("Cfg", (), {
        "value": {"profiles": {"conservative": {"cvar": {"limit": -0.08}}}},
    })()

    class _StubConfigService:
        def __init__(self, _db: Any) -> None: ...

        async def get(self, vertical: str, key: str, org: str | None) -> Any:
            return stub_cfg

    monkeypatch.setattr(
        "app.core.config.config_service.ConfigService",
        _StubConfigService,
    )

    resolved = await _resolve_cvar_limit(
        db, "conservative", portfolio_id=pid, org_id="org-a",
    )
    assert resolved == pytest.approx(0.08)


@pytest.mark.asyncio
async def test_falls_back_to_config_when_no_portfolio_id(monkeypatch) -> None:
    """Layer 1 is skipped entirely when portfolio_id is None (e.g. legacy
    callers that predate per-portfolio calibration)."""
    db = MagicMock()
    # execute should NOT be called because Layer 1 is skipped
    db.execute = AsyncMock(side_effect=AssertionError("Layer 1 must not run"))

    stub_cfg = type("Cfg", (), {
        "value": {"profiles": {"moderate": {"cvar": {"limit": -0.06}}}},
    })()

    class _StubConfigService:
        def __init__(self, _db: Any) -> None: ...

        async def get(self, *_a: Any, **_kw: Any) -> Any:
            return stub_cfg

    monkeypatch.setattr(
        "app.core.config.config_service.ConfigService",
        _StubConfigService,
    )

    resolved = await _resolve_cvar_limit(db, "moderate", portfolio_id=None)
    assert resolved == pytest.approx(0.06)


# ── Layer 3 — hardcoded fallback ──────────────────────────────────────


@pytest.mark.asyncio
async def test_falls_back_to_hardcoded_when_config_raises(monkeypatch) -> None:
    """If both Layer 1 and Layer 2 miss, the hardcoded safety-net default fires."""
    pid = uuid.uuid4()
    db = _make_db_with_calibration(None)

    class _StubConfigService:
        def __init__(self, _db: Any) -> None: ...

        async def get(self, *_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("config backend unavailable")

    monkeypatch.setattr(
        "app.core.config.config_service.ConfigService",
        _StubConfigService,
    )

    resolved = await _resolve_cvar_limit(
        db, "conservative", portfolio_id=pid, org_id="org-a",
    )
    # Hardcoded _DEFAULT_CVAR_LIMITS["conservative"] = -0.08 → abs = 0.08
    assert resolved == pytest.approx(0.08)


@pytest.mark.asyncio
async def test_falls_back_to_hardcoded_for_unknown_profile(monkeypatch) -> None:
    """Unknown profile → default 0.05."""
    db = MagicMock()
    db.execute = AsyncMock(return_value=_StubResult(None))

    class _StubConfigService:
        def __init__(self, _db: Any) -> None: ...

        async def get(self, *_a: Any, **_kw: Any) -> Any:
            return type("Cfg", (), {"value": {"profiles": {}}})()

    monkeypatch.setattr(
        "app.core.config.config_service.ConfigService",
        _StubConfigService,
    )

    resolved = await _resolve_cvar_limit(
        db, "unknown_profile", portfolio_id=uuid.uuid4(), org_id="org-a",
    )
    assert resolved == pytest.approx(0.05)
