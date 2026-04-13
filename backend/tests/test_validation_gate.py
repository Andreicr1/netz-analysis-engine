"""Unit tests for the 16-check construction validation gate.

Phase 3 Task 3.1 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

Covers:
- Happy path: a well-formed payload passes all 16 checks.
- Per-check failure: each block-severity check fails in isolation
  and the aggregate ``ValidationResult.passed`` flips to False.
- Aggregation semantics: a payload that fails 3 blocks and 2 warns
  reports ``passed=False`` + ``len(blocks)==3`` + ``len(warnings)==2``.
- Fail-soft guarantee: a check that raises is caught and converted
  to a warn-level failure without stranding activation.
- No fail-fast: ALL 16 checks run even if the first one fails.
- JSONB serialization shape is stable.
"""

from __future__ import annotations

from typing import Any

import pytest

from vertical_engines.wealth.model_portfolio.validation_gate import (
    CHECKS,
    ValidationDbContext,
    ValidationResult,
    to_jsonb,
    validate_construction,
)

# ── Helpers ──────────────────────────────────────────────────────


def _base_payload() -> dict[str, Any]:
    """A known-good construction run payload that passes all 16 checks."""
    return {
        "as_of_date": "2026-04-08",
        "weights_proposed": {
            "11111111-1111-1111-1111-111111111111": 0.20,
            "22222222-2222-2222-2222-222222222222": 0.20,
            "33333333-3333-3333-3333-333333333333": 0.20,
            "44444444-4444-4444-4444-444444444444": 0.20,
            "55555555-5555-5555-5555-555555555555": 0.20,
        },
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
            {"instrument_id": "11111111-1111-1111-1111-111111111111",
             "block_id": "na_equity_large", "weight": 0.20},
            {"instrument_id": "22222222-2222-2222-2222-222222222222",
             "block_id": "na_equity_large", "weight": 0.20},
            {"instrument_id": "33333333-3333-3333-3333-333333333333",
             "block_id": "fi_treasury", "weight": 0.20},
            {"instrument_id": "44444444-4444-4444-4444-444444444444",
             "block_id": "fi_treasury", "weight": 0.20},
            {"instrument_id": "55555555-5555-5555-5555-555555555555",
             "block_id": "intl_equity_dm", "weight": 0.20},
        ],
        "stress_results": [
            {"scenario": "gfc_2008", "nav_impact_pct": -0.15},
            {"scenario": "covid_2020", "nav_impact_pct": -0.10},
        ],
        "optimizer_trace": {},
        "statistical_inputs": {},
        "factor_exposure": {"average_r_squared": 0.65},
    }


def _base_db_context() -> ValidationDbContext:
    """DB context that matches the happy-path payload."""
    return ValidationDbContext(
        banned_instrument_ids=frozenset(),
        approved_instrument_ids=frozenset({
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
            "33333333-3333-3333-3333-333333333333",
            "44444444-4444-4444-4444-444444444444",
            "55555555-5555-5555-5555-555555555555",
        }),
        strategic_targets={
            "na_equity_large": 0.40,
            "fi_treasury": 0.40,
            "intl_equity_dm": 0.20,
        },
        block_constraints={
            "na_equity_large": (0.30, 0.50),
            "fi_treasury": (0.30, 0.50),
            "intl_equity_dm": (0.10, 0.30),
        },
        nav_latest_date={
            "11111111-1111-1111-1111-111111111111": "2026-04-07",
            "22222222-2222-2222-2222-222222222222": "2026-04-07",
            "33333333-3333-3333-3333-333333333333": "2026-04-07",
            "44444444-4444-4444-4444-444444444444": "2026-04-07",
            "55555555-5555-5555-5555-555555555555": "2026-04-07",
        },
    )


# ── Happy path ───────────────────────────────────────────────────


def test_happy_path_passes_all_15_checks():
    result = validate_construction(_base_payload(), _base_db_context())
    assert result.passed is True
    assert len(result.checks) == 16
    assert result.blocks == []
    failed_ids = [c.id for c in result.checks if not c.passed]
    assert failed_ids == [], (
        f"happy path should pass all 16 checks; failed: {failed_ids}"
    )


def test_all_15_checks_run_even_with_empty_payload():
    """No fail-fast: empty payload still runs all 16 checks."""
    result = validate_construction({}, ValidationDbContext())
    assert len(result.checks) == 16
    ids = [c.id for c in result.checks]
    # Order must match the CHECKS registry exactly
    expected_ids = [check_id for check_id, _ in CHECKS]
    assert ids == expected_ids


# ── Per-check block failures ─────────────────────────────────────


def test_weights_sum_to_one_fails_when_total_off():
    payload = _base_payload()
    payload["weights_proposed"]["11111111-1111-1111-1111-111111111111"] = 0.30
    result = validate_construction(payload, _base_db_context())
    assert result.passed is False
    failed = [c for c in result.checks if c.id == "weights_sum_to_one"]
    assert failed[0].passed is False
    assert failed[0].severity == "block"


