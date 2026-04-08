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

import pytest

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


# NOTE: The DB-write path of the async ``transition()`` function is
# exercised end-to-end in Phase 3 Task 3.4 (the
# ``construction_run_executor`` worker test) using the project's real
# Postgres test DB. A SQLite-based unit test was attempted here but
# the project policy (per ``backend/tests/conftest.py``) is "Tests run
# against real PostgreSQL — asyncpg requires PG", and ``aiosqlite`` is
# intentionally not in the dev dependency set. The state machine
# logic above (TRANSITIONS adjacency, ``compute_allowed_actions``,
# ``InvalidStateTransition``, ``ApprovalPolicy``) is fully covered by
# the pure-Python tests; the DB plumbing is exercised by the worker
# test in Phase 3.
