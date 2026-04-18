"""PR-A26.1 — Propose-mode unit tests.

Covers the pure helpers that drive the propose payload:

* :func:`_derive_drift_band` — hybrid ``max(0.02, 0.15 * target)``.
* :func:`_build_propose_payload` — block aggregation, exclusion
  handling, ``cvar_feasible`` derivation, and winner_signal
  classification.

Heavier end-to-end coverage (gate ordering, SSE, endpoint dispatch)
belongs to ``backend/tests/wealth/test_propose_allocation_endpoint.py``;
this module stays in-process and DB-free so the propose math is
locked down even when the integration suite is skipped in CI.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.wealth.schemas.sanitized import WinnerSignal
from app.domains.wealth.workers.construction_run_executor import (
    _build_propose_payload,
    _derive_drift_band,
)


# ── Drift band math ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("target", "expected_min", "expected_max"),
    [
        # Floor regime: 2% absolute drift dominates.
        (0.05, 0.03, 0.07),
        (0.10, 0.08, 0.12),
        # 15% relative regime takes over once target ≥ 0.1334...
        (0.40, 0.34, 0.46),
        (0.20, 0.17, 0.23),
        # Edge: exactly 13.33% — drift = 0.02 (floor still wins).
        (0.13, 0.11, 0.15),
        # Zero target → collapsed band (used for excluded blocks).
        (0.0, 0.0, 0.0),
        (-0.01, 0.0, 0.0),
    ],
)
def test_drift_band_matches_spec(
    target: float, expected_min: float, expected_max: float,
) -> None:
    drift_min, drift_max = _derive_drift_band(target)
    assert drift_min == pytest.approx(expected_min, abs=1e-6)
    assert drift_max == pytest.approx(expected_max, abs=1e-6)


def test_drift_band_clamps_above_one() -> None:
    drift_min, drift_max = _derive_drift_band(0.95)
    assert drift_max == pytest.approx(1.0)
    assert drift_min == pytest.approx(0.95 - max(0.02, 0.15 * 0.95))


# ── _build_propose_payload ───────────────────────────────────────


_CANONICAL_BLOCKS: tuple[str, ...] = (
    "na_equity_large",
    "na_equity_growth",
    "fi_us_aggregate",
    "fi_us_treasury",
    "alt_gold",
    "cash",
)


@dataclass
class _FakeRow:
    """Tuple-like row stand-in for SQLAlchemy ``.all()`` results."""

    value: str

    def __getitem__(self, idx: int) -> str:
        if idx != 0:
            raise IndexError(idx)
        return self.value


def _make_db_mock(
    *, canonical_blocks: Iterable[str], excluded_blocks: Iterable[str],
) -> AsyncMock:
    """Build an AsyncMock for ``db.execute`` that returns the two row sets
    consumed by ``_build_propose_payload`` in order: canonical block ids,
    then excluded block ids.
    """
    canonical_result = MagicMock()
    canonical_result.all.return_value = [
        _FakeRow(b) for b in canonical_blocks
    ]
    excluded_result = MagicMock()
    excluded_result.all.return_value = [_FakeRow(b) for b in excluded_blocks]

    db = AsyncMock()
    # First call → canonical query, second → excluded query.
    db.execute.side_effect = [canonical_result, excluded_result]
    return db


@pytest.mark.asyncio
async def test_propose_payload_aggregates_funds_to_blocks() -> None:
    db = _make_db_mock(
        canonical_blocks=_CANONICAL_BLOCKS, excluded_blocks=[],
    )
    base_result: dict[str, Any] = {
        "funds": [
            {"instrument_id": "f1", "block_id": "na_equity_large", "weight": 0.20},
            {"instrument_id": "f2", "block_id": "na_equity_large", "weight": 0.12},
            {"instrument_id": "f3", "block_id": "fi_us_aggregate", "weight": 0.40},
            {"instrument_id": "f4", "block_id": "alt_gold", "weight": 0.05},
            {"instrument_id": "f5", "block_id": "cash", "weight": 0.23},
        ],
        "cascade": {"winning_phase": "phase_1_ru_max_return"},
    }
    payload = await _build_propose_payload(
        db,
        organization_id="org-abc",
        profile="growth",
        base_result=base_result,
        cascade_telemetry={},
        ex_ante_metrics={
            "expected_return": 0.087,
            "cvar_95": 0.029,
            "sharpe_ratio": 1.4,
        },
        calibration_snapshot={"cvar_limit": 0.03},
    )

    bands_by_block = {b["block_id"]: b for b in payload["proposed_bands"]}
    assert set(bands_by_block) == set(_CANONICAL_BLOCKS)

    # Aggregation: na_equity_large = 0.20 + 0.12 = 0.32.
    nael = bands_by_block["na_equity_large"]
    assert nael["target_weight"] == pytest.approx(0.32)
    assert nael["drift_min"] == pytest.approx(0.272, abs=1e-6)
    assert nael["drift_max"] == pytest.approx(0.368, abs=1e-6)

    # Block with no allocation → zero band.
    assert bands_by_block["na_equity_growth"]["target_weight"] == 0.0
    assert bands_by_block["na_equity_growth"]["drift_min"] == 0.0
    assert bands_by_block["na_equity_growth"]["drift_max"] == 0.0

    # Phase 1 winner → cvar_feasible AND PROPOSAL_READY.
    assert payload["proposal_metrics"]["cvar_feasible"] is True
    assert payload["proposal_metrics"]["expected_return"] == pytest.approx(0.087)
    assert payload["proposal_metrics"]["target_cvar"] == pytest.approx(0.03)
    assert payload["winner_signal"] == WinnerSignal.PROPOSAL_READY.value
    assert payload["run_mode"] == "propose"


@pytest.mark.asyncio
async def test_propose_payload_zeros_excluded_blocks() -> None:
    db = _make_db_mock(
        canonical_blocks=_CANONICAL_BLOCKS,
        excluded_blocks=["alt_gold"],
    )
    # The optimizer would never assign weight to alt_gold under propose
    # mode (max=0 in BlockConstraint), but the payload assembly must
    # also defensively zero it AND attach the exclusion rationale.
    base_result: dict[str, Any] = {
        "funds": [
            {"instrument_id": "f1", "block_id": "na_equity_large", "weight": 0.50},
            {"instrument_id": "f2", "block_id": "fi_us_aggregate", "weight": 0.50},
        ],
        "cascade": {"winning_phase": "phase_1_ru_max_return"},
    }
    payload = await _build_propose_payload(
        db,
        organization_id="org-abc",
        profile="growth",
        base_result=base_result,
        cascade_telemetry={},
        ex_ante_metrics={"cvar_95": 0.04, "expected_return": 0.06, "sharpe_ratio": 0.9},
        calibration_snapshot={"cvar_limit": 0.05},
    )
    bands_by_block = {b["block_id"]: b for b in payload["proposed_bands"]}
    gold = bands_by_block["alt_gold"]
    assert gold["target_weight"] == 0.0
    assert gold["drift_min"] == 0.0
    assert gold["drift_max"] == 0.0
    assert "excluded" in (gold["rationale"] or "").lower()


@pytest.mark.asyncio
async def test_propose_payload_phase_3_marks_cvar_infeasible() -> None:
    db = _make_db_mock(
        canonical_blocks=_CANONICAL_BLOCKS, excluded_blocks=[],
    )
    base_result: dict[str, Any] = {
        "funds": [
            {"instrument_id": "f1", "block_id": "fi_us_treasury", "weight": 0.60},
            {"instrument_id": "f2", "block_id": "cash", "weight": 0.40},
        ],
        # Phase 3 fallback: universe cannot meet the operator's CVaR
        # target — return the min-CVaR portfolio anyway and flag it.
        "cascade": {"winning_phase": "phase_3_min_cvar"},
    }
    payload = await _build_propose_payload(
        db,
        organization_id="org-abc",
        profile="conservative",
        base_result=base_result,
        cascade_telemetry={},
        ex_ante_metrics={
            "expected_return": 0.025,
            "cvar_95": 0.07,
            "sharpe_ratio": 0.4,
        },
        calibration_snapshot={"cvar_limit": 0.025},
    )
    assert payload["proposal_metrics"]["cvar_feasible"] is False
    assert payload["winner_signal"] == WinnerSignal.PROPOSAL_CVAR_INFEASIBLE.value
    # Bands still emitted so the operator can review what min-CVaR looks like.
    bands_by_block = {b["block_id"]: b for b in payload["proposed_bands"]}
    assert bands_by_block["fi_us_treasury"]["target_weight"] == pytest.approx(0.60)
    assert bands_by_block["cash"]["target_weight"] == pytest.approx(0.40)


@pytest.mark.asyncio
async def test_propose_payload_phase_2_robust_is_feasible() -> None:
    db = _make_db_mock(
        canonical_blocks=_CANONICAL_BLOCKS, excluded_blocks=[],
    )
    base_result: dict[str, Any] = {
        "funds": [
            {"instrument_id": "f1", "block_id": "na_equity_large", "weight": 0.50},
            {"instrument_id": "f2", "block_id": "fi_us_aggregate", "weight": 0.50},
        ],
        "cascade": {"winning_phase": "phase_2_ru_robust"},
    }
    payload = await _build_propose_payload(
        db,
        organization_id="org-abc",
        profile="moderate",
        base_result=base_result,
        cascade_telemetry={},
        ex_ante_metrics={
            "expected_return": 0.07,
            "cvar_95": 0.045,
            "sharpe_ratio": 1.1,
        },
        calibration_snapshot={"cvar_limit": 0.05},
    )
    assert payload["proposal_metrics"]["cvar_feasible"] is True
    assert payload["winner_signal"] == WinnerSignal.PROPOSAL_READY.value


# ── Enum surface ────────────────────────────────────────────────


def test_winner_signal_enum_carries_propose_members() -> None:
    assert WinnerSignal.PROPOSAL_READY.value == "proposal_ready"
    assert WinnerSignal.PROPOSAL_CVAR_INFEASIBLE.value == "proposal_cvar_infeasible"
