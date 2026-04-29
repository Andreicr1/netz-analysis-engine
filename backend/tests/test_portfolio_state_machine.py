"""Unit tests for portfolio state machine.

Phase 1 Task 1.2 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

Covers (pure-Python only — no DB required):

- Every valid edge in the ``TRANSITIONS`` adjacency map
- ``compute_allowed_actions`` for each of the 8 states with both
  validation pass/fail and self-approval policy permutations
- The ``InvalidStateTransition`` exception payload
- Soft-block contract: a failing validation does NOT remove the
  ``approve`` action when ``policy.require_construction_for_approve``
  is False (OD-5)
- ``ApprovalPolicy`` defaults are conservative

The DB-write path of the async ``transition()`` function is exercised
end-to-end in Phase 3 Task 3.4 (``construction_run_executor`` worker)
once a real construct flow exists. Project convention (per
``backend/tests/conftest.py``) is to use the real Postgres test DB,
not SQLite — so a unit-level integration test would duplicate the
infrastructure of the Phase 3 worker test without adding signal.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.wealth.models.model_portfolio import PortfolioStateTransition
from vertical_engines.wealth.model_portfolio.state_machine import (
    ACTION_ACTIVATE,
    ACTION_APPROVE,
    ACTION_ARCHIVE,
    ACTION_CONSTRUCT,
    ACTION_PAUSE,
    ACTION_REBUILD_DRAFT,
    ACTION_REJECT,
    ACTION_RESUME,
    ACTION_VALIDATE,
    ALL_ACTIONS,
    TRANSITIONS,
    ApprovalPolicy,
    InvalidStateTransition,
    ValidationStatus,
    compute_allowed_actions,
    transition,
)

# ── TRANSITIONS adjacency map sanity ───────────────────────────────


def test_transitions_covers_8_canonical_states():
    expected = {
        "draft",
        "constructed",
        "validated",
        "approved",
        "live",
        "paused",
        "archived",
        "rejected",
    }
    assert set(TRANSITIONS.keys()) == expected


def test_archived_is_terminal():
    assert TRANSITIONS["archived"] == set()


def test_every_target_state_is_in_transitions_keys():
    """All edge targets must be valid source states (no dangling nodes)."""
    targets = {to for edges in TRANSITIONS.values() for to in edges}
    assert targets.issubset(set(TRANSITIONS.keys()))


@pytest.mark.parametrize(
    ("from_state", "valid_targets"),
    list(TRANSITIONS.items()),
)
def test_each_state_has_documented_edges(from_state, valid_targets):
    """Smoke test: parametrized over the entire adjacency map.

    Just confirms each entry is a set (not a list/tuple/None) and that
    edges are strings — catches typos at import time.
    """
    assert isinstance(valid_targets, set)
    for target in valid_targets:
        assert isinstance(target, str)


# ── compute_allowed_actions — happy paths per state ───────────────


def test_draft_actions():
    actions = compute_allowed_actions("draft")
    assert ACTION_CONSTRUCT in actions
    assert ACTION_ARCHIVE in actions
    assert ACTION_APPROVE not in actions


def test_constructed_actions_with_passing_validation():
    validation = ValidationStatus(has_run=True, passed=True)
    actions = compute_allowed_actions("constructed", validation=validation)
    assert ACTION_VALIDATE in actions
    assert ACTION_APPROVE in actions  # validation passed
    assert ACTION_REJECT in actions
    assert ACTION_REBUILD_DRAFT in actions


def test_constructed_actions_with_failing_validation_default_policy():
    """Default policy gates approve on validation pass."""
    validation = ValidationStatus(has_run=True, passed=False)
    actions = compute_allowed_actions("constructed", validation=validation)
    assert ACTION_APPROVE not in actions
    assert ACTION_REJECT in actions
    assert ACTION_REBUILD_DRAFT in actions


def test_constructed_actions_with_failing_validation_soft_block_policy():
    """OD-5: when policy.require_construction_for_approve=False, approve
    stays visible even on failing validation. The route layer captures
    the override rationale + audit log."""
    validation = ValidationStatus(has_run=True, passed=False)
    policy = ApprovalPolicy(require_construction_for_approve=False)
    actions = compute_allowed_actions(
        "constructed", validation=validation, policy=policy,
    )
    assert ACTION_APPROVE in actions


def test_constructed_actions_no_run_yet_hides_approve():
    actions = compute_allowed_actions(
        "constructed", validation=ValidationStatus(has_run=False, passed=False),
    )
    assert ACTION_APPROVE not in actions
    assert ACTION_VALIDATE in actions  # validate is always available


def test_validated_actions():
    actions = compute_allowed_actions("validated")
    assert ACTION_APPROVE in actions
    assert ACTION_REBUILD_DRAFT in actions
    assert ACTION_ACTIVATE not in actions  # only after approve


def test_approved_actions():
    actions = compute_allowed_actions("approved")
    assert ACTION_ACTIVATE in actions
    assert ACTION_REBUILD_DRAFT in actions
    assert ACTION_PAUSE not in actions  # only after activate (live)


def test_live_actions():
    actions = compute_allowed_actions("live")
    assert ACTION_PAUSE in actions
    assert ACTION_ARCHIVE in actions
    assert ACTION_ACTIVATE not in actions  # already live


def test_paused_actions():
    actions = compute_allowed_actions("paused")
    assert ACTION_RESUME in actions
    assert ACTION_ARCHIVE in actions


def test_rejected_actions():
    actions = compute_allowed_actions("rejected")
    assert ACTION_REBUILD_DRAFT in actions
    assert ACTION_ARCHIVE in actions


def test_archived_is_terminal_actions_empty():
    actions = compute_allowed_actions("archived")
    assert actions == []


def test_unknown_state_returns_empty():
    actions = compute_allowed_actions("not_a_state")
    assert actions == []


@pytest.mark.parametrize(
    "state",
    [
        "draft", "constructed", "validated", "approved",
        "live", "paused", "archived", "rejected",
    ],
)
def test_actions_are_subset_of_all_actions(state):
    """All returned actions must be in :data:`ALL_ACTIONS`."""
    actions = compute_allowed_actions(
        state, validation=ValidationStatus(has_run=True, passed=True),
    )
    assert set(actions).issubset(ALL_ACTIONS)


# ── InvalidStateTransition exception payload ───────────────────────


def test_invalid_state_transition_carries_states():
    exc = InvalidStateTransition(from_state="draft", to_state="live")
    assert exc.from_state == "draft"
    assert exc.to_state == "live"
    assert "draft" in str(exc)
    assert "live" in str(exc)


# ── ApprovalPolicy defaults ────────────────────────────────────────


def test_approval_policy_defaults_are_conservative():
    policy = ApprovalPolicy()
    assert policy.allow_self_approval is False
    assert policy.require_construction_for_approve is True


def test_approval_policy_self_approval_flag_propagates():
    policy = ApprovalPolicy(allow_self_approval=True)
    assert policy.allow_self_approval is True


# ── Edge case: every state has at least one (or zero, for terminal) action ──


def test_every_non_terminal_state_offers_at_least_one_action():
    """Every state except ``archived`` should offer at least one action.

    A portfolio with no actions is a UI dead-end — the only legitimate
    case is the explicit terminal state.
    """
    for state in TRANSITIONS:
        actions = compute_allowed_actions(
            state,
            validation=ValidationStatus(has_run=True, passed=True),
        )
        if state == "archived":
            assert actions == []
        else:
            assert len(actions) > 0, f"state {state!r} has zero actions"


# ── Self-approval flag round-trips through metadata (smoke test) ──


def test_validated_state_actions_under_self_approval_policy():
    """OD-6: self_approval policy doesn't *change* the action set
    (approve is already in the list); it changes whether the route
    accepts the call from a single-actor org and whether the audit row
    flags ``self_approved=true``. The state machine action computer
    should yield the same shape regardless of policy.allow_self_approval."""
    actions_strict = compute_allowed_actions("validated", policy=ApprovalPolicy())
    actions_relaxed = compute_allowed_actions(
        "validated", policy=ApprovalPolicy(allow_self_approval=True),
    )
    assert set(actions_strict) == set(actions_relaxed)


# ── PR-Q115: write_audit_event on transition ──────────────────────


def _mock_db_for_transition(portfolio_id, org_id, from_state="draft"):
    """Build a mocked AsyncSession sufficient for ``transition()``."""
    mock_portfolio = MagicMock()
    mock_portfolio.id = portfolio_id
    mock_portfolio.state = from_state
    mock_portfolio.organization_id = org_id
    mock_portfolio.state_changed_at = datetime(2026, 4, 29, tzinfo=timezone.utc)

    db = AsyncMock()
    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = mock_portfolio
    update_result = MagicMock()
    db.execute = AsyncMock(side_effect=[select_result, update_result])
    db.add = MagicMock()  # Session.add is synchronous
    return db, mock_portfolio


@pytest.mark.asyncio
async def test_transition_writes_audit_event():
    """PR-Q115: transition() must call write_audit_event with correct kwargs."""
    pid = uuid.uuid4()
    org_id = uuid.uuid4()
    db, _ = _mock_db_for_transition(pid, org_id, from_state="draft")

    with patch(
        "vertical_engines.wealth.model_portfolio.state_machine.write_audit_event",
        new_callable=AsyncMock,
    ) as mock_audit:
        await transition(
            db,
            portfolio_id=pid,
            to_state="constructed",
            actor_id="actor_1",
            reason="test reason",
        )

        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["action"] == "model_portfolio.state_transition"
        assert kwargs["entity_type"] == "ModelPortfolio"
        assert kwargs["entity_id"] == str(pid)
        assert kwargs["allow_global"] is False
        assert kwargs["before"] == {"state": "draft"}
        assert kwargs["after"]["state"] == "constructed"
        assert kwargs["after"]["actor_id"] == "actor_1"
        assert kwargs["after"]["reason"] == "test reason"


@pytest.mark.asyncio
async def test_transition_writes_both_domain_and_audit_rows():
    """PR-Q115: Both PortfolioStateTransition AND audit_events row are created."""
    pid = uuid.uuid4()
    org_id = uuid.uuid4()
    db, _ = _mock_db_for_transition(pid, org_id, from_state="draft")

    added_objects: list = []
    db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    with patch(
        "vertical_engines.wealth.model_portfolio.state_machine.write_audit_event",
        new_callable=AsyncMock,
    ) as mock_audit:
        await transition(
            db,
            portfolio_id=pid,
            to_state="constructed",
            actor_id="actor_1",
        )

        # Domain-specific row: PortfolioStateTransition was db.add()-ed
        transition_rows = [
            obj for obj in added_objects
            if isinstance(obj, PortfolioStateTransition)
        ]
        assert len(transition_rows) == 1
        assert transition_rows[0].from_state == "draft"
        assert transition_rows[0].to_state == "constructed"

        # Unified audit: write_audit_event also called
        mock_audit.assert_called_once()
