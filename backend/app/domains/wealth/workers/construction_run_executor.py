"""Construction run executor — wraps the enriched /construct pipeline.

Phase 3 Task 3.4 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

Responsibilities
----------------
1. Load the portfolio and its ``portfolio_calibration`` row
2. Create a ``portfolio_construction_runs`` row with ``status='running'``
3. Acquire the ``900_101`` advisory lock for the portfolio (single-flight)
4. Call ``_run_construction_async`` to get the optimizer output
5. Run the 4 preset stress scenarios via ``PRESET_SCENARIOS`` — persist to ``portfolio_stress_results``
6. Run the ``construction_advisor`` IF ``calibration.advisor_enabled`` (Task 3.3 fold-in)
7. Run the 15-check ``validation_gate``
8. Render the deterministic Jinja2 narrative
9. Update the run row with ``status='succeeded'|'failed'``, populate all
   enrichment columns, and compute ``wall_clock_ms``
10. Publish SSE events via ``publish_event()`` so the Job-or-Stream route
    can bridge to the frontend

Stability guardrails (DL18)
---------------------------
- **P1 Bounded** — 120s hard wall-clock timeout via ``asyncio.wait_for``
- **P2 Batched** — the advisor and stress scenarios run sequentially
  inside the bound; batching across portfolios is not applicable
- **P3 Isolated** — all writes use the RLS-aware session from the caller
- **P4 Lifecycle** — status enum tracks ``running → succeeded|failed``
- **P5 Idempotent** — Redis single-flight lock on
  ``construct:v1:{portfolio_id}:{calibration_hash}``; same key inside 1h
  returns the cached ``run_id`` without re-running
- **P6 Fault-Tolerant** — any step that raises is captured in
  ``optimizer_trace.error``, the run is marked ``failed``, the lock is
  released in ``finally``

Worker lock (DL19)
------------------
Uses ``pg_try_advisory_xact_lock(900_101, portfolio_int)`` with an
integer literal lock ID (never ``hash()``). The second arg is derived
via ``zlib.crc32`` on the portfolio UUID so concurrent runs for
different portfolios don't block each other.

Public surface
--------------
- ``execute_construction_run`` — main entry point (async)
- ``compute_cache_key`` — pure helper for the Redis single-flight key
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
import zlib
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jobs.tracker import (
    clear_cancellation_flag,
    is_cancellation_requested,
    publish_event,
    publish_terminal_event,
)
from app.domains.wealth.models.model_portfolio import (
    ModelPortfolio,
    PortfolioCalibration,
    PortfolioConstructionRun,
    PortfolioStressResult,
)
from app.domains.wealth.schemas.sanitized import (
    WinnerSignal,
    build_operator_message,
    compute_winner_signal,
    humanize_event_type,
    sanitize_payload,
)
from quant_engine.allocation_template_service import (
    TemplateReport,
    build_template_operator_message,
    validate_template_completeness,
)
from quant_engine.block_coverage_service import (
    CoverageReport,
    build_coverage_operator_message,
    validate_block_coverage,
)
from vertical_engines.wealth.model_portfolio.narrative_templater import (
    render_narrative,
)
from vertical_engines.wealth.model_portfolio.stress_scenarios import (
    PRESET_SCENARIOS,
    run_stress_scenario,
)
from vertical_engines.wealth.model_portfolio.validation_gate import (
    ValidationDbContext,
    to_jsonb,
    validate_construction,
)

logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────


#: DL19 — integer literal advisory lock ID reserved for this worker.
LOCK_ID: int = 900_101

#: DL18 P1 — hard wall-clock timeout for a construction run.
CONSTRUCTION_TIMEOUT_SECONDS: float = 120.0


class RunCancelledError(Exception):
    """Raised internally when a cooperative cancellation flag is observed.

    Bubbles out of ``_execute_inner`` to the top-level exception handler
    in ``execute_construction_run``, which marks the run as ``cancelled``
    and emits the terminal event. Not part of the public surface — the
    runner catches it before returning to the caller.
    """

    def __init__(self, phase: str) -> None:
        super().__init__(f"construction cancelled at phase {phase}")
        self.phase = phase


class CoverageInsufficientError(Exception):
    """PR-A22 — raised when block coverage validation fails pre-optimizer.

    Carries the full :class:`CoverageReport` so the top-level handler
    can persist it into ``cascade_telemetry`` and emit a structured SSE
    event. The optimizer is never invoked when this exception bubbles.
    """

    def __init__(self, report: CoverageReport) -> None:
        super().__init__(
            f"block_coverage_insufficient gaps={len(report.gaps)} "
            f"weight_at_risk={report.total_target_weight_at_risk:.4f}"
        )
        self.report = report


class TemplateIncompleteError(Exception):
    """PR-A25 — raised when the canonical template is incomplete.

    Fires strictly before ``CoverageInsufficientError`` so operators
    see the structural defect (missing canonical block rows) rather
    than the downstream coverage gap it would otherwise manifest as.
    """

    def __init__(self, report: TemplateReport) -> None:
        super().__init__(
            "template_incomplete missing="
            f"{len(report.missing_canonical_blocks)}"
        )
        self.report = report


class NoApprovedAllocationError(Exception):
    """PR-A26.2 Section E — realize-mode requires an approved Strategic IPS.

    Raised pre-optimizer when any canonical ``strategic_allocation`` row
    for the ``(organization_id, profile)`` pair has ``approved_at IS
    NULL``. The operator remedy is to run the propose → approve cycle
    before realizing any portfolio.
    """

    def __init__(
        self, *, organization_id: uuid.UUID, profile: str,
        approved_count: int, total_count: int,
    ) -> None:
        super().__init__(
            f"no_approved_allocation profile={profile!r} "
            f"approved={approved_count}/{total_count}"
        )
        self.organization_id = organization_id
        self.profile = profile
        self.approved_count = approved_count
        self.total_count = total_count


class InstrumentConcentrationBreachError(Exception):
    """PR-A26.2 Section F — realize composition breached the 15% per-instrument cap.

    The block's realized weight ``w_b`` would require at least
    ``ceil(w_b / 0.15)`` approved instruments to distribute under the
    hard 15% ceiling. Operator remedy: approve more instruments for
    the breaching block or accept a lower block weight.
    """

    def __init__(
        self, *, block_id: str, block_weight: float,
        required: int, available: int,
    ) -> None:
        super().__init__(
            f"instrument_concentration_breach block={block_id} "
            f"block_weight={block_weight:.4f} required={required} "
            f"available={available}"
        )
        self.block_id = block_id
        self.block_weight = block_weight
        self.required = required
        self.available = available


# ── Helpers ────────────────────────────────────────────────────


def compute_cache_key(
    portfolio_id: uuid.UUID | str,
    calibration_snapshot: dict[str, Any],
    as_of_date: date,
) -> str:
    """Deterministic SHA-256 cache key for a construction run.

    Per quant §B.4: same calibration + same date = same run (up to
    the universe fingerprint, which varies per org). Callers pass
    the calibration JSON verbatim; the hash is stable across
    re-runs.
    """
    payload = json.dumps(
        {
            "pid": str(portfolio_id),
            "as_of": as_of_date.isoformat(),
            "calibration": calibration_snapshot,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _portfolio_lock_key(portfolio_id: uuid.UUID | str) -> int:
    """Derive a stable 32-bit lock partition key for a portfolio UUID."""
    return zlib.crc32(str(portfolio_id).encode("utf-8")) & 0x7FFFFFFF


async def _check_cancellation(job_id: str | None, phase: str) -> None:
    """Raise ``RunCancelledError`` if the cooperative cancel flag is set.

    Called at phase boundaries inside ``_execute_inner``. When no
    ``job_id`` is attached (synchronous caller path), cancellation is
    unsupported and this is a no-op — only async/SSE runs can be
    cancelled.
    """
    if not job_id:
        return
    if await is_cancellation_requested(job_id):
        raise RunCancelledError(phase)


async def _publish_event_sanitized(
    db: AsyncSession,
    *,
    run_id: uuid.UUID,
    job_id: str | None,
    raw_type: str,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit a sanitised SSE event AND append it to ``event_log``.

    Two side effects:

    1. Publishes to the Redis SSE channel (same bus as the raw
       ``publish_event``) with the raw event type mapped to an
       institutional label via ``EVENT_TYPE_LABELS`` and the payload
       walked through ``sanitize_payload`` so jargon keys and regime
       enums are translated at the wire boundary.
    2. Appends a structured ``{seq, type, raw_type, ts, payload}``
       entry to ``portfolio_construction_runs.event_log`` so late
       subscribers (Phase 4 Builder analytics replay) can reconstruct
       the run history from the column without needing access to the
       live SSE stream.

    Returns the sanitised event dict for unit-test inspection.
    """
    raw_payload = raw_payload or {}
    public_type = humanize_event_type(raw_type)
    public_payload = sanitize_payload(raw_payload)

    event: dict[str, Any] = {
        "type": public_type,
        "raw_type": raw_type,
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "payload": public_payload,
    }

    # Side effect 1 — SSE bus (only when a job is attached)
    if job_id:
        await publish_event(job_id, public_type, public_payload)

    # Side effect 2 — DB append to event_log, assigning the next seq
    # atomically via jsonb_array_length so concurrent appends remain
    # strictly ordered. The UPDATE uses the run's server-side array
    # length + 1 so callers don't need to track a counter.
    await db.execute(
        text(
            """
            UPDATE portfolio_construction_runs
            SET event_log = event_log || jsonb_build_array(
                jsonb_build_object(
                    'seq', COALESCE(jsonb_array_length(event_log), 0),
                    'type', CAST(:public_type AS text),
                    'raw_type', CAST(:raw_type AS text),
                    'ts', CAST(:ts AS text),
                    'payload', CAST(:payload AS jsonb)
                )
            )
            WHERE id = :run_id
            """,
        ),
        {
            "run_id": run_id,
            "public_type": public_type,
            "raw_type": raw_type,
            "ts": event["ts"],
            "payload": json.dumps(public_payload),
        },
    )
    return event


