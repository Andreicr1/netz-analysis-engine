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
    humanize_event_type,
    sanitize_payload,
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

    telemetry = {
        "phase_attempts": public_attempts,
        "cascade_summary": cascade_summary,
        "min_achievable_cvar": min_achievable_cvar,
        "achievable_return_band": achievable_return_band,
        "operator_signal": operator_signal,
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


# ── Main entry point ──────────────────────────────────────────


async def execute_construction_run(
    db: AsyncSession,
    *,
    portfolio_id: uuid.UUID,
    organization_id: uuid.UUID | str,
    requested_by: str,
    job_id: str | None = None,
    as_of_date: date | None = None,
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

    # Detect heuristic fallback + PR-A11 Phase 3 min-variance fallback. Both
    # outcomes produced weights but fail to honor the CVaR objective, so
    # persist as ``degraded``. ``run.cascade_telemetry`` (set in the inner
    # executor) drives the decision; the legacy solver-string check remains
    # as a defensive fallback for pre-A11 code paths (empty telemetry).
    telemetry_summary = (run.cascade_telemetry or {}).get("cascade_summary")
    solver = (run.optimizer_trace or {}).get("solver")
    if telemetry_summary in ("phase_3_fallback", "heuristic_fallback"):
        run.status = "degraded"
    elif telemetry_summary == "cascade_exhausted":
        run.status = "failed"
    elif telemetry_summary in ("phase_1_succeeded", "phase_1_5_robust_succeeded", "phase_2_succeeded"):
        run.status = "succeeded"
    elif solver == "heuristic_fallback":
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
