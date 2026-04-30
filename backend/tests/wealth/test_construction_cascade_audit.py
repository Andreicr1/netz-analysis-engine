"""PR-Q144: cascade completion emits write_audit_event (C-03 fix).

Tests that:
- A completed cascade run emits exactly ONE ``model_portfolio.cascade_completed``
  audit event via ``write_audit_event``.
- The ``after`` JSONB payload contains the required fields (winning_phase,
  cascade_summary, run_status, min_achievable_cvar, cvar_enforcement, phase_attempts).
- The audit event is flushed atomically with the run row update — if
  ``write_audit_event`` raises, the entire transaction (including run status
  and completed_at) rolls back.
- Cancelled runs do NOT emit a cascade audit event.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MODULE = "app.domains.wealth.workers.construction_run_executor"


def _stub_calibration() -> dict[str, Any]:
    """Minimal calibration snapshot for the executor."""
    return {
        "profile": "balanced",
        "cvar_limit": 0.05,
        "stress_scenarios_active": [],
        "stress_severity_multiplier": 1.0,
        "advisor_enabled": False,
    }


def _phase_1_cascade_telemetry() -> dict[str, Any]:
    """Telemetry dict as built by _build_cascade_telemetry for a Phase 1 win."""
    return {
        "winning_phase": "phase_1_ru_max_return",
        "cascade_summary": "phase_1_succeeded",
        "min_achievable_cvar": 0.035,
        "phase_attempts": [
            {"phase": "phase_1_ru_max_return", "status": "succeeded"},
            {"phase": "phase_2_ru_robust", "status": "skipped"},
            {"phase": "phase_3_min_cvar", "status": "succeeded"},
        ],
        "operator_signal": None,
    }


async def _fake_execute_inner_phase1(
    *, db, run, portfolio_id, calibration_snapshot, job_id, propose_mode,
):
    """Simulate _execute_inner setting cascade_telemetry on the run row."""
    run.cascade_telemetry = _phase_1_cascade_telemetry()
    run.optimizer_trace = {"status": "optimal", "solver": "CLARABEL"}
    run.weights_proposed = {"fund_a": 0.6, "fund_b": 0.4}


async def _fake_execute_inner_cancelled(
    *, db, run, portfolio_id, calibration_snapshot, job_id, propose_mode,
):
    """Simulate _execute_inner raising a cancellation."""
    from app.domains.wealth.workers.construction_run_executor import (
        RunCancelledError,
    )

    raise RunCancelledError("pre_optimizer")


def _mock_db() -> AsyncMock:
    """Build a mocked AsyncSession for execute_construction_run."""
    db = AsyncMock()
    # flush and refresh are no-ops
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    # add is synchronous
    db.add = MagicMock()
    # execute returns something that supports scalar()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalar.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    return db


@pytest.mark.asyncio
async def test_cascade_completion_emits_audit_event():
    """A completed cascade run must emit exactly ONE write_audit_event with
    action=model_portfolio.cascade_completed and allow_global=False."""
    db = _mock_db()
    portfolio_id = uuid.uuid4()
    org_id = uuid.uuid4()

    with (
        patch(f"{MODULE}._load_calibration", new_callable=AsyncMock, return_value=_stub_calibration()),
        patch(f"{MODULE}._execute_inner", side_effect=_fake_execute_inner_phase1),
        patch(f"{MODULE}._publish_event_sanitized", new_callable=AsyncMock, return_value={}),
        patch(f"{MODULE}._publish_terminal_event_sanitized", new_callable=AsyncMock, return_value={}),
        patch(f"{MODULE}.write_audit_event", new_callable=AsyncMock) as mock_audit,
        patch(f"{MODULE}.clear_cancellation_flag", new_callable=AsyncMock),
    ):
        from app.domains.wealth.workers.construction_run_executor import (
            execute_construction_run,
        )

        run = await execute_construction_run(
            db,
            portfolio_id=portfolio_id,
            organization_id=org_id,
            requested_by="operator-1",
            job_id="job-abc",
            as_of_date=date(2026, 4, 29),
        )

        # Exactly one audit event
        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["action"] == "model_portfolio.cascade_completed"
        assert kwargs["entity_type"] == "ConstructionRun"
        assert kwargs["entity_id"] == str(run.id)
        assert kwargs["allow_global"] is False
        assert kwargs["actor_id"] == "operator-1"


@pytest.mark.asyncio
async def test_audit_after_payload_includes_winning_phase():
    """The ``after`` JSONB must contain winning_phase, cascade_summary,
    run_status, min_achievable_cvar, cvar_enforcement, and phase_attempts."""
    db = _mock_db()
    portfolio_id = uuid.uuid4()
    org_id = uuid.uuid4()

    with (
        patch(f"{MODULE}._load_calibration", new_callable=AsyncMock, return_value=_stub_calibration()),
        patch(f"{MODULE}._execute_inner", side_effect=_fake_execute_inner_phase1),
        patch(f"{MODULE}._publish_event_sanitized", new_callable=AsyncMock, return_value={}),
        patch(f"{MODULE}._publish_terminal_event_sanitized", new_callable=AsyncMock, return_value={}),
        patch(f"{MODULE}.write_audit_event", new_callable=AsyncMock) as mock_audit,
        patch(f"{MODULE}.clear_cancellation_flag", new_callable=AsyncMock),
    ):
        from app.domains.wealth.workers.construction_run_executor import (
            execute_construction_run,
        )

        await execute_construction_run(
            db,
            portfolio_id=portfolio_id,
            organization_id=org_id,
            requested_by="operator-2",
            job_id="job-def",
            as_of_date=date(2026, 4, 29),
        )

        after = mock_audit.call_args.kwargs["after"]

        # Required fields
        assert after["winning_phase"] == "phase_1_ru_max_return"
        assert after["cascade_summary"] == "phase_1_succeeded"
        assert after["run_status"] == "succeeded"
        assert after["min_achievable_cvar"] == 0.035
        # Q142 pending — None until that PR lands
        assert "cvar_enforcement" in after
        assert after["cvar_enforcement"] is None
        # phase_attempts is a list of phase names (not full dicts)
        assert after["phase_attempts"] == [
            "phase_1_ru_max_return",
            "phase_2_ru_robust",
            "phase_3_min_cvar",
        ]


@pytest.mark.asyncio
async def test_audit_atomic_with_run_row():
    """If write_audit_event raises, the exception propagates — db.flush()
    for the success-path run row never executes, so the caller's session
    transaction rolls back both the run row update and the audit row.

    The audit call sits OUTSIDE the try/except that guards _execute_inner
    (which only catches TimeoutError, RunCancelledError, and generic
    Exception from the inner pipeline). This is intentional: the audit
    event is part of the *finalization* path, not the inner pipeline.
    A failure here propagates to the caller, whose session rollback
    guarantees atomicity (Q126 discipline)."""
    db = _mock_db()
    portfolio_id = uuid.uuid4()
    org_id = uuid.uuid4()
    audit_error = RuntimeError("Simulated audit flush failure")

    with (
        patch(f"{MODULE}._load_calibration", new_callable=AsyncMock, return_value=_stub_calibration()),
        patch(f"{MODULE}._execute_inner", side_effect=_fake_execute_inner_phase1),
        patch(f"{MODULE}._publish_event_sanitized", new_callable=AsyncMock, return_value={}),
        patch(f"{MODULE}._publish_terminal_event_sanitized", new_callable=AsyncMock, return_value={}),
        patch(f"{MODULE}.write_audit_event", new_callable=AsyncMock, side_effect=audit_error),
        patch(f"{MODULE}.clear_cancellation_flag", new_callable=AsyncMock),
    ):
        from app.domains.wealth.workers.construction_run_executor import (
            execute_construction_run,
        )

        # The audit error propagates upward — the success-path flush
        # never fires. The caller's session sees the RuntimeError and
        # rolls back the entire transaction.
        with pytest.raises(RuntimeError, match="Simulated audit flush failure"):
            await execute_construction_run(
                db,
                portfolio_id=portfolio_id,
                organization_id=org_id,
                requested_by="operator-3",
                job_id="job-ghi",
                as_of_date=date(2026, 4, 29),
            )

        # Count the flush calls that DID fire. The success-path flush
        # (the one after write_audit_event) must NOT have been called.
        # Expected flushes:
        #   1. After creating the run row (status='running') — line ~1415
        # The _execute_inner mock doesn't call db.flush directly.
        # The success-path flush (after audit) was blocked by the exception.
        #
        # This proves the run row update and audit event are either both
        # committed or both rolled back by the caller's session.
        assert db.flush.call_count == 1  # only the initial 'running' flush


@pytest.mark.asyncio
async def test_cancelled_run_does_not_emit_audit():
    """Cancelled runs skip the cascade audit event — no decision was made."""
    db = _mock_db()
    portfolio_id = uuid.uuid4()
    org_id = uuid.uuid4()

    with (
        patch(f"{MODULE}._load_calibration", new_callable=AsyncMock, return_value=_stub_calibration()),
        patch(f"{MODULE}._execute_inner", side_effect=_fake_execute_inner_cancelled),
        patch(f"{MODULE}._publish_event_sanitized", new_callable=AsyncMock, return_value={}),
        patch(f"{MODULE}._publish_terminal_event_sanitized", new_callable=AsyncMock, return_value={}),
        patch(f"{MODULE}.write_audit_event", new_callable=AsyncMock) as mock_audit,
        patch(f"{MODULE}.clear_cancellation_flag", new_callable=AsyncMock),
        patch(f"{MODULE}.is_cancellation_requested", new_callable=AsyncMock, return_value=False),
    ):
        from app.domains.wealth.workers.construction_run_executor import (
            execute_construction_run,
        )

        run = await execute_construction_run(
            db,
            portfolio_id=portfolio_id,
            organization_id=org_id,
            requested_by="operator-4",
            job_id="job-jkl",
            as_of_date=date(2026, 4, 29),
        )

        assert run.status == "cancelled"
        # write_audit_event must NOT have been called
        mock_audit.assert_not_called()