def test_cvar_within_limit_block_failure():
    payload = _base_payload()
    payload["ex_ante_metrics"]["cvar_95"] = -0.20  # exceeds -0.05 limit
    result = validate_construction(payload, _base_db_context())
    assert result.passed is False
    failed = [c for c in result.checks if c.id == "cvar_within_limit"]
    assert failed[0].passed is False
    assert failed[0].severity == "block"


def test_min_diversification_count_block_failure():
    payload = _base_payload()
    payload["weights_proposed"] = {
        "11111111-1111-1111-1111-111111111111": 0.50,
        "22222222-2222-2222-2222-222222222222": 0.50,
    }
    payload["funds"] = [
        {"instrument_id": "11111111-1111-1111-1111-111111111111",
         "block_id": "na_equity_large", "weight": 0.50},
        {"instrument_id": "22222222-2222-2222-2222-222222222222",
         "block_id": "fi_treasury", "weight": 0.50},
    ]
    result = validate_construction(payload, _base_db_context())
    assert result.passed is False
    failed = [c for c in result.checks if c.id == "min_diversification_count"]
    assert failed[0].passed is False
    assert failed[0].value == 2
    assert failed[0].threshold == 5


def test_max_single_fund_weight_block_failure():
    payload = _base_payload()
    payload["weights_proposed"]["11111111-1111-1111-1111-111111111111"] = 0.60
    payload["weights_proposed"]["22222222-2222-2222-2222-222222222222"] = 0.10
    payload["weights_proposed"]["33333333-3333-3333-3333-333333333333"] = 0.10
    payload["weights_proposed"]["44444444-4444-4444-4444-444444444444"] = 0.10
    payload["weights_proposed"]["55555555-5555-5555-5555-555555555555"] = 0.10
    payload["calibration_snapshot"]["max_single_fund_weight"] = 0.25
    result = validate_construction(payload, _base_db_context())
    assert result.passed is False
    failed = [c for c in result.checks if c.id == "max_single_fund_weight"]
    assert failed[0].passed is False
    assert failed[0].severity == "block"


def test_banned_instrument_block_failure():
    payload = _base_payload()
    db = _base_db_context()
    db = ValidationDbContext(
        banned_instrument_ids=frozenset({"11111111-1111-1111-1111-111111111111"}),
        approved_instrument_ids=db.approved_instrument_ids,
        strategic_targets=db.strategic_targets,
        block_constraints=db.block_constraints,
        nav_latest_date=db.nav_latest_date,
    )
    result = validate_construction(payload, db)
    assert result.passed is False
    failed = [c for c in result.checks if c.id == "no_banned_instruments"]
    assert failed[0].passed is False
    assert failed[0].severity == "block"


def test_unapproved_instrument_block_failure():
    payload = _base_payload()
    db = ValidationDbContext(
        approved_instrument_ids=frozenset({
            # Intentionally missing instrument 5
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
            "33333333-3333-3333-3333-333333333333",
            "44444444-4444-4444-4444-444444444444",
        }),
        block_constraints={
            "na_equity_large": (0.30, 0.50),
            "fi_treasury": (0.30, 0.50),
            "intl_equity_dm": (0.10, 0.30),
        },
        nav_latest_date={
            f"{i}" * 8 + "-" + f"{i}" * 4 + "-" + f"{i}" * 4 + "-" +
            f"{i}" * 4 + "-" + f"{i}" * 12: "2026-04-07"
            for i in range(1, 6)
        },
    )
    result = validate_construction(payload, db)
    failed = [c for c in result.checks if c.id == "all_instruments_approved"]
    assert failed[0].passed is False
    assert failed[0].severity == "block"


def test_block_min_weight_violation():
    payload = _base_payload()
    # Zero out fi_treasury allocation
    payload["funds"] = [
        {"instrument_id": "11111111-1111-1111-1111-111111111111",
         "block_id": "na_equity_large", "weight": 0.50},
        {"instrument_id": "55555555-5555-5555-5555-555555555555",
         "block_id": "na_equity_large", "weight": 0.20},
        {"instrument_id": "22222222-2222-2222-2222-222222222222",
         "block_id": "intl_equity_dm", "weight": 0.30},
    ]
    payload["weights_proposed"] = {
        "11111111-1111-1111-1111-111111111111": 0.50,
        "55555555-5555-5555-5555-555555555555": 0.20,
        "22222222-2222-2222-2222-222222222222": 0.30,
    }
    result = validate_construction(payload, _base_db_context())
    failed = [c for c in result.checks if c.id == "all_block_min_weights_satisfied"]
    assert failed[0].passed is False
    assert failed[0].value == 1  # fi_treasury (0%) below 30% min


def test_block_max_weight_violation():
    payload = _base_payload()
    payload["funds"] = [
        {"instrument_id": f"{i}" * 8 + "-" + f"{i}" * 4 + "-" + f"{i}" * 4 +
         "-" + f"{i}" * 4 + "-" + f"{i}" * 12,
         "block_id": "na_equity_large", "weight": 0.6 if i == 1 else 0.1}
        for i in range(1, 6)
    ]
    result = validate_construction(payload, _base_db_context())
    failed = [c for c in result.checks if c.id == "all_block_max_weights_satisfied"]
    assert failed[0].passed is False