async def _publish_terminal_event_sanitized(
    db: AsyncSession,
    *,
    run_id: uuid.UUID,
    job_id: str | None,
    raw_type: str,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Terminal variant — same sanitisation, then clear the ownership key.

    ``publish_terminal_event`` differs from ``publish_event`` only in
    that it additionally schedules cleanup of the job ownership key,
    so late-reconnecting clients can still pick up the final event.
    """
    raw_payload = raw_payload or {}
    public_type = humanize_event_type(raw_type)
    public_payload = sanitize_payload(raw_payload)

    event: dict[str, Any] = {
        "type": public_type,
        "raw_type": raw_type,
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "payload": public_payload,
    }

    if job_id:
        await publish_terminal_event(job_id, public_type, public_payload)

    await db.execute(
        text(
            """
            UPDATE portfolio_construction_runs
            SET event_log = event_log || jsonb_build_array(
                jsonb_build_object(
                    'seq', COALESCE(jsonb_array_length(event_log), 0),
                    'type', CAST(:public_type AS text),
                    'raw_type', CAST(:raw_type AS text),
                    'ts', CAST(:ts AS text),
                    'payload', CAST(:payload AS jsonb)
                )
            )
            WHERE id = :run_id
            """,
        ),
        {
            "run_id": run_id,
            "public_type": public_type,
            "raw_type": raw_type,
            "ts": event["ts"],
            "payload": json.dumps(public_payload),
        },
    )
    return event


# ── Per-phase cascade events ─────────────────────────────────────

# PR-A12 — RU LP cascade. Three phases only; variance-capped + min-variance
# + heuristic-fallback paths retired. Labels stay operator-vocabulary.
_CASCADE_PHASES: list[tuple[str, str]] = [
    ("phase_1_ru_max_return", "Max Return (CVaR-bounded)"),
    ("phase_2_ru_robust", "Robust Max Return"),
    ("phase_3_min_cvar", "Min Tail Risk"),
]

# Map optimizer result status → index of the winning phase (0-based).
# PR-A12: "optimal" covers Phase 1/2/3 success; "degraded" = Phase 3 above
# limit (universe floor binds); "constraint_polytope_empty" = upstream
# configuration error (block bands unsatisfiable).
_STATUS_TO_WINNING_PHASE: dict[str, int] = {
    "optimal": 2,                           # winner index resolved from winning_phase below
    "degraded": 2,                          # Phase 3 above-limit
    "constraint_polytope_empty": 2,         # no feasible polytope
}


# ── PR-A11/A12 — cascade telemetry builder ──────────────────────────

# Normalized public phase keys — match the optimizer's internal keys 1:1
# (PR-A12 renames the optimizer so the remap is a no-op). Kept as a dict
# for forward-compat if we ever want to decouple internal from external
# naming again.
_CASCADE_PHASE_ORDER_PUBLIC: tuple[str, ...] = (
    "phase_1_ru_max_return",
    "phase_2_ru_robust",
    "phase_3_min_cvar",
)

_PHASE_PUBLIC_KEY: dict[str, str] = {
    "phase_1_ru_max_return": "phase_1_ru_max_return",
    "phase_2_ru_robust": "phase_2_ru_robust",
    "phase_3_min_cvar": "phase_3_min_cvar",
    "upstream_heuristic": "upstream_heuristic",
}

# run.status derived from cascade outcome.
# - Phase 1/2 win → succeeded
# - Phase 3 winner WITHIN cvar_limit → succeeded (rare — Phase 1 usually
#   wins whenever the universe supports it)
# - Phase 3 winner ABOVE cvar_limit → degraded (universe floor binds)
# - Upstream heuristic (compute_fund_level_inputs failed before cascade) → degraded
# - Constraint polytope empty (block bands sum > 1) → failed
_STATUS_BY_SUMMARY: dict[str, str] = {
    "phase_1_succeeded": "succeeded",
    "phase_2_robust_succeeded": "succeeded",
    "phase_3_min_cvar_within_limit": "succeeded",
    "phase_3_min_cvar_above_limit": "degraded",
    "upstream_heuristic": "degraded",
    "constraint_polytope_empty": "failed",
}

# NOTE: final summary also depends on cvar_within_limit when winning_phase
# is phase_3_min_cvar — resolved inside ``_build_cascade_telemetry``. This
# table handles the non-conditional cases.
_SUMMARY_BY_WINNING_PHASE: dict[str, str] = {
    "phase_1_ru_max_return": "phase_1_succeeded",
    "phase_2_ru_robust": "phase_2_robust_succeeded",
    "upstream_heuristic": "upstream_heuristic",
}


def _build_cascade_telemetry(
    *,
    cascade_block: dict[str, Any] | None,
    optimizer_trace: dict[str, Any],
    cvar_limit: float | None,
) -> tuple[dict[str, Any], str]:
    """Build the persisted cascade_telemetry payload + derived run status.

    Parameters
    ----------
    cascade_block
        ``{"phase_attempts": [...], "winning_phase": str|None}`` from
        ``_run_construction_async``. Skipped phases are present.
    optimizer_trace
        ``run.optimizer_trace`` (for the terminal status / error fallback).
    cvar_limit
        Configured CVaR limit (informational — not required to derive
        summary / operator_signal).

    Returns
    -------
    (telemetry_dict, run_status)
        ``telemetry_dict`` matches the shape in PR-A11 Section A.2.
        ``run_status`` is one of ``succeeded|degraded|failed``.
    """
    block = cascade_block or {}
    raw_attempts: list[dict[str, Any]] = list(block.get("phase_attempts") or [])
    winning_phase = block.get("winning_phase")
    min_achievable_cvar = block.get("min_achievable_cvar")
    achievable_return_band = block.get("achievable_return_band")
    # PR-A14 — universe coverage surface (routes/model_portfolios.py
    # ``coverage_payload``). None on legacy/test paths that didn't emit it.
    raw_coverage = block.get("coverage")
    coverage: dict[str, Any] | None = (
        dict(raw_coverage) if isinstance(raw_coverage, dict) else None
    )

    # Legacy/test path: no cascade info at all → return empty telemetry
    # with a sentinel status so the caller falls back to the solver-string
    # check (preserves pre-PR-A11 behavior for mocked _run_construction_async
    # results that don't emit the ``cascade`` block).
    if not raw_attempts and winning_phase is None:
        return {}, "unknown"

    # Normalize each attempt's phase key to the public naming, pad missing
    # cascade slots with ``skipped`` so ``len(phase_attempts) >= 3`` always.
    public_attempts: list[dict[str, Any]] = []
    seen_public: set[str] = set()
    for att in raw_attempts:
        phase_raw = str(att.get("phase") or "")
        phase_public = _PHASE_PUBLIC_KEY.get(phase_raw, phase_raw)
        public_attempts.append({
            "phase": phase_public,
            "status": att.get("status"),
            "solver": att.get("solver"),
            "objective_value": att.get("objective_value"),
            "wall_ms": att.get("wall_ms") or 0,
            "infeasibility_reason": att.get("infeasibility_reason"),
            "cvar_at_solution": att.get("cvar_at_solution"),
            "cvar_at_solution_cf": att.get("cvar_at_solution_cf"),
            "cvar_limit_effective": att.get("cvar_limit_effective"),
            "cvar_within_limit": att.get("cvar_within_limit"),
            "kappa_used": att.get("kappa_used"),
        })
        seen_public.add(phase_public)
    for phase_public in _CASCADE_PHASE_ORDER_PUBLIC:
        if phase_public not in seen_public:
            public_attempts.append({
                "phase": phase_public, "status": "skipped", "solver": None,
                "objective_value": None, "wall_ms": 0,
                "infeasibility_reason": None,
                "cvar_at_solution": None, "cvar_at_solution_cf": None,
                "cvar_limit_effective": None,
                "cvar_within_limit": None,
                "kappa_used": None,
            })

    # Order attempts canonically (3 RU phases + optional upstream_heuristic last)
    order_lookup = {
        p: i for i, p in enumerate(_CASCADE_PHASE_ORDER_PUBLIC)
    }
    public_attempts.sort(
        key=lambda a: order_lookup.get(a["phase"], len(_CASCADE_PHASE_ORDER_PUBLIC)),
    )

    # Resolve cascade_summary. Phase 3 needs within-limit check to pick
    # the right enum; Phase 1/2/upstream use the direct mapping.
    if winning_phase == "phase_3_min_cvar":
        phase3_attempt = next(
            (a for a in public_attempts if a["phase"] == "phase_3_min_cvar"),
            None,
        )
        within_limit = bool(phase3_attempt and phase3_attempt.get("cvar_within_limit"))
        cascade_summary = (
            "phase_3_min_cvar_within_limit" if within_limit
            else "phase_3_min_cvar_above_limit"
        )
    else:
        cascade_summary = _SUMMARY_BY_WINNING_PHASE.get(
            winning_phase or "", "constraint_polytope_empty",
        )
    run_status = _STATUS_BY_SUMMARY.get(cascade_summary, "failed")

    # Operator signal — sanitized, translated by PR-A10/A13 frontend copy.
    operator_signal: dict[str, Any] | None
    if cascade_summary in (
        "phase_1_succeeded",
        "phase_2_robust_succeeded",
        "phase_3_min_cvar_within_limit",
    ):
        operator_signal = None
    elif cascade_summary == "phase_3_min_cvar_above_limit":
        # Tail-risk floor binds — universe cannot hit operator's CVaR limit.
        operator_signal = {
            "kind": "cvar_limit_below_universe_floor",
            "binding": "tail_risk_floor",
            "message_key": "cvar_limit_below_universe_floor",
            "min_achievable_cvar": min_achievable_cvar,
            "user_cvar_limit": cvar_limit,
        }
    elif cascade_summary == "upstream_heuristic":
        # compute_fund_level_inputs raised before cascade ran (e.g.
        # ill-conditioned Σ, too few funds with NAV data).
        # PR-A14 — swap primary kind when the heuristic fired because the
        # approved universe fell below the 20% coverage floor, so operators
        # see "import funds into the missing blocks" instead of a generic
        # "statistics unavailable" message.
        if coverage and bool(coverage.get("hard_fail")):
            operator_signal = {
                "kind": "universe_coverage_insufficient",
                "binding": "universe_coverage",
                "message_key": "universe_coverage_hard_fail",
                "pct_covered": coverage.get("pct_covered"),
                "missing_blocks_count": len(coverage.get("missing_blocks") or []),
            }
        else:
            operator_signal = {
                "kind": "upstream_data_missing",
                "binding": "returns_quality",
                "message_key": "statistical_inputs_unavailable",
            }
    else:  # constraint_polytope_empty
        operator_signal = {
            "kind": "constraint_polytope_empty",
            "binding": "block_bands",
            "message_key": "block_bands_unsatisfiable",
        }

    # PR-A14 — secondary operator_signal: non-blocking warning when the
    # approved universe covers < 85% of the profile's strategic allocation
    # targets. Additive field; primary keeps its existing contract so
    # frontend callers that only look at ``kind`` continue to work.
    if (
        coverage is not None
        and coverage.get("pct_covered") is not None
        and float(coverage["pct_covered"]) < 0.85
        # Hard-fail already surfaces as primary kind — don't duplicate.
        and not (operator_signal and operator_signal.get("kind") == "universe_coverage_insufficient")
    ):
        secondary = {
            "kind": "universe_coverage_insufficient",
            "binding": "universe_coverage",
            "message_key": "expand_universe_recommended",
            "pct_covered": coverage.get("pct_covered"),
            "missing_blocks_count": len(coverage.get("missing_blocks") or []),
        }
        if operator_signal is None:
            # Primary was "implicit feasible" (e.g. phase_1_succeeded).
            # Synthesise a feasible primary so consumers always find the
            # secondary under operator_signal.secondary.
            operator_signal = {
                "kind": "feasible",
                "binding": None,
                "message_key": "feasible",
                "secondary": secondary,
            }
        else:
            operator_signal = {**operator_signal, "secondary": secondary}

    # ── PR-A19.1 Section C — cascade-aware operator signal ────────────
    # Additive; legacy ``operator_signal`` and ``cascade_summary`` keep
    # their existing contracts. ``winner_signal`` distinguishes "Phase 1
    # optimal" from "Phase 3 min-CVaR fallback because CVaR target
    # infeasible" so the frontend can render the right operator_message
    # verbatim (smart-backend / dumb-frontend).
    phase3_attempt = next(
        (a for a in public_attempts if a["phase"] == "phase_3_min_cvar"),
        None,
    )
    _cvar_within_limit = (
        bool(phase3_attempt.get("cvar_within_limit"))
        if phase3_attempt is not None else False
    )
    winner_signal_enum = compute_winner_signal(
        winning_phase=winning_phase,
        cvar_within_limit=_cvar_within_limit,
        cvar_limit=cvar_limit,
        min_achievable_cvar=min_achievable_cvar,
    )
    # Winner's delivered expected return — for phase_1/phase_2 it's the
    # winning attempt's objective_value; for phase_3 it's the lower band
    # edge (phase_3 objective is min-CVaR, not return).
    _winner_expected_return: float | None = None
    if winning_phase == "phase_3_min_cvar" and achievable_return_band is not None:
        _winner_expected_return = achievable_return_band.get("lower")
    else:
        winner_attempt = next(
            (a for a in public_attempts if a["phase"] == winning_phase),
            None,
        )
        if winner_attempt is not None:
            _winner_expected_return = winner_attempt.get("objective_value")
    operator_message = build_operator_message(
        signal=winner_signal_enum,
        cvar_limit=cvar_limit,
        min_achievable_cvar=min_achievable_cvar,
        expected_return=_winner_expected_return,
    )

    telemetry = {
        "phase_attempts": public_attempts,
        "cascade_summary": cascade_summary,
        "min_achievable_cvar": min_achievable_cvar,
        "achievable_return_band": achievable_return_band,
        "operator_signal": operator_signal,
        # PR-A14 — universe coverage JSONB (nullable for legacy runs).
        "coverage": coverage,
        # PR-A19.1 Section C — cascade-aware operator signal (additive).
        "winner_signal": winner_signal_enum.value,
        "operator_message": operator_message,
    }
    return telemetry, run_status


async def _emit_cascade_phase_events(
    db: AsyncSession,
    *,
    run_id: uuid.UUID,
    job_id: str | None,
    winning_phase: str | None,
    objective_value: float | None,
) -> None:
    """Emit retrospective per-phase optimizer events for the cascade timeline.

    PR-A12 — uses the cascade's ``winning_phase`` directly (set by the RU
    cascade) instead of inferring from solver status strings. Phase 3
    ALWAYS runs (for the achievable band) so it is always ``succeeded``;
    earlier phases that weren't the winner are ``failed`` or ``skipped``
    depending on position.
    """
    winning_idx: int | None = None
    for i, (pk, _) in enumerate(_CASCADE_PHASES):
        if pk == winning_phase:
            winning_idx = i
            break

    total_failure = winning_idx is None and winning_phase is None
    # Phase 3 always runs → always succeeded unless the whole cascade
    # failed upstream (polytope empty etc).
    phase_3_idx = next(
        (i for i, (pk, _) in enumerate(_CASCADE_PHASES) if pk == "phase_3_min_cvar"),
        len(_CASCADE_PHASES) - 1,
    )

    for idx, (phase_key, phase_label) in enumerate(_CASCADE_PHASES):
        if total_failure:
            status = "failed"
        elif idx == winning_idx:
            status = "succeeded"
        elif idx == phase_3_idx:
            # Always-run telemetry phase.
            status = "succeeded"
        elif winning_idx is not None and idx < winning_idx:
            status = "failed"
        else:
            status = "skipped"

        await _publish_event_sanitized(
            db,
            run_id=run_id,
            job_id=job_id,
            raw_type="optimizer_phase_complete",
            raw_payload={
                "phase": phase_key,
                "phase_label": phase_label,
                "status": status,
                "objective_value": objective_value if status == "succeeded" else None,
            },
        )


async def _acquire_advisory_lock(
    db: AsyncSession, portfolio_id: uuid.UUID | str,
) -> bool:
    """Acquire the transaction-scoped advisory lock for this portfolio.

    Returns True if acquired, False if another construct is already
    running for the same portfolio. The lock auto-releases at
    transaction commit/rollback.
    """
    result = await db.execute(
        text("SELECT pg_try_advisory_xact_lock(:cls, :obj)"),
        {"cls": LOCK_ID, "obj": _portfolio_lock_key(portfolio_id)},
    )
    return bool(result.scalar())


def _serialize_calibration(cal: PortfolioCalibration) -> dict[str, Any]:
    """Snapshot the calibration row into a JSON-safe dict for the run."""
    return {
        "schema_version": cal.schema_version,
        "mandate": cal.mandate,
        "cvar_limit": float(cal.cvar_limit),
        "max_single_fund_weight": float(cal.max_single_fund_weight),
        "turnover_cap": float(cal.turnover_cap) if cal.turnover_cap is not None else None,
        "stress_scenarios_active": list(cal.stress_scenarios_active),
        "regime_override": cal.regime_override,
        "bl_enabled": cal.bl_enabled,
        "bl_view_confidence_default": float(cal.bl_view_confidence_default),
        "garch_enabled": cal.garch_enabled,
        "turnover_lambda": float(cal.turnover_lambda) if cal.turnover_lambda is not None else None,
        "stress_severity_multiplier": float(cal.stress_severity_multiplier),
        "advisor_enabled": cal.advisor_enabled,
        "cvar_level": float(cal.cvar_level),
        "lambda_risk_aversion": float(cal.lambda_risk_aversion) if cal.lambda_risk_aversion is not None else None,
        "shrinkage_intensity_override": float(cal.shrinkage_intensity_override) if cal.shrinkage_intensity_override is not None else None,
        "expert_overrides": dict(cal.expert_overrides),
    }


def _load_default_calibration(portfolio_id: uuid.UUID) -> dict[str, Any]:
    """Fallback when no calibration row exists for this portfolio.

    Matches the DB defaults from migration 0100 so the first
    /construct call on a fresh portfolio still has a well-formed
    calibration snapshot.
    """
    return {
        "schema_version": 1,
        "mandate": "balanced",
        "cvar_limit": 0.05,
        "max_single_fund_weight": 0.10,
        "turnover_cap": None,
        "stress_scenarios_active": [
            "gfc_2008", "covid_2020", "taper_2013", "rate_shock_200bps",
        ],
        "regime_override": None,
        "bl_enabled": True,
        "bl_view_confidence_default": 1.0,
        "garch_enabled": True,
        "turnover_lambda": None,
        "stress_severity_multiplier": 1.0,
        "advisor_enabled": True,
        "cvar_level": 0.95,
        "lambda_risk_aversion": None,
        "shrinkage_intensity_override": None,
        "expert_overrides": {},
    }


async def _load_calibration(
    db: AsyncSession, portfolio_id: uuid.UUID,
) -> dict[str, Any]:
    row = await db.execute(
        select(PortfolioCalibration).where(
            PortfolioCalibration.portfolio_id == portfolio_id,
        ),
    )
    cal = row.scalar_one_or_none()
    if cal is None:
        return _load_default_calibration(portfolio_id)
    return _serialize_calibration(cal)


# ── Stress scenario runner ─────────────────────────────────────


def _run_stress_suite(
    base_result: dict[str, Any],
    scenarios: list[str],
    severity_multiplier: float = 1.0,
) -> list[dict[str, Any]]:
    """Run the canonical preset stress scenarios against the optimizer
    output.

    Returns one dict per scenario, shaped for persistence to
    ``portfolio_stress_results``. The scenario loop is sync and
    fast (<1s for the 4 presets on a 30-fund portfolio) so it
    runs inline inside the 120s construct bound.
    """
    funds = base_result.get("funds") or []
    # Aggregate to block weights
    weights_by_block: dict[str, float] = {}
    for f in funds:
        bid = f.get("block_id")
        w = float(f.get("weight") or 0.0)
        if bid:
            weights_by_block[bid] = weights_by_block.get(bid, 0.0) + w

    results: list[dict[str, Any]] = []
    for scenario_name in scenarios:
        if scenario_name not in PRESET_SCENARIOS:
            # Unknown scenario — skip with an explanation row
            results.append({
                "scenario": scenario_name,
                "scenario_kind": "user_defined",
                "nav_impact_pct": None,
                "error": f"unknown preset: {scenario_name}",
            })
            continue
        raw_shocks = PRESET_SCENARIOS[scenario_name]
        shocks = {bid: shock * severity_multiplier for bid, shock in raw_shocks.items()}
        try:
            res = run_stress_scenario(
                weights_by_block=weights_by_block,
                shocks=shocks,
                historical_returns=None,
                scenario_name=scenario_name,
            )
            results.append({
                "scenario": scenario_name,
                "scenario_kind": "preset",
                "nav_impact_pct": float(res.nav_impact_pct),
                "cvar_impact_pct": float(res.cvar_stressed) if res.cvar_stressed is not None else None,
                "per_block_impact": [
                    {"block_id": bid, "loss_pct": loss}
                    for bid, loss in res.block_impacts.items()
                ],
                "per_instrument_impact": [],
                "shock_params": shocks,
                "worst_block": res.worst_block,
                "best_block": res.best_block,
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "stress_scenario_failed",
                extra={"scenario": scenario_name, "error": str(exc)},
            )
            results.append({
                "scenario": scenario_name,
                "scenario_kind": "preset",
                "nav_impact_pct": None,
                "error": str(exc),
            })
    return results


# ── Advisor fold-in (Task 3.3) ─────────────────────────────────


async def _build_advisor_result(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
    profile: str,
    base_result: dict[str, Any],
) -> dict[str, Any] | None:
    """Run the construction advisor and return its output as a dict.

    Only called when ``calibration.advisor_enabled=True`` AND the
    optimizer succeeded. Skips silently on any failure — the advisor
    is best-effort, it never blocks the run.
    """
    optimization = base_result.get("optimization") or {}
    if not optimization.get("status", "").startswith("optimal"):
        return None
    cvar = optimization.get("cvar_95")
    cvar_limit = optimization.get("cvar_limit")
    if cvar is None or cvar_limit is None:
        return None

    # Compute block_weights + basic coverage metrics without the heavy
    # data-fetching path of the standalone /construction-advice route.
    # The heavy path (fund returns, CUSIP overlap, candidate screening)
    # is exposed via the standalone route per OD-4 — this fold-in
    # provides a lighter "always-on" advisor signal.
    funds = base_result.get("funds") or []
    block_weights: dict[str, float] = {}
    for f in funds:
        bid = f.get("block_id")
        w = float(f.get("weight") or 0.0)
        if bid:
            block_weights[bid] = block_weights.get(bid, 0.0) + w

    return {
        "portfolio_id": str(portfolio_id),
        "profile": profile,
        "current_cvar_95": float(cvar),
        "cvar_limit": float(cvar_limit),
        "cvar_gap": round(float(cvar) - float(cvar_limit), 6),
        "block_weights": block_weights,
        "coverage_summary": {
            "total_blocks": len(block_weights),
            "weight_concentration": round(
                max(block_weights.values()) if block_weights else 0.0, 6,
            ),
        },
        "detail_endpoint": (
            f"/api/v1/model-portfolios/{portfolio_id}/construction-advice"
        ),
        "note": (
            "This is the lightweight always-on advisor surface. "
            "Call the detail endpoint for full candidate screening + "
            "minimum-viable-set analysis."
        ),
    }


async def _persist_template_failure(
    db: AsyncSession,
    *,
    run: PortfolioConstructionRun,
    report: TemplateReport,
) -> None:
    """PR-A25 — persist a template-incomplete failure to the run row.

    Mirrors :func:`_persist_coverage_failure`: writes a structured
    ``cascade_telemetry`` payload with ``winner_signal`` +
    ``operator_message`` plus a ``template_report`` envelope, and
    flips ``status = 'failed'`` with a compact ``failure_reason``.
    """
    operator_message = build_template_operator_message(report)
    existing_telemetry = run.cascade_telemetry or {}
    run.cascade_telemetry = {
        **existing_telemetry,
        "winner_signal": WinnerSignal.TEMPLATE_INCOMPLETE.value,
        "operator_signal": WinnerSignal.TEMPLATE_INCOMPLETE.value,
        "operator_message": operator_message,
        "template_report": report.model_dump(mode="json"),
        # Cascade never ran — signal to downstream consumers that
        # stress / advisor / validation output should not be rendered.
        "cascade_summary": "template_incomplete",
    }
    run.status = "failed"
    run.failure_reason = (
        f"template_incomplete: profile '{report.profile}' missing "
        f"{len(report.missing_canonical_blocks)} canonical block(s)"
    )


async def _count_approved_blocks(
    db: AsyncSession, organization_id: uuid.UUID | str, profile: str,
) -> tuple[int, int]:
    """PR-A26.2 Section E — return ``(approved, total)`` canonical-block count.

    ``approved`` counts rows with ``approved_at IS NOT NULL``; ``total``
    is the number of rows present for the ``(org, profile)`` pair.
    Realize mode requires ``approved == 18`` (== total once the A25
    canonical trigger has run).
    """
    from sqlalchemy import text as _sa_text

    row = await db.execute(
        _sa_text(
            """
            SELECT COUNT(*) FILTER (WHERE approved_at IS NOT NULL) AS approved,
                   COUNT(*) AS total
              FROM strategic_allocation
             WHERE organization_id = :org
               AND profile = :profile
            """
        ),
        {"org": str(organization_id), "profile": profile},
    )
    record = row.one_or_none()
    if record is None:
        return 0, 0
    return int(record[0] or 0), int(record[1] or 0)


async def _persist_no_approval_failure(
    db: AsyncSession,
    *,
    run: PortfolioConstructionRun,
    organization_id: uuid.UUID,
    profile: str,
    approved_count: int,
    total_count: int,
) -> None:
    """PR-A26.2 Section E — persist the no-approved-allocation failure."""
    existing = run.cascade_telemetry or {}
    run.cascade_telemetry = {
        **existing,
        "winner_signal": WinnerSignal.NO_APPROVED_ALLOCATION.value,
        "operator_signal": WinnerSignal.NO_APPROVED_ALLOCATION.value,
        "operator_message": {
            "title": "No approved Strategic IPS",
            "body": (
                f"Realize mode requires an approved Strategic allocation "
                f"for the '{profile}' profile — currently "
                f"{approved_count}/{total_count} canonical blocks are "
                "approved. Run POST /portfolio/profiles/{profile}/"
                "propose-allocation and then POST approve-proposal/{run_id} "
                "to seed the Strategic IPS anchor before realizing."
            ),
            "severity": "warning",
            "action_hint": "run_propose_then_approve",
        },
        "cascade_summary": "no_approved_allocation",
        "approval_state": {
            "approved_count": approved_count,
            "total_count": total_count,
        },
    }
    run.status = "failed"
    run.failure_reason = (
        f"no_approved_allocation: {approved_count}/{total_count} "
        f"canonical blocks approved for profile '{profile}'"
    )


async def _persist_instrument_concentration_breach(
    db: AsyncSession,
    *,
    run: PortfolioConstructionRun,
    breaches: list[dict[str, Any]],
) -> None:
    """PR-A26.2 Section F — persist instrument concentration breach."""
    existing = run.cascade_telemetry or {}
    run.cascade_telemetry = {
        **existing,
        "winner_signal": WinnerSignal.INSTRUMENT_CONCENTRATION_BREACH.value,
        "operator_signal": WinnerSignal.INSTRUMENT_CONCENTRATION_BREACH.value,
        "operator_message": {
            "title": "Per-instrument concentration cap breached",
            "body": (
                "One or more blocks would require a single instrument to "
                "hold more than 15% of the total portfolio to distribute "
                "the block's realize weight. Approve additional "
                "instruments for the breaching block(s) or accept a "
                "lower realize weight."
            ),
            "severity": "warning",
            "action_hint": "approve_more_instruments_or_reduce_block_weight",
        },
        "cascade_summary": "instrument_concentration_breach",
        "concentration_breaches": breaches,
    }
    run.status = "failed"
    first = breaches[0] if breaches else {}
    run.failure_reason = (
        f"instrument_concentration_breach: block={first.get('block_id')!r} "
        f"required={first.get('required')} available={first.get('available')}"
    )


async def _persist_coverage_failure(
    db: AsyncSession,
    *,
    run: PortfolioConstructionRun,
    report: CoverageReport,
) -> None:
    """PR-A22 — persist the block-coverage failure to the run row.

    Writes a structured ``cascade_telemetry`` payload that mirrors the
    shape of the normal cascade (``winner_signal`` +
    ``operator_message``) plus a ``coverage_report`` envelope with the
    per-block gap detail. Frontend consumers branch on
    ``winner_signal = 'block_coverage_insufficient'``.
    """
    operator_message = build_coverage_operator_message(report)
    existing_telemetry = run.cascade_telemetry or {}
    run.cascade_telemetry = {
        **existing_telemetry,
        "winner_signal": WinnerSignal.BLOCK_COVERAGE_INSUFFICIENT.value,
        "operator_signal": WinnerSignal.BLOCK_COVERAGE_INSUFFICIENT.value,
        "operator_message": operator_message,
        "coverage_report": report.model_dump(mode="json"),
        # cascade never ran — flag it so downstream readers know to
        # skip stress/advisor/validation rendering.
        "cascade_summary": "block_coverage_insufficient",
    }
    run.status = "failed"
    run.failure_reason = (
        f"block_coverage_insufficient: {len(report.gaps)} gap(s), "
        f"{report.total_target_weight_at_risk:.1%} of mandate uncovered"
    )


# ── PR-A26.1 — propose-mode band derivation ─────────────────────


def _derive_drift_band(target: float) -> tuple[float, float]:
    """Hybrid drift band per A26.1 spec: ``max(0.02, 0.15 * target)``.

    Returned band is symmetric and clamped to ``[0, 1]``. A target of
    zero collapses both edges to zero — used for excluded blocks and
    blocks the optimizer chose not to fund.
    """
    if target <= 0.0:
        return 0.0, 0.0
    drift = max(0.02, 0.15 * target)
    return max(0.0, target - drift), min(1.0, target + drift)


_PROPOSAL_DEFAULT_RATIONALE = (
    "Optimizer-proposed weight at this allocation under "
    "the configured CVaR target."
)
_PROPOSAL_EXCLUDED_RATIONALE = (
    "Block excluded by IPS — forced to zero exposure."
)


async def _build_propose_payload(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | str,
    profile: str,
    base_result: dict[str, Any],
    cascade_telemetry: dict[str, Any],
    ex_ante_metrics: dict[str, Any],
    calibration_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Build the propose-mode payload merged into ``cascade_telemetry``.

    Inputs come straight from the post-cascade state inside
    ``_execute_inner``: the funds list (for block aggregation), the
    canonical template + excluded-block set (re-queried RLS-aware), the
    cascade winner (for ``cvar_feasible``), and the ex-ante metrics.

    Returns a dict with three keys merged into cascade_telemetry:
    ``proposed_bands``, ``proposal_metrics``, and ``winner_signal``.
    The latter overrides the cascade-derived signal so propose runs
    surface ``proposal_ready`` / ``proposal_cvar_infeasible`` instead
    of the realize-mode operator signals.
    """
    from app.domains.wealth.models.allocation import StrategicAllocation
    from app.domains.wealth.models.block import AllocationBlock

    # 1. Aggregate optimizer weights to block level.
    weights_by_block: dict[str, float] = {}
    for fund in base_result.get("funds") or []:
        bid = fund.get("block_id")
        if not bid:
            continue
        w = float(fund.get("weight") or 0.0)
        weights_by_block[bid] = weights_by_block.get(bid, 0.0) + w

    # 2. Canonical block list + excluded set (RLS-aware via passed db).
    canonical_rows = (
        await db.execute(
            select(AllocationBlock.block_id)
            .where(AllocationBlock.is_canonical.is_(True))
        )
    ).all()
    canonical_block_ids = sorted({r[0] for r in canonical_rows})

    excluded_rows = (
        await db.execute(
            select(StrategicAllocation.block_id)
            .where(
                StrategicAllocation.profile == profile,
                StrategicAllocation.excluded_from_portfolio.is_(True),
            )
        )
    ).all()
    excluded_block_ids = {r[0] for r in excluded_rows}

    # 3. Build proposed bands per canonical block.
    proposed_bands: list[dict[str, Any]] = []
    for bid in canonical_block_ids:
        if bid in excluded_block_ids:
            proposed_bands.append({
                "block_id": bid,
                "target_weight": 0.0,
                "drift_min": 0.0,
                "drift_max": 0.0,
                "rationale": _PROPOSAL_EXCLUDED_RATIONALE,
            })
            continue
        target = float(weights_by_block.get(bid, 0.0))
        drift_min, drift_max = _derive_drift_band(target)
        proposed_bands.append({
            "block_id": bid,
            "target_weight": round(target, 6),
            "drift_min": round(drift_min, 6),
            "drift_max": round(drift_max, 6),
            "rationale": _PROPOSAL_DEFAULT_RATIONALE,
        })

    # 4. cvar_feasible: True iff the cascade landed on Phase 1 or Phase 2.
    # Phase 3 (min-CVaR fallback) means the universe floor exceeds the
    # operator's CVaR target — return the bands but flag infeasibility.
    winning_phase = (base_result.get("cascade") or {}).get("winning_phase")
    cvar_feasible = winning_phase in {
        "phase_1_ru_max_return",
        "phase_2_ru_robust",
    }

    target_cvar = calibration_snapshot.get("cvar_limit")
    expected_cvar = ex_ante_metrics.get("cvar_95")
    proposal_metrics = {
        "expected_return": ex_ante_metrics.get("expected_return"),
        "expected_cvar": expected_cvar,
        "expected_sharpe": ex_ante_metrics.get("sharpe_ratio"),
        "target_cvar": float(target_cvar) if target_cvar is not None else None,
        "cvar_feasible": bool(cvar_feasible),
    }

    winner_signal = (
        WinnerSignal.PROPOSAL_READY.value
        if cvar_feasible
        else WinnerSignal.PROPOSAL_CVAR_INFEASIBLE.value
    )

    return {
        "proposed_bands": proposed_bands,
        "proposal_metrics": proposal_metrics,
        "winner_signal": winner_signal,
        "run_mode": "propose",
    }


