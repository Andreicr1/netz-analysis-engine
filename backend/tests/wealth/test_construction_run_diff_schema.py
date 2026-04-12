"""Tests for the ConstructionRunDiffOut schema.

Phase 2 Session C commit 4 — locks in the wire contract of the
``/model-portfolios/{id}/construction/runs/{runId}/diff`` endpoint.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.domains.wealth.schemas.model_portfolio import (
    ConstructionRunDiffOut,
    ConstructionRunMetricDelta,
    ConstructionRunWeightDelta,
)


def _build_diff(
    metrics_delta_override: dict[str, ConstructionRunMetricDelta] | None = None,
) -> ConstructionRunDiffOut:
    return ConstructionRunDiffOut(
        portfolio_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        run_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        previous_run_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        requested_at=datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc),
        weight_delta={
            "inst-a": ConstructionRunWeightDelta(
                **{"from": 0.10, "to": 0.15, "delta": 0.05},
            ),
            "inst-b": ConstructionRunWeightDelta(
                **{"from": 0.20, "to": 0.18, "delta": -0.02},
            ),
        },
        metrics_delta=metrics_delta_override or {
            "expected_return": ConstructionRunMetricDelta(
                **{"from": 0.072, "to": 0.078, "delta": 0.006},
            ),
        },
        status_delta_text="delta computed",
    )


def test_weight_delta_populate_by_name_and_alias() -> None:
    """Schema accepts both ``from_weight``/``to_weight`` and ``from``/``to``."""
    via_alias = ConstructionRunWeightDelta(**{"from": 0.1, "to": 0.2, "delta": 0.1})
    via_name = ConstructionRunWeightDelta(from_weight=0.1, to_weight=0.2, delta=0.1)
    assert via_alias.from_weight == via_name.from_weight == 0.1
    assert via_alias.to_weight == via_name.to_weight == 0.2
    # Wire format uses the short ``from``/``to`` keys
    dumped = via_alias.model_dump(by_alias=True)
    assert dumped == {"from": 0.1, "to": 0.2, "delta": 0.1}


def test_metric_delta_accepts_none_for_non_numeric() -> None:
    """Non-numeric metrics land with delta=None from the MV."""
    delta = ConstructionRunMetricDelta(
        **{"from": None, "to": None, "delta": None},
    )
    assert delta.delta is None


def test_diff_out_sanitizes_metrics_delta_keys() -> None:
    """Residual raw jargon keys get humanised by the post-init validator."""
    # Simulate a regression where the MV still carries raw keys.
    raw_keys = {
        "cvar_95": ConstructionRunMetricDelta(
            **{"from": 0.05, "to": 0.04, "delta": -0.01},
        ),
        "volatility_garch": ConstructionRunMetricDelta(
            **{"from": 0.15, "to": 0.12, "delta": -0.03},
        ),
    }
    diff = _build_diff(metrics_delta_override=raw_keys)

    # The two raw keys should be gone — replaced by institutional labels.
    assert "cvar_95" not in diff.metrics_delta
    assert "volatility_garch" not in diff.metrics_delta
    # Human labels contain the institutional phrasing
    labels = list(diff.metrics_delta.keys())
    assert any("Conditional Tail Risk" in k for k in labels)
    assert any("Conditional Volatility" in k for k in labels)


def test_diff_out_round_trip_via_model_dump_json() -> None:
    diff = _build_diff()
    payload = diff.model_dump(by_alias=True)
    assert payload["status_delta_text"] == "delta computed"
    assert "weight_delta" in payload
    assert payload["weight_delta"]["inst-a"] == {"from": 0.10, "to": 0.15, "delta": 0.05}
    # Known-clean keys survive the sanitisation pass unchanged
    assert "expected_return" in payload["metrics_delta"]


def test_diff_out_empty_weight_and_metrics() -> None:
    diff = ConstructionRunDiffOut(
        portfolio_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        previous_run_id=None,
        requested_at=None,
        weight_delta={},
        metrics_delta={},
        status_delta_text="initial run",
    )
    assert diff.weight_delta == {}
    assert diff.metrics_delta == {}
    assert diff.previous_run_id is None