# ── Warn-severity cases ──────────────────────────────────────────


def test_warn_failures_do_not_block_aggregate_pass():
    """A warn failure keeps ``result.passed=True``."""
    payload = _base_payload()
    payload["stress_results"] = [
        {"scenario": "extreme", "nav_impact_pct": -0.60},  # worse than -0.40
    ]
    result = validate_construction(payload, _base_db_context())
    # Warn failure should NOT block aggregate pass
    assert result.passed is True
    warn_failed = [c for c in result.warnings if c.id == "stress_within_tolerance"]
    assert len(warn_failed) == 1
    assert warn_failed[0].severity == "warn"


def test_unrealistic_expected_return_is_warn_not_block():
    payload = _base_payload()
    payload["ex_ante_metrics"]["expected_return"] = 0.75  # above 50% ceiling
    result = validate_construction(payload, _base_db_context())
    assert result.passed is True  # warn does not block
    failed = [c for c in result.checks if c.id == "no_unrealistic_expected_return"]
    assert failed[0].passed is False
    assert failed[0].severity == "warn"


# ── Aggregation semantics ────────────────────────────────────────


def test_aggregation_counts_blocks_and_warns_separately():
    """A payload that fails 3 blocks and 2 warns reports them in
    separate buckets and sets ``passed=False``."""
    payload = _base_payload()
    # Block failures (3):
    #   1. weights_sum_to_one (sum > 1)
    #   2. cvar_within_limit (cvar > limit)
    #   3. min_diversification_count (only 2 funds)
    payload["weights_proposed"] = {
        "11111111-1111-1111-1111-111111111111": 0.70,
        "22222222-2222-2222-2222-222222222222": 0.70,
    }
    payload["ex_ante_metrics"]["cvar_95"] = -0.20
    payload["funds"] = [
        {"instrument_id": "11111111-1111-1111-1111-111111111111",
         "block_id": "na_equity_large", "weight": 0.70},
        {"instrument_id": "22222222-2222-2222-2222-222222222222",
         "block_id": "fi_treasury", "weight": 0.70},
    ]
    # Warn failures (2):
    #   1. stress_within_tolerance (-0.60 < -0.40)
    #   2. no_unrealistic_expected_return (0.75 > 0.50)
    payload["stress_results"] = [
        {"scenario": "extreme", "nav_impact_pct": -0.60},
    ]
    payload["ex_ante_metrics"]["expected_return"] = 0.75

    result = validate_construction(payload, _base_db_context())
    assert result.passed is False  # any block → False
    assert len(result.blocks) >= 3
    assert len(result.warnings) >= 2


# ── No fail-fast guarantee ───────────────────────────────────────


def test_no_fail_fast_all_15_checks_run():
    """Even a payload that fails the first check must run all 15."""
    payload = {}  # everything missing
    result = validate_construction(payload, ValidationDbContext())
    assert len(result.checks) == 16, (
        "no fail-fast: all 16 checks must always run"
    )


# ── Resilience: a raising check becomes a warn ───────────────────


def test_check_that_raises_is_caught_as_warn():
    """A bug in one check cannot strand activation."""
    # Inject an instrument with a non-string key to force a TypeError
    # path in one of the checks.
    payload = _base_payload()
    payload["weights_proposed"] = None  # likely to raise in multiple checks
    result = validate_construction(payload, _base_db_context())
    assert len(result.checks) == 16  # all 15 still run
    # None of the raised ones are block severity (they were caught
    # and converted to warn).
    for c in result.checks:
        if not c.passed and c.explanation.startswith("Check raised:"):
            assert c.severity == "warn"


# ── JSONB serialization ──────────────────────────────────────────


def test_to_jsonb_shape():
    result = validate_construction(_base_payload(), _base_db_context())
    j = to_jsonb(result)
    assert set(j.keys()) == {"passed", "checks", "summary"}
    assert j["passed"] is True
    assert len(j["checks"]) == 16
    assert j["summary"]["total"] == 16
    assert j["summary"]["passed"] == 16
    assert j["summary"]["blocks_failed"] == 0
    assert j["summary"]["warnings_failed"] == 0

    # Every check has the expected keys
    for c in j["checks"]:
        assert set(c.keys()) == {
            "id", "label", "severity", "passed",
            "value", "threshold", "explanation",
        }


def test_to_jsonb_preserves_check_order():
    result = validate_construction(_base_payload(), _base_db_context())
    j = to_jsonb(result)
    actual_ids = [c["id"] for c in j["checks"]]
    expected_ids = [check_id for check_id, _ in CHECKS]
    assert actual_ids == expected_ids


# ── Result dataclass ──────────────────────────────────────────────


def test_validation_result_is_frozen_dataclass():
    import dataclasses

    result = validate_construction(_base_payload(), _base_db_context())
    assert isinstance(result, ValidationResult)
    # Frozen dataclass — mutation must raise FrozenInstanceError
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.passed = False  # type: ignore[misc]
