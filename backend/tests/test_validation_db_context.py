"""Tests for PR-Q116 — ValidationDbContext population from DB.

Verifies that:
1. ``build_validation_db_context`` returns a fully-populated context.
2. The validation gate correctly uses the populated context to detect
   banned instruments (check 9) and approved universe (check 10).
3. Block constraints from strategic_allocation are passed through.
4. An empty context (pre-Q116 behavior) lets banned instruments pass
   undetected, confirming the defect existed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from vertical_engines.wealth.model_portfolio.validation_gate import (
    ValidationDbContext,
    validate_construction,
)

# ── Helpers ──────────────────────────────────────────────────────

_INSTRUMENT_IDS = [
    "11111111-1111-1111-1111-111111111111",
    "22222222-2222-2222-2222-222222222222",
    "33333333-3333-3333-3333-333333333333",
    "44444444-4444-4444-4444-444444444444",
    "55555555-5555-5555-5555-555555555555",
]


def _base_payload() -> dict[str, Any]:
    return {
        "as_of_date": "2026-04-08",
        "weights_proposed": {iid: 0.20 for iid in _INSTRUMENT_IDS},
        "calibration_snapshot": {
            "cvar_limit": 0.05,
            "max_single_fund_weight": 0.25,
            "turnover_cap": 0.30,
            "bl_enabled": False,
            "garch_enabled": False,
        },
        "ex_ante_metrics": {
            "cvar_95": -0.04,
            "expected_return": 0.08,
            "turnover": 0.10,
        },
        "funds": [
            {"instrument_id": iid, "block_id": "na_equity_large", "weight": 0.20}
            for iid in _INSTRUMENT_IDS
        ],
        "stress_results": [
            {"scenario": "gfc_2008", "nav_impact_pct": -0.15},
        ],
        "optimizer_trace": {},
        "statistical_inputs": {},
        "factor_exposure": {"average_r_squared": 0.65},
    }


def _populated_context(
    *,
    banned: frozenset[str] | None = None,
    approved: frozenset[str] | None = None,
) -> ValidationDbContext:
    """Build a context that mirrors what build_validation_db_context returns."""
    return ValidationDbContext(
        banned_instrument_ids=banned or frozenset(),
        approved_instrument_ids=approved or frozenset(_INSTRUMENT_IDS),
        strategic_targets={"na_equity_large": 1.0},
        block_constraints={"na_equity_large": (0.0, 1.0)},
        nav_latest_date={iid: "2026-04-07" for iid in _INSTRUMENT_IDS},
        nav_staleness_threshold_days=10,
    )


# ── Defect confirmation: empty context misses banned instruments ──


class TestEmptyContextDefect:
    """Confirms the pre-Q116 defect: empty context lets banned pass."""

    def test_empty_context_banned_check_passes_vacuously(self):
        """With empty banned set, check 9 always passes even if there
        SHOULD be banned instruments — the gate can't discriminate."""
        payload = _base_payload()
        empty_ctx = ValidationDbContext()
        result = validate_construction(payload, empty_ctx)
        check_9 = [c for c in result.checks if c.id == "no_banned_instruments"]
        assert len(check_9) == 1
        # Pre-Q116: always passes because banned set is empty
        assert check_9[0].passed is True

    def test_empty_context_approved_check_downgrades_to_warn(self):
        """With empty approved set, check 10 downgrades to warn-level
        pass with 'check skipped' explanation."""
        payload = _base_payload()
        empty_ctx = ValidationDbContext()
        result = validate_construction(payload, empty_ctx)
        check_10 = [c for c in result.checks if c.id == "all_instruments_approved"]
        assert len(check_10) == 1
        assert check_10[0].severity == "warn"
        assert check_10[0].passed is True
        assert "skipped" in check_10[0].explanation.lower()

    def test_empty_context_block_max_passes_vacuously(self):
        """With empty block_constraints, check 8 always passes."""
        payload = _base_payload()
        empty_ctx = ValidationDbContext()
        result = validate_construction(payload, empty_ctx)
        check_8 = [c for c in result.checks
                    if c.id == "all_block_max_weights_satisfied"]
        assert len(check_8) == 1
        assert check_8[0].passed is True


# ── Populated context: gate now enforces checks ──


