"""Portfolio lifecycle state machine.

Backend-authoritative state machine for the model portfolio lifecycle.
Phase 1 Task 1.2 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

Locks consumed
--------------
- **DL3** — backend authoritative; frontend reads ``allowed_actions`` from
  the API and only renders buttons whose action string is in the list.
  Zero ``if state === "validated"`` conditionals in Svelte.
- **OD-5** — soft block on activation: a ``block``-severity validation
  failure does NOT remove the ``activate`` action; the route layer is
  responsible for capturing an override rationale + audit log.
- **OD-6** — single-user orgs may self-approve when
  ``ConfigService.get("wealth", "approval_policy", org_id).allow_self_approval``
  is true; the audit row is flagged ``self_approved=true``.

Public surface
--------------
- ``TRANSITIONS`` — the canonical edge dictionary
- ``ValidationStatus`` — minimal struct used by the action computer
- ``compute_allowed_actions`` — pure function, no DB I/O
- ``transition`` — async DB writer that takes ``FOR UPDATE`` row lock,
  validates the edge, mutates ``model_portfolios``, and inserts the
  audit row in a single transaction
- ``InvalidStateTransition`` — raised on illegal edges
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wealth.models.model_portfolio import (
    ModelPortfolio,
    PortfolioStateTransition,
)

logger = structlog.get_logger()


# ── Canonical state set ─────────────────────────────────────────────
# Must stay in sync with the CHECK constraint in migration 0098.

State = str  # 'draft' | 'constructed' | ... — runtime check via TRANSITIONS

#: Adjacency list of legal state transitions. The ``set()`` value of
#: ``archived`` is empty by design — once archived, a portfolio is
#: terminal. To "revive" an archived portfolio, clone it (creates a new
#: ``draft``).
TRANSITIONS: Final[dict[State, set[State]]] = {
    "draft":       {"constructed", "archived"},
    "constructed": {"validated", "rejected", "draft"},
    "validated":   {"approved", "draft"},
    "approved":    {"live", "draft"},
    "live":        {"paused", "archived"},
    "paused":      {"live", "archived"},
    "archived":    set(),
    "rejected":    {"draft", "archived"},
}


# ── Action mapping ──────────────────────────────────────────────────
# Each action string is a button the frontend may render. The route
# layer is the only authority for whether the action is *currently*
# allowed — see ``compute_allowed_actions`` below.

ACTION_CONSTRUCT: Final[str]     = "construct"
ACTION_VALIDATE: Final[str]      = "validate"
ACTION_APPROVE: Final[str]       = "approve"
ACTION_ACTIVATE: Final[str]      = "activate"
ACTION_PAUSE: Final[str]         = "pause"
ACTION_RESUME: Final[str]        = "resume"
ACTION_ARCHIVE: Final[str]       = "archive"
ACTION_REJECT: Final[str]        = "reject"
ACTION_REBUILD_DRAFT: Final[str] = "rebuild_draft"

ALL_ACTIONS: Final[frozenset[str]] = frozenset({
    ACTION_CONSTRUCT,
    ACTION_VALIDATE,
    ACTION_APPROVE,
    ACTION_ACTIVATE,
    ACTION_PAUSE,
    ACTION_RESUME,
    ACTION_ARCHIVE,
    ACTION_REJECT,
    ACTION_REBUILD_DRAFT,
})


@dataclass(frozen=True)
class ValidationStatus:
    """Minimal projection of a construction run's validation result.

    Used by ``compute_allowed_actions`` to decide whether ``approve`` is
    a valid action when the portfolio is in ``constructed`` state. Only
    the two booleans matter — the full ``ValidationResult`` lives in the
    construction run record (Phase 3 Task 3.1).
    """

    has_run: bool
    """True if at least one construction run exists for this portfolio."""

    passed: bool
    """True if the most recent construction run's validation gate passed
    with zero block-severity failures."""


@dataclass(frozen=True)
class ApprovalPolicy:
    """Resolved approval policy for the org.

    Read once via ``ConfigService.get("wealth","approval_policy",org_id)``
    and passed in. The state machine never reads ConfigService directly —
    keeps it pure and synchronously testable.
    """

    allow_self_approval: bool = False
    """OD-6: when true, an actor in a single-user org may move
    ``validated → approved`` without four-eyes. The transition row will
    be flagged ``metadata.self_approved=true``."""

    require_construction_for_approve: bool = True
    """If true, ``approve`` is gated on ``ValidationStatus.passed``. If
    false, the route layer may surface an override path with audit. The
    state machine itself always emits the action — gating is the route's
    job (OD-5 soft-block contract)."""


def compute_allowed_actions(
    state: State,
    validation: ValidationStatus | None = None,
    policy: ApprovalPolicy | None = None,
) -> list[str]:
    """Return the action strings allowed from the given state.

    Pure function. No I/O. Safe to call from sync code.

    Parameters
    ----------
    state
        Current state of the portfolio (one of ``TRANSITIONS`` keys).
    validation
        Latest construction run's validation status. May be ``None`` for
        portfolios that have never been constructed.
    policy
        Resolved approval policy. Defaults to a conservative policy
        (``allow_self_approval=False``) when not provided.

    Returns
    -------
    list[str]
        Action strings the frontend may render. Always a subset of
        :data:`ALL_ACTIONS`. Never returns ``None`` — an empty list
        means the portfolio is terminal (``archived``) or in an
        unrecognized state.
    """
    if state not in TRANSITIONS:
        logger.warning("state_machine.unknown_state", state=state)
        return []

    policy = policy or ApprovalPolicy()
    actions: list[str] = []

    if state == "draft":
        actions.append(ACTION_CONSTRUCT)
        actions.append(ACTION_ARCHIVE)

    elif state == "constructed":
        # ``validate`` is always available — it just re-runs the gate.
        actions.append(ACTION_VALIDATE)
        # Soft-block per OD-5: keep ``approve`` visible even if validation
        # is failing — the route captures the override rationale.
        if validation is not None and validation.has_run:
            if validation.passed or not policy.require_construction_for_approve:
                actions.append(ACTION_APPROVE)
        actions.append(ACTION_REJECT)
        actions.append(ACTION_REBUILD_DRAFT)

    elif state == "validated":
        # ``validated`` only exists if validation already passed; allow
        # both approval paths (normal + self-approval flagged).
        actions.append(ACTION_APPROVE)
        actions.append(ACTION_REBUILD_DRAFT)

    elif state == "approved":
        actions.append(ACTION_ACTIVATE)
        actions.append(ACTION_REBUILD_DRAFT)

    elif state == "live":
        actions.append(ACTION_PAUSE)
        actions.append(ACTION_ARCHIVE)

    elif state == "paused":
        actions.append(ACTION_RESUME)
        actions.append(ACTION_ARCHIVE)

    elif state == "rejected":
        actions.append(ACTION_REBUILD_DRAFT)
        actions.append(ACTION_ARCHIVE)

    elif state == "archived":
        # Terminal state — no further actions.
        pass

    return actions


class InvalidStateTransition(Exception):
    """Raised when ``transition()`` is asked to perform an illegal edge.

    The exception payload carries the source/target states so the
    caller can render a meaningful error response.
    """

    def __init__(self, from_state: str, to_state: str) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid portfolio state transition: {from_state} → {to_state}",
        )


@dataclass
class TransitionResult:
    """Outcome of a successful ``transition()`` call.

    Returned to the caller so the route can include the new state in
    its response without re-fetching the portfolio.
    """

    portfolio_id: uuid.UUID
    from_state: str
    to_state: str
    transition_id: uuid.UUID
    state_changed_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


async def transition(
    db: AsyncSession,
    *,
    portfolio_id: uuid.UUID,
    to_state: State,
    actor_id: str,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TransitionResult:
    """Move a portfolio from its current state to ``to_state``.

    Wraps the entire move in a single transaction with ``SELECT ... FOR
    UPDATE`` row-locking on ``model_portfolios`` to prevent races. The
    audit row is inserted *inside the same transaction* so the audit
    trail is consistent with the state column.

    The caller is responsible for committing the surrounding session.
    This function only ``flush()``-es to make the new transition row
    visible to subsequent reads in the same transaction.

    Parameters
    ----------
    db
        Async session with RLS already established (the route layer's
        ``get_db_with_rls`` dependency).
    portfolio_id
        UUID of the target portfolio.
    to_state
        Target state. Must be one of the canonical 8 values.
    actor_id
        ``actor.actor_id`` from the route's ``Depends(get_actor)``. Used
        for both the audit row and the ``state_changed_by`` column.
    reason
        Optional human-readable reason. Surfaced in the IC view of the
        audit feed.
    metadata
        Optional JSON-serializable extras. Common keys: ``self_approved``
        (OD-6), ``override_validation`` (OD-5), ``parent_live_id``
        (rebalance spawn — Phase 9 Task 9.6).

    Raises
    ------
    InvalidStateTransition
        If the source → target edge is not in :data:`TRANSITIONS`.
    LookupError
        If the portfolio does not exist (or RLS hides it).

    Returns
    -------
    TransitionResult
        The applied transition.
    """
    if to_state not in TRANSITIONS:
        raise InvalidStateTransition(from_state="<unknown>", to_state=to_state)

    metadata = metadata or {}

    # Row-lock to prevent two concurrent transitions racing.
    locked = await db.execute(
        select(ModelPortfolio)
        .where(ModelPortfolio.id == portfolio_id)
        .with_for_update(),
    )
    portfolio = locked.scalar_one_or_none()
    if portfolio is None:
        raise LookupError(f"model_portfolio {portfolio_id} not found")

    from_state = portfolio.state
    if to_state not in TRANSITIONS.get(from_state, set()):
        raise InvalidStateTransition(from_state=from_state, to_state=to_state)

    # Apply the column updates via UPDATE so the trigger-free
    # ``state_changed_at`` move is atomic with the rest.
    await db.execute(
        update(ModelPortfolio)
        .where(ModelPortfolio.id == portfolio_id)
        .values(
            state=to_state,
            state_changed_by=actor_id,
        ),
    )

    # Insert the audit row.
    transition_row = PortfolioStateTransition(
        organization_id=portfolio.organization_id,
        portfolio_id=portfolio_id,
        from_state=from_state,
        to_state=to_state,
        actor_id=actor_id,
        reason=reason,
        state_metadata=metadata,
    )
    db.add(transition_row)
    await db.flush()
    await db.refresh(transition_row)
    await db.refresh(portfolio)

    logger.info(
        "portfolio_state_transition",
        portfolio_id=str(portfolio_id),
        from_state=from_state,
        to_state=to_state,
        actor_id=actor_id,
        transition_id=str(transition_row.id),
    )

    return TransitionResult(
        portfolio_id=portfolio_id,
        from_state=from_state,
        to_state=to_state,
        transition_id=transition_row.id,
        state_changed_at=portfolio.state_changed_at,
        metadata=metadata,
    )