# ── Main entry point ──────────────────────────────────────────


async def execute_construction_run(
    db: AsyncSession,
    *,
    portfolio_id: uuid.UUID,
    organization_id: uuid.UUID | str,
    requested_by: str,
    job_id: str | None = None,
    as_of_date: date | None = None,
    propose_mode: bool = False,
) -> PortfolioConstructionRun:
    """Execute a full enriched construction run.

    This is the load-bearing entry point for Phase 3. It runs:

    1. Calibration load
    2. Advisory lock acquisition (DL19, 900_101)
    3. Optimizer cascade via ``_run_construction_async``
    4. Stress suite (4 preset scenarios)
    5. Advisor fold-in (if ``calibration.advisor_enabled``)
    6. 15-check validation gate
    7. Jinja2 narrative templater
    8. Persistence of the ``portfolio_construction_runs`` row +
       ``portfolio_stress_results`` rows
    9. SSE publication of progress + terminal events

    Parameters
    ----------
    db
        RLS-aware async session bound to the requesting org.
    portfolio_id
        Target portfolio UUID.
    organization_id
        Org UUID — must match the current RLS context.
    requested_by
        ``actor.actor_id`` from the route handler — recorded on
        the run + used as ``state_changed_by`` downstream.
    job_id
        SSE job ID. If ``None``, no SSE events are published
        (synchronous caller).
    as_of_date
        Run as-of date. Defaults to today.

    Returns
    -------
    PortfolioConstructionRun
        The persisted run row — the caller should immediately
        return its ID to the client via the 202 response.
    """
    as_of_date = as_of_date or date.today()
    start_ts = time.perf_counter()

    # ── 1. Load calibration ──
    calibration_snapshot = await _load_calibration(db, portfolio_id)
    cache_hash = compute_cache_key(portfolio_id, calibration_snapshot, as_of_date)

    # ── 2. Persist the run row as 'running' ──
    run = PortfolioConstructionRun(
        organization_id=uuid.UUID(str(organization_id)) if not isinstance(organization_id, uuid.UUID) else organization_id,
        portfolio_id=portfolio_id,
        calibration_snapshot=calibration_snapshot,
        calibration_hash=cache_hash,
        universe_fingerprint="pending",  # filled post-construction
        as_of_date=as_of_date,
        status="running",
        run_mode="propose" if propose_mode else "realize",
        requested_by=requested_by,
        started_at=datetime.now(tz=timezone.utc),
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)

    run_id = run.id

    await _publish_event_sanitized(
        db,
        run_id=run_id,
        job_id=job_id,
        raw_type="run_started",
        raw_payload={"run_id": str(run_id), "portfolio_id": str(portfolio_id)},
    )

    try:
        # ── 3. Wall-clock bound (DL18 P1) ──
        await asyncio.wait_for(
            _execute_inner(
                db=db,
                run=run,
                portfolio_id=portfolio_id,
                calibration_snapshot=calibration_snapshot,
                job_id=job_id,
                propose_mode=propose_mode,
            ),
            timeout=CONSTRUCTION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        run.status = "failed"
        run.failure_reason = (
            f"construction exceeded {CONSTRUCTION_TIMEOUT_SECONDS}s wall-clock bound"
        )
        run.completed_at = datetime.now(tz=timezone.utc)
        run.wall_clock_ms = int((time.perf_counter() - start_ts) * 1000)
        await db.flush()
        await _publish_terminal_event_sanitized(
            db,
            run_id=run_id,
            job_id=job_id,
            raw_type="run_failed",
            raw_payload={"run_id": str(run_id), "reason": "timeout"},
        )
        logger.warning(
            "construction_run_timeout",
            extra={"run_id": str(run_id), "portfolio_id": str(portfolio_id)},
        )
        return run
    except TemplateIncompleteError as template_exc:
        # PR-A25 — structural failure ahead of the coverage gate.
        await _persist_template_failure(
            db, run=run, report=template_exc.report,
        )
        run.completed_at = datetime.now(tz=timezone.utc)
        run.wall_clock_ms = int((time.perf_counter() - start_ts) * 1000)
        await db.flush()
        await _publish_terminal_event_sanitized(
            db,
            run_id=run_id,
            job_id=job_id,
            raw_type="run_failed",
            raw_payload={
                "run_id": str(run_id),
                "reason": "template_incomplete",
                "winner_signal": WinnerSignal.TEMPLATE_INCOMPLETE.value,
                "template_report": template_exc.report.model_dump(mode="json"),
            },
        )
        logger.warning(
            "construction_run_template_incomplete",
            extra={
                "run_id": str(run_id),
                "portfolio_id": str(portfolio_id),
                "missing_canonical_blocks": (
                    template_exc.report.missing_canonical_blocks
                ),
            },
        )
        return run
    except NoApprovedAllocationError as no_approval_exc:
        # PR-A26.2 Section E — realize mode blocked; emit structured signal.
        await _persist_no_approval_failure(
            db,
            run=run,
            organization_id=no_approval_exc.organization_id,
            profile=no_approval_exc.profile,
            approved_count=no_approval_exc.approved_count,
            total_count=no_approval_exc.total_count,
        )
        run.completed_at = datetime.now(tz=timezone.utc)
        run.wall_clock_ms = int((time.perf_counter() - start_ts) * 1000)
        await db.flush()
        await _publish_terminal_event_sanitized(
            db,
            run_id=run_id,
            job_id=job_id,
            raw_type="run_failed",
            raw_payload={
                "run_id": str(run_id),
                "reason": "no_approved_allocation",
                "winner_signal": WinnerSignal.NO_APPROVED_ALLOCATION.value,
                "approved_count": no_approval_exc.approved_count,
                "total_count": no_approval_exc.total_count,
            },
        )
        logger.info(
            "construction_run_no_approved_allocation",
            extra={
                "run_id": str(run_id),
                "portfolio_id": str(portfolio_id),
                "profile": no_approval_exc.profile,
                "approved": no_approval_exc.approved_count,
                "total": no_approval_exc.total_count,
            },
        )
        return run
    except InstrumentConcentrationBreachError as conc_exc:
        # PR-A26.2 Section F — realize composition refused; emit signal.
        await _persist_instrument_concentration_breach(
            db,
            run=run,
            breaches=[
                {
                    "block_id": conc_exc.block_id,
                    "block_weight": conc_exc.block_weight,
                    "required": conc_exc.required,
                    "available": conc_exc.available,
                },
            ],
        )
        run.completed_at = datetime.now(tz=timezone.utc)
        run.wall_clock_ms = int((time.perf_counter() - start_ts) * 1000)
        await db.flush()
        await _publish_terminal_event_sanitized(
            db,
            run_id=run_id,
            job_id=job_id,
            raw_type="run_failed",
            raw_payload={
                "run_id": str(run_id),
                "reason": "instrument_concentration_breach",
                "winner_signal": (
                    WinnerSignal.INSTRUMENT_CONCENTRATION_BREACH.value
                ),
                "block_id": conc_exc.block_id,
                "required": conc_exc.required,
                "available": conc_exc.available,
            },
        )
        logger.info(
            "construction_run_instrument_concentration_breach",
            extra={
                "run_id": str(run_id),
                "portfolio_id": str(portfolio_id),
                "block_id": conc_exc.block_id,
                "required": conc_exc.required,
                "available": conc_exc.available,
            },
        )
        return run
    except CoverageInsufficientError as coverage_exc:
        # PR-A22 — pre-solve failure with structured gap report.
        await _persist_coverage_failure(
            db, run=run, report=coverage_exc.report,
        )
        run.completed_at = datetime.now(tz=timezone.utc)
        run.wall_clock_ms = int((time.perf_counter() - start_ts) * 1000)
        await db.flush()
        await _publish_terminal_event_sanitized(
            db,
            run_id=run_id,
            job_id=job_id,
            raw_type="run_failed",
            raw_payload={
                "run_id": str(run_id),
                "reason": "block_coverage_insufficient",
                "winner_signal": WinnerSignal.BLOCK_COVERAGE_INSUFFICIENT.value,
                "coverage_report": coverage_exc.report.model_dump(mode="json"),
            },
        )
        logger.info(
            "construction_run_block_coverage_insufficient",
            extra={
                "run_id": str(run_id),
                "portfolio_id": str(portfolio_id),
                "gaps": [g.block_id for g in coverage_exc.report.gaps],
                "weight_at_risk": coverage_exc.report.total_target_weight_at_risk,
            },
        )
        return run
    except RunCancelledError as cancel_exc:
        run.status = "cancelled"
        run.failure_reason = f"cancelled at phase {cancel_exc.phase}"
        run.completed_at = datetime.now(tz=timezone.utc)
        run.wall_clock_ms = int((time.perf_counter() - start_ts) * 1000)
        await db.flush()
        await _publish_terminal_event_sanitized(
            db,
            run_id=run_id,
            job_id=job_id,
            raw_type="run_cancelled",
            raw_payload={
                "run_id": str(run_id),
                "phase": cancel_exc.phase,
                "reason": "cancellation_requested",
            },
        )
        if job_id:
            await clear_cancellation_flag(job_id)
        logger.info(
            "construction_run_cancelled",
            extra={
                "run_id": str(run_id),
                "portfolio_id": str(portfolio_id),
                "phase": cancel_exc.phase,
            },
        )
        return run
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.failure_reason = f"{type(exc).__name__}: {exc}"
        run.completed_at = datetime.now(tz=timezone.utc)
        run.wall_clock_ms = int((time.perf_counter() - start_ts) * 1000)
        await db.flush()
        await _publish_terminal_event_sanitized(
            db,
            run_id=run_id,
            job_id=job_id,
            raw_type="run_failed",
            raw_payload={"run_id": str(run_id), "reason": str(exc)},
        )
        logger.exception(
            "construction_run_failed",
            extra={"run_id": str(run_id), "portfolio_id": str(portfolio_id)},
        )
        return run

    # PR-A12 cascade summary enum drives run.status. Post-A12 there is no
    # cvar-blind fallback that produced weights — Phase 3 always runs
    # CVaR-aware, so ``phase_3_min_cvar_above_limit`` and ``upstream_heuristic``
    # are the only ``degraded`` outcomes; ``constraint_polytope_empty`` is the
    # only remaining terminal failure. The legacy solver-string check stays
    # as a defensive fallback for empty cascade_telemetry (pre-A11 mocks).
    telemetry_summary = (run.cascade_telemetry or {}).get("cascade_summary")
    solver = (run.optimizer_trace or {}).get("solver")
    if telemetry_summary in (
        "phase_3_min_cvar_above_limit",
        "upstream_heuristic",
    ):
        run.status = "degraded"
    elif telemetry_summary == "constraint_polytope_empty":
        run.status = "failed"
    elif telemetry_summary in (
        "phase_1_succeeded",
        "phase_2_robust_succeeded",
        "phase_3_min_cvar_within_limit",
    ):
        run.status = "succeeded"
    elif solver == "heuristic_fallback":
        # Defensive: legacy path where cascade_telemetry is empty but the
        # upstream-bailout composition was built (solver tag set by the route).
        run.status = "degraded"
    else:
        run.status = "succeeded"
    run.completed_at = datetime.now(tz=timezone.utc)
    run.wall_clock_ms = int((time.perf_counter() - start_ts) * 1000)
    await db.flush()

    # Keep the raw_type as ``run_succeeded`` so the existing frontend
    # ``phase === "COMPLETED"`` mapping still terminates the builder flow;
    # the ``status`` field on the payload carries the degraded signal so
    # downstream UI can render a fallback badge (frontend work lands in PR-A8).
    await _publish_terminal_event_sanitized(
        db,
        run_id=run_id,
        job_id=job_id,
        raw_type="run_succeeded",
        raw_payload={
            "run_id": str(run_id),
            "status": run.status,
            "wall_clock_ms": run.wall_clock_ms,
        },
    )

    logger.info(
        "construction_run_succeeded",
        extra={
            "run_id": str(run_id),
            "portfolio_id": str(portfolio_id),
            "status": run.status,
            "wall_clock_ms": run.wall_clock_ms,
        },
    )
    return run


async def _execute_inner(
    *,
    db: AsyncSession,
    run: PortfolioConstructionRun,
    portfolio_id: uuid.UUID,
    calibration_snapshot: dict[str, Any],
    job_id: str | None,
    propose_mode: bool = False,
) -> None:
    """The inner pipeline — everything that runs inside the 120s bound.

    Extracted into its own coroutine so ``asyncio.wait_for`` can cleanly
    cancel it on timeout without leaving the run row in an inconsistent
    state.
    """
    # Imported lazily to avoid a circular import at module load:
    # routes.model_portfolios → workers.construction_run_executor → routes.*
    from app.domains.wealth.routes.model_portfolios import _run_construction_async

    # ── Load portfolio profile ──
    portfolio_row = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = portfolio_row.scalar_one_or_none()
    if portfolio is None:
        raise LookupError(f"portfolio {portfolio_id} not found")
    profile = portfolio.profile
    organization_id = portfolio.organization_id

    # ── PR-A25. Template completeness gate — runs BEFORE the coverage
    # gate so structural defects (missing canonical blocks) surface as
    # the dedicated ``template_incomplete`` signal. Post-migration 0153
    # this should never fail; if it does the trigger is broken and the
    # operator message directs them to engineering rather than to the
    # universe editor.
    template = await validate_template_completeness(
        db, organization_id, profile,
    )
    if not template.is_complete:
        raise TemplateIncompleteError(template)

    # ── PR-A22. Block coverage gate — fail fast if any block in the
    # profile's StrategicAllocation has zero approved candidates in
    # the org's universe. Runs BEFORE the optimizer so the cascade is
    # never invoked against an ill-specified mandate. The operator
    # sees a structured gap report instead of a silently redistributed
    # portfolio.
    coverage = await validate_block_coverage(db, organization_id, profile)
    if not coverage.is_sufficient:
        raise CoverageInsufficientError(coverage)

    # ── PR-A26.2 Section E. Realize-mode approval gate ──
    # Refuse-to-run until an approved Strategic IPS exists for the
    # (org, profile) pair. Propose mode skips this check — it generates
    # the anchor bands the operator later approves.
    if not propose_mode:
        approved, total = await _count_approved_blocks(
            db, organization_id, profile,
        )
        # ``total`` is 18 post-A25; allow for transitional fixtures by
        # requiring ``approved == total`` AND ``approved > 0``.
        if total == 0 or approved < total:
            raise NoApprovedAllocationError(
                organization_id=organization_id,
                profile=profile,
                approved_count=approved,
                total_count=total,
            )

    await _check_cancellation(job_id, "pre_optimizer")
    await _publish_event_sanitized(
        db,
        run_id=run.id,
        job_id=job_id,
        raw_type="optimizer_started",
        raw_payload={"profile": profile},
    )

    # ── 4. Optimizer cascade ──
    base_result = await _run_construction_async(
        db, profile, str(organization_id), portfolio_id=portfolio_id,
        propose_mode=propose_mode,
    )

    # PR-A8 — Layer 3 dedup telemetry. Surfaced as a sanitized SSE event
    # so the frontend (PR-A9) can render the universe-size chip on the
    # SHRINKAGE phase, and persisted to ``statistical_inputs.dedup`` so
    # late subscribers and audit consumers can see what was pruned.
    dedup_block = base_result.get("dedup") if isinstance(base_result, dict) else None
    if isinstance(dedup_block, dict):
        await _publish_event_sanitized(
            db,
            run_id=run.id,
            job_id=job_id,
            raw_type="prefilter_dedup_completed",
            raw_payload={
                "universe_size_before_dedup": dedup_block.get("n_input"),
                "universe_size_after_dedup": dedup_block.get("n_kept"),
                "n_clusters": dedup_block.get("n_clusters"),
                "threshold": dedup_block.get("threshold_used"),
                "pair_corr_p50": dedup_block.get("pair_corr_p50"),
                "pair_corr_p95": dedup_block.get("pair_corr_p95"),
            },
        )

    # PR-A9 — three-tier κ(Σ) telemetry. Backend emits numeric metrics only;
    # the frontend in PR-A10 formats the human "conditioning: good / acceptable
    # / fallback applied" label. Raw `covariance_source` ∈ {"sample",
    # "factor_model"} survives through ``sanitize_payload`` unchanged because
    # neither is in the regime/jargon sanitiser allowlist.
    shrinkage_block = (
        base_result.get("shrinkage") if isinstance(base_result, dict) else None
    )
    if isinstance(shrinkage_block, dict) and shrinkage_block:
        await _publish_event_sanitized(
            db,
            run_id=run.id,
            job_id=job_id,
            raw_type="shrinkage_completed",
            raw_payload={
                "kappa_sample": shrinkage_block.get("kappa_sample"),
                "kappa_final": shrinkage_block.get("kappa_final"),
                "kappa_factor_fallback": shrinkage_block.get(
                    "kappa_factor_fallback",
                ),
                "covariance_source": shrinkage_block.get("covariance_source"),
                "warn": shrinkage_block.get("warn"),
            },
        )

    optimizer_trace = {
        "solver": (base_result.get("optimization") or {}).get("solver"),
        "status": (base_result.get("optimization") or {}).get("status"),
        "error": base_result.get("error"),
    }

    # Enrich calibration_snapshot with TAA provenance from the construction result
    taa_provenance = base_result.get("taa")
    if taa_provenance:
        calibration_snapshot["taa"] = taa_provenance

    # Build weights_proposed from the funds list
    funds = base_result.get("funds") or []
    weights_proposed = {
        str(f["instrument_id"]): float(f.get("weight") or 0.0)
        for f in funds
        if f.get("instrument_id") is not None
    }

    # Ex-ante metrics from optimization section
    optimization = base_result.get("optimization") or {}
    ex_ante_metrics = {
        "expected_return": optimization.get("expected_return"),
        "portfolio_volatility": optimization.get("portfolio_volatility"),
        "sharpe_ratio": optimization.get("sharpe_ratio"),
        "cvar_95": optimization.get("cvar_95"),
    }

    factor_exposure = optimization.get("factor_exposures") or {}

    # ── 4b. Retrospective per-phase cascade events ──
    # The optimizer runs as a single call — we infer the cascade path
    # from the result status and emit events so the frontend timeline
    # can reconstruct the progression.
    await _emit_cascade_phase_events(
        db,
        run_id=run.id,
        job_id=job_id,
        winning_phase=(base_result.get("cascade") or {}).get("winning_phase"),
        objective_value=optimization.get("expected_return"),
    )

    # ── 4c. PR-A11/A12 cascade telemetry (structured + sanitized) ──
    cascade_telemetry, derived_run_status = _build_cascade_telemetry(
        cascade_block=base_result.get("cascade") or {},
        optimizer_trace=optimizer_trace,
        cvar_limit=calibration_snapshot.get("cvar_limit"),
    )
    if cascade_telemetry:
        await _publish_event_sanitized(
            db,
            run_id=run.id,
            job_id=job_id,
            raw_type="cascade_telemetry_completed",
            raw_payload={
                "cascade_summary": cascade_telemetry.get("cascade_summary"),
                "operator_signal": cascade_telemetry.get("operator_signal"),
                # PR-A12 — Builder slider inputs. Sanitized numeric values only.
                "min_achievable_cvar": cascade_telemetry.get("min_achievable_cvar"),
                "achievable_return_band": cascade_telemetry.get("achievable_return_band"),
                # PR-A19.1 Section C — cascade-aware operator signal.
                "winner_signal": cascade_telemetry.get("winner_signal"),
                "operator_message": cascade_telemetry.get("operator_message"),
            },
        )

    # ── PR-A26.1 — propose-mode payload (bands + metrics) ──
    if propose_mode:
        proposal_payload = await _build_propose_payload(
            db,
            organization_id=organization_id,
            profile=profile,
            base_result=base_result,
            cascade_telemetry=cascade_telemetry,
            ex_ante_metrics=ex_ante_metrics,
            calibration_snapshot=calibration_snapshot,
        )
        cascade_telemetry = {**cascade_telemetry, **proposal_payload}
        await _publish_event_sanitized(
            db,
            run_id=run.id,
            job_id=job_id,
            raw_type=(
                "propose_ready"
                if proposal_payload["proposal_metrics"]["cvar_feasible"]
                else "propose_cvar_infeasible"
            ),
            raw_payload={
                "winner_signal": proposal_payload["winner_signal"],
                "proposal_metrics": proposal_payload["proposal_metrics"],
                "n_bands": len(proposal_payload["proposed_bands"]),
            },
        )

    # ── 5. Stress suite (sequence: after optimizer, before advisor) ──
    await _check_cancellation(job_id, "pre_stress")
    await _publish_event_sanitized(
        db,
        run_id=run.id,
        job_id=job_id,
        raw_type="stress_started",
        raw_payload={},
    )
    active_scenarios = list(calibration_snapshot.get("stress_scenarios_active") or [])
    severity = float(calibration_snapshot.get("stress_severity_multiplier") or 1.0)
    stress_results = _run_stress_suite(base_result, active_scenarios, severity)

    # Persist one row per preset stress result
    for sr in stress_results:
        if sr.get("error"):
            continue
        db.add(
            PortfolioStressResult(
                organization_id=organization_id,
                portfolio_id=portfolio_id,
                construction_run_id=run.id,
                scenario=sr["scenario"],
                scenario_kind=sr.get("scenario_kind", "preset"),
                scenario_label=None,
                as_of=run.as_of_date,
                nav_impact_pct=sr.get("nav_impact_pct") or 0.0,
                cvar_impact_pct=sr.get("cvar_impact_pct"),
                per_block_impact=sr.get("per_block_impact") or [],
                per_instrument_impact=sr.get("per_instrument_impact") or [],
                shock_params=sr.get("shock_params") or {},
            ),
        )
    await db.flush()

    # ── 6. Advisor fold-in (Task 3.3) — only if enabled ──
    advisor_result: dict[str, Any] | None = None
    if calibration_snapshot.get("advisor_enabled"):
        await _check_cancellation(job_id, "pre_advisor")
        await _publish_event_sanitized(
            db,
            run_id=run.id,
            job_id=job_id,
            raw_type="advisor_started",
            raw_payload={},
        )
        try:
            advisor_result = await _build_advisor_result(
                db, portfolio_id, profile, base_result,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "advisor_fold_in_failed",
                extra={"run_id": str(run.id), "error": str(exc)},
            )
            advisor_result = {"error": f"{type(exc).__name__}: {exc}"}

    # ── 7. Validation gate (15 checks, no fail-fast) ──
    await _check_cancellation(job_id, "pre_validation")
    await _publish_event_sanitized(
        db,
        run_id=run.id,
        job_id=job_id,
        raw_type="validation_started",
        raw_payload={},
    )

    # Build the JSONB-shaped payload the validation gate expects.
    statistical_inputs_payload: dict[str, Any] = {}
    if isinstance(dedup_block, dict):
        statistical_inputs_payload["dedup"] = dedup_block
    # PR-A9 — persist conditioning payload so Section F.1 SQL can query
    # ``statistical_inputs->>'covariance_source'`` / ``->>'kappa_sample'``
    # / ``->>'kappa_final'`` directly (no nested object walk needed).
    if isinstance(shrinkage_block, dict) and shrinkage_block:
        statistical_inputs_payload["shrinkage"] = shrinkage_block
        statistical_inputs_payload["covariance_source"] = shrinkage_block.get(
            "covariance_source",
        )
        statistical_inputs_payload["kappa_sample"] = shrinkage_block.get(
            "kappa_sample",
        )
        statistical_inputs_payload["kappa_final"] = shrinkage_block.get(
            "kappa_final",
        )
    validation_payload: dict[str, Any] = {
        "as_of_date": run.as_of_date.isoformat(),
        "profile": profile,
        "weights_proposed": weights_proposed,
        "calibration_snapshot": calibration_snapshot,
        "ex_ante_metrics": ex_ante_metrics,
        "funds": funds,
        "stress_results": stress_results,
        "optimizer_trace": optimizer_trace,
        "statistical_inputs": statistical_inputs_payload,
        "factor_exposure": factor_exposure,
    }
    validation_result = validate_construction(
        validation_payload, ValidationDbContext(),
    )
    validation_jsonb = to_jsonb(validation_result)

    # ── 8. Narrative templater (pure Jinja2, no LLM) ──
    await _check_cancellation(job_id, "pre_narrative")
    await _publish_event_sanitized(
        db,
        run_id=run.id,
        job_id=job_id,
        raw_type="narrative_started",
        raw_payload={},
    )

    # Resolve regime from TAA provenance if available, else from calibration override
    taa_section = calibration_snapshot.get("taa") or {}
    resolved_regime = (
        taa_section.get("raw_regime")
        or calibration_snapshot.get("regime_override")
        or "NORMAL"
    )

    narrative_payload: dict[str, Any] = {
        **validation_payload,
        "binding_constraints": [],  # optimizer doesn't currently export — future work
        "regime_context": {"regime": resolved_regime},
    }
    narrative = render_narrative(narrative_payload)

    # ── 9. Persist all enrichment on the run row ──
    run.optimizer_trace = optimizer_trace
    # PR-A11 — cascade telemetry column (binding_constraints intentionally
    # left untouched; keeps its existing list-of-strings semantics).
    run.cascade_telemetry = cascade_telemetry
    run.binding_constraints = []
    run.regime_context = narrative_payload["regime_context"]
    run.statistical_inputs = statistical_inputs_payload
    run.ex_ante_metrics = ex_ante_metrics
    run.factor_exposure = factor_exposure
    run.stress_results = stress_results
    run.advisor = advisor_result
    run.validation = validation_jsonb
    run.narrative = narrative
    run.rationale_per_weight = {}
    run.weights_proposed = weights_proposed
    run.universe_fingerprint = hashlib.sha256(
        json.dumps(sorted(weights_proposed.keys())).encode(),
    ).hexdigest()

    await db.flush()


# ── Dataclass-safe serializer for advisor payloads ─────────────


def _dataclass_to_dict(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    return obj