class TestPopulatedContextEnforcement:
    """Verifies that a properly populated context makes the gate enforce."""

    def test_banned_instrument_detected_with_populated_context(self):
        """Check 9 (no_banned_instruments) FAILS when a weighted
        instrument is in the banned set — the core fix of PR-Q116."""
        payload = _base_payload()
        ctx = _populated_context(
            banned=frozenset({_INSTRUMENT_IDS[0]}),
        )
        result = validate_construction(payload, ctx)
        check_9 = [c for c in result.checks if c.id == "no_banned_instruments"]
        assert len(check_9) == 1
        assert check_9[0].passed is False
        assert check_9[0].severity == "block"
        assert result.passed is False

    def test_approved_universe_enforced_with_populated_context(self):
        """Check 10 (all_instruments_approved) FAILS when an instrument
        is not in the approved set."""
        payload = _base_payload()
        # Approve only 4 of 5 instruments
        ctx = _populated_context(
            approved=frozenset(_INSTRUMENT_IDS[:4]),
        )
        result = validate_construction(payload, ctx)
        check_10 = [c for c in result.checks
                     if c.id == "all_instruments_approved"]
        assert len(check_10) == 1
        assert check_10[0].passed is False
        assert check_10[0].severity == "block"

    def test_block_max_weight_enforced_with_populated_context(self):
        """Check 8 (block_max) FAILS when a block exceeds the max
        from block_constraints."""
        payload = _base_payload()
        # All 5 instruments in one block = 100% weight,
        # but max is 60%
        ctx = _populated_context()
        ctx = ValidationDbContext(
            banned_instrument_ids=ctx.banned_instrument_ids,
            approved_instrument_ids=ctx.approved_instrument_ids,
            strategic_targets={"na_equity_large": 0.50},
            block_constraints={"na_equity_large": (0.30, 0.60)},
            nav_latest_date=ctx.nav_latest_date,
        )
        result = validate_construction(payload, ctx)
        check_8 = [c for c in result.checks
                    if c.id == "all_block_max_weights_satisfied"]
        assert len(check_8) == 1
        assert check_8[0].passed is False
        assert check_8[0].severity == "block"

    def test_all_checks_pass_with_correct_populated_context(self):
        """A fully-correct context + payload passes all checks."""
        payload = _base_payload()
        ctx = _populated_context()
        result = validate_construction(payload, ctx)
        assert result.passed is True
        block_failures = [c for c in result.checks
                          if c.severity == "block" and not c.passed]
        assert len(block_failures) == 0


# ── build_validation_db_context unit test (mocked DB) ──


class TestBuildValidationDbContext:
    """Test the query helper with a mocked AsyncSession."""

    @pytest.mark.asyncio
    async def test_builds_context_with_all_fields(self):
        """Verify the returned context has all 5 fields populated."""
        from app.domains.wealth.queries.validation_context import (
            build_validation_db_context,
        )

        # Mock DB session that returns canned rows for each query
        db = AsyncMock()

        # Track call count to return different results per query
        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Banned instruments query
                result.all.return_value = [
                    (_INSTRUMENT_IDS[4],),
                ]
            elif call_count == 2:
                # Approved instruments query
                result.all.return_value = [
                    (iid,) for iid in _INSTRUMENT_IDS[:4]
                ]
            elif call_count == 3:
                # Block constraints query — 5 columns:
                # (block_id, override_min, override_max, excluded, target_w)
                result.all.return_value = [
                    ("na_equity_large", 0.30, 0.70, False, 0.50),
                    ("fi_treasury", 0.20, 0.40, False, 0.30),
                ]
            elif call_count == 4:
                # NAV latest dates query
                result.all.return_value = [
                    (iid, "2026-04-07") for iid in _INSTRUMENT_IDS
                ]
            else:
                result.all.return_value = []
            return result

        db.execute = _mock_execute

        import uuid as _uuid

        ctx = await build_validation_db_context(
            db,
            organization_id=_uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            profile="conservative",
            instrument_ids=_INSTRUMENT_IDS,
        )

        assert isinstance(ctx, ValidationDbContext)
        assert _INSTRUMENT_IDS[4] in ctx.banned_instrument_ids
        assert len(ctx.approved_instrument_ids) == 4
        assert "na_equity_large" in ctx.block_constraints
        assert ctx.block_constraints["na_equity_large"] == (0.30, 0.70)
        assert "fi_treasury" in ctx.block_constraints
        assert len(ctx.nav_latest_date) == 5
        assert ctx.strategic_targets["na_equity_large"] == 0.50
        assert ctx.nav_staleness_threshold_days == 10

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_context(self):
        """When the org has no data, context fields are empty but valid."""
        from app.domains.wealth.queries.validation_context import (
            build_validation_db_context,
        )

        db = AsyncMock()

        async def _mock_execute(stmt, params=None):
            result = MagicMock()
            result.all.return_value = []
            return result

        db.execute = _mock_execute

        import uuid as _uuid

        ctx = await build_validation_db_context(
            db,
            organization_id=_uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            profile="conservative",
            instrument_ids=[],
        )

        assert isinstance(ctx, ValidationDbContext)
        assert len(ctx.banned_instrument_ids) == 0
        assert len(ctx.approved_instrument_ids) == 0
        assert len(ctx.block_constraints) == 0
        assert len(ctx.nav_latest_date) == 0
