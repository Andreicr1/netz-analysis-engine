"""UnifiedAlert Pydantic schemas — Phase 7 Alerts Unification.

A single shape that bridges the two real alert sources currently in
production:

  1. ``strategy_drift_alerts`` (StrategyDriftAlert) — instrument-level
     drift detection rows written by the ``drift_check`` worker.
     Severity: ``none | moderate | severe`` (drift-specific scale).

  2. ``portfolio_alerts`` (PortfolioAlert, migration 0103) — unified
     portfolio-level feed scaffolded in Phase 2 of the
     portfolio-enterprise-workbench plan. Severity:
     ``info | warning | critical``. Currently empty in production —
     workers landing in a follow-up sprint will populate it.

Per the Phase 7 user mandate the frontend never branches on the
source: every alert flows through this normalized contract. The
aggregator route reads both tables, normalizes severity, computes
human-readable titles, attaches subject linkage, and emits a
unified time-ordered stream.

OD-26 strict empty states apply — when there are no alerts the
aggregator returns ``[]`` rather than fabricating filler rows.
DL15 — read/unread state lives on the source tables
(``acknowledged_at`` is the canonical persistence point on both),
never in localStorage.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Canonical severity scale used by the unified API. The aggregator
# normalizes the source-specific severities into this set.
UnifiedSeverity = Literal["info", "warning", "critical"]

# The two real sources today. Adding a third source (e.g.
# ``screener_fail`` for OD-25 watchlist transitions) is a
# ConfigService-driven extension that lands in a follow-up sprint.
UnifiedAlertSource = Literal["drift", "portfolio"]

# What kind of entity the alert is about. The frontend uses this
# (plus ``subject_id``) to build the drill-through href.
UnifiedSubjectKind = Literal["instrument", "portfolio"]


class UnifiedAlertRead(BaseModel):
    """Single shape returned by ``GET /alerts/inbox``.

    Every field is mandatory unless typed nullable. The frontend
    decoder maps this 1:1 to the ``UnifiedAlert`` TS interface in
    ``frontends/wealth/src/lib/types/alerts.ts``.
    """

    model_config = ConfigDict(extra="ignore")

    #: Stable id from the source row. Combine with ``source`` to
    #: form the canonical key the acknowledge endpoint expects.
    id: uuid.UUID
    source: UnifiedAlertSource

    #: Snake-case alert kind for icon + label routing.
    #: Drift uses ``"drift"``; portfolio_alerts.alert_type passes
    #: through verbatim (``"cvar_breach" | "regime_change" | ...``).
    alert_type: str

    #: Normalized severity. Drift's ``severe → critical``,
    #: ``moderate → warning``, ``none → info``.
    severity: UnifiedSeverity

    #: 1-line headline rendered in the GlobalAlertInbox dropdown.
    title: str

    #: Optional secondary line — usually the subject name + brief
    #: context (e.g. ``"3 of 9 metrics anomalous"``).
    subtitle: str | None = None

    # ── Subject linkage ───────────────────────────────────────
    subject_kind: UnifiedSubjectKind
    subject_id: uuid.UUID
    subject_name: str | None = None

    # ── Read state ────────────────────────────────────────────
    created_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None

    #: Frontend uses this to navigate when the row is clicked.
    #: Computed by the route layer (not stored). Phase 7 lands the
    #: portfolio + universe deep links; the Discovery deep link
    #: requires the instrument_id ↔ external_id bridge that lands
    #: in a follow-up sprint.
    href: str | None = None


class UnifiedAlertInboxResponse(BaseModel):
    """Envelope for ``GET /alerts/inbox``."""

    model_config = ConfigDict(extra="ignore")

    items: list[UnifiedAlertRead] = Field(default_factory=list)
    total: int
    unread_count: int
    #: Per-source counts so the frontend can render diagnostic
    #: tooltips on the bell icon ("3 drift, 1 portfolio").
    by_source: dict[str, int] = Field(default_factory=dict)


class UnifiedAlertAcknowledgeRequest(BaseModel):
    """Body for ``POST /alerts/{source}/{id}/acknowledge``.

    Empty for now — the actor_id comes from the Clerk JWT and the
    timestamp is server-generated. Future expansion (acknowledge
    reason, dismiss-instead-of-acknowledge) drops fields here
    without a path change.
    """

    model_config = ConfigDict(extra="ignore")


class PortfolioAlertCountRead(BaseModel):
    """Response for ``GET /alerts/portfolio/{id}/count``.

    Used by the Phase 5 PortfolioSubNav 'Live' pill badge to surface
    the per-portfolio open-alert count without paginating through
    the full inbox.
    """

    model_config = ConfigDict(extra="ignore")

    portfolio_id: uuid.UUID
    open_count: int
