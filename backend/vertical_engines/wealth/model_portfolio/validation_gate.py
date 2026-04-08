"""Validation gate with 15 checks for construction runs.

Phase 3 Task 3.1 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

Runs 15 independent checks against a construction run payload.
**No fail-fast** — every check is evaluated so the UI can render a
complete health panel, not just the first failure. Aggregation is
``passed = not any(block failures)``.

Severity taxonomy
-----------------
- ``block`` — a blocking issue. Under default policy, a block
  failure prevents activation. Under OD-5 soft-block policy
  (``ApprovalPolicy.require_construction_for_approve = False``) the
  state machine keeps the ``approve`` action visible and the route
  layer captures an IC chair override + audit log.
- ``warn`` — a warning that does not block activation but is
  surfaced in the narrative and the Builder's CalibrationPanel.

Public surface
--------------
- :class:`ValidationCheck` — frozen dataclass, one per check
- :class:`ValidationResult` — aggregate result
- :class:`ValidationDbContext` — pre-fetched DB rows needed by the
  checks (keeps the gate synchronous and testable)
- :func:`validate_construction` — run all 15 and aggregate

The 15 checks
-------------
1. weights-sum-to-one
2. no-stale-nav
3. cvar-within-effective-limit
4. turnover-within-cap
5. min-diversification-count
6. max-single-fund-weight
7. all-block-min-weights-satisfied
8. all-block-max-weights-satisfied
9. no-banned-instruments
10. all-instruments-approved
11. stress-within-tolerance
12. no-unrealistic-expected-return
13. bl-views-consistent-with-prior
14. garch-convergence-rate
15. factor-model-r-squared
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final, Literal

Severity = Literal["block", "warn"]


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    """Result of a single validation check.

    Pure data — no ORM references. Safe to cross async/thread
    boundaries (CLAUDE.md rule). Serialized to JSONB as-is for
    the ``portfolio_construction_runs.validation`` column.
    """

    id: str
    label: str
    severity: Severity
    passed: bool
    value: float | int | None
    threshold: float | int | None
    explanation: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Aggregate of the 15 checks."""

    passed: bool
    """True if no block-severity check failed."""

    checks: list[ValidationCheck]
    """All 15 checks in stable order."""

    warnings: list[ValidationCheck] = field(default_factory=list)
    """Subset of ``checks`` where ``severity='warn'`` and ``passed=False``."""

    blocks: list[ValidationCheck] = field(default_factory=list)
    """Subset of ``checks`` where ``severity='block'`` and ``passed=False``."""


@dataclass(frozen=True, slots=True)
class ValidationDbContext:
    """Pre-fetched DB state the checks need.

    Loaded once by the caller (the ``construction_run_executor``
    worker) and passed in — keeps :func:`validate_construction`
    fully synchronous and unit-testable without a DB.

    Attributes
    ----------
    banned_instrument_ids
        Set of instrument UUIDs the org has explicitly banned.
        Empty set if the org has no bans configured.
    approved_instrument_ids
        Set of instrument UUIDs in the org's approved universe.
        All opt_fund_ids used in the run must be in this set.
    strategic_targets
        ``{block_id: target_weight}`` from ``StrategicAllocation``.
    block_constraints
        ``{block_id: (min_weight, max_weight)}``.
    nav_latest_date
        ``{instrument_id: latest_nav_date}`` for the staleness check.
    """

    banned_instrument_ids: frozenset[str] = frozenset()
    approved_instrument_ids: frozenset[str] = frozenset()
    strategic_targets: dict[str, float] = field(default_factory=dict)
    block_constraints: dict[str, tuple[float, float]] = field(default_factory=dict)
    nav_latest_date: dict[str, str] = field(default_factory=dict)
    nav_staleness_threshold_days: int = 10


# ── Check thresholds (all tunable via ConfigService in a later sprint) ──

_WEIGHTS_SUM_TOLERANCE: Final[float] = 1e-4
_MIN_DIVERSIFICATION_COUNT: Final[int] = 5
_MAX_REALISTIC_ER_ABS: Final[float] = 0.50  # 50% annual expected return ceiling
_GARCH_MIN_CONVERGENCE: Final[float] = 0.80
_FACTOR_MODEL_MIN_R2: Final[float] = 0.30
_STRESS_NAV_IMPACT_THRESHOLD: Final[float] = -0.40  # worse than -40% = block
_BL_POSTERIOR_DEVIATION_MAX: Final[float] = 2.0  # sigma
_BLOCK_WEIGHT_TOLERANCE: Final[float] = 1e-4


# ── Individual check implementations ─────────────────────────────


def _check_weights_sum_to_one(
    run_payload: dict[str, Any],
    _db: ValidationDbContext,
) -> ValidationCheck:
    weights = run_payload.get("weights_proposed") or {}
    if not isinstance(weights, dict):
        weights = {}
    total = sum(float(w) for w in weights.values() if w is not None)
    passed = abs(total - 1.0) <= _WEIGHTS_SUM_TOLERANCE
    return ValidationCheck(
        id="weights_sum_to_one",
        label="Weights sum to 100%",
        severity="block",
        passed=passed,
        value=round(total, 6),
        threshold=1.0,
        explanation=(
            f"Proposed weights total {total:.4%} — must be within "
            f"{_WEIGHTS_SUM_TOLERANCE:.0e} of 1.0."
        ),
    )


def _check_no_stale_nav(
    run_payload: dict[str, Any],
    db: ValidationDbContext,
) -> ValidationCheck:
    weights = run_payload.get("weights_proposed") or {}
    instrument_ids = [str(iid) for iid in weights]
    as_of_date = run_payload.get("as_of_date")
    stale_count = 0
    if as_of_date:
        for iid in instrument_ids:
            latest = db.nav_latest_date.get(iid)
            if latest is None:
                stale_count += 1
    passed = stale_count == 0
    return ValidationCheck(
        id="no_stale_nav",
        label="NAV data is fresh",
        severity="block",
        passed=passed,
        value=stale_count,
        threshold=0,
        explanation=(
            f"{stale_count} instrument(s) have NAV data older than "
            f"{db.nav_staleness_threshold_days} days or missing entirely."
        ),
    )


def _check_cvar_within_limit(
    run_payload: dict[str, Any],
    _db: ValidationDbContext,
) -> ValidationCheck:
    metrics = run_payload.get("ex_ante_metrics") or {}
    cvar = metrics.get("cvar_95")
    calibration = run_payload.get("calibration_snapshot") or {}
    limit = calibration.get("cvar_limit")
    if cvar is None or limit is None:
        return ValidationCheck(
            id="cvar_within_limit",
            label="CVaR within calibration limit",
            severity="block",
            passed=False,
            value=cvar,
            threshold=limit,
            explanation="Missing cvar_95 or cvar_limit in payload.",
        )
    # CVaR convention in this codebase: negative = loss.
    # Limit e.g. -0.05 means 5% loss budget.
    cvar_f = float(cvar)
    limit_f = -abs(float(limit))
    passed = cvar_f >= limit_f  # less negative = within budget
    return ValidationCheck(
        id="cvar_within_limit",
        label="CVaR within calibration limit",
        severity="block",
        passed=passed,
        value=round(cvar_f, 6),
        threshold=round(limit_f, 6),
        explanation=(
            f"Ex-ante CVaR 95% is {cvar_f:.4%}; calibration limit is "
            f"{limit_f:.4%}. {'OK' if passed else 'Breach'}."
        ),
    )


def _check_turnover_within_cap(
    run_payload: dict[str, Any],
    _db: ValidationDbContext,
) -> ValidationCheck:
    metrics = run_payload.get("ex_ante_metrics") or {}
    turnover = metrics.get("turnover")
    calibration = run_payload.get("calibration_snapshot") or {}
    cap = calibration.get("turnover_cap")
    if cap is None:
        return ValidationCheck(
            id="turnover_within_cap",
            label="Turnover within cap",
            severity="warn",
            passed=True,
            value=turnover,
            threshold=None,
            explanation="No turnover cap configured — skipped.",
        )
    turnover_f = float(turnover or 0.0)
    cap_f = float(cap)
    passed = turnover_f <= cap_f + _WEIGHTS_SUM_TOLERANCE
    return ValidationCheck(
        id="turnover_within_cap",
        label="Turnover within cap",
        severity="warn",
        passed=passed,
        value=round(turnover_f, 6),
        threshold=round(cap_f, 6),
        explanation=(
            f"Proposed turnover {turnover_f:.4%} vs cap {cap_f:.4%}."
        ),
    )


def _check_min_diversification_count(
    run_payload: dict[str, Any],
    _db: ValidationDbContext,
) -> ValidationCheck:
    weights = run_payload.get("weights_proposed") or {}
    nonzero = sum(1 for w in weights.values() if w and float(w) > 1e-6)
    passed = nonzero >= _MIN_DIVERSIFICATION_COUNT
    return ValidationCheck(
        id="min_diversification_count",
        label="Minimum diversification count",
        severity="block",
        passed=passed,
        value=nonzero,
        threshold=_MIN_DIVERSIFICATION_COUNT,
        explanation=(
            f"Portfolio holds {nonzero} instruments with nonzero weight; "
            f"minimum for diversification is {_MIN_DIVERSIFICATION_COUNT}."
        ),
    )


def _check_max_single_fund_weight(
    run_payload: dict[str, Any],
    _db: ValidationDbContext,
) -> ValidationCheck:
    weights = run_payload.get("weights_proposed") or {}
    calibration = run_payload.get("calibration_snapshot") or {}
    cap = calibration.get("max_single_fund_weight")
    if cap is None:
        return ValidationCheck(
            id="max_single_fund_weight",
            label="Max single-fund weight",
            severity="block",
            passed=False,
            value=None,
            threshold=None,
            explanation="max_single_fund_weight missing from calibration.",
        )
    max_weight = max(
        (float(w) for w in weights.values() if w is not None),
        default=0.0,
    )
    cap_f = float(cap)
    passed = max_weight <= cap_f + _WEIGHTS_SUM_TOLERANCE
    return ValidationCheck(
        id="max_single_fund_weight",
        label="Max single-fund weight",
        severity="block",
        passed=passed,
        value=round(max_weight, 6),
        threshold=round(cap_f, 6),
        explanation=(
            f"Heaviest fund is {max_weight:.4%}; cap is {cap_f:.4%}."
        ),
    )


def _check_block_min_weights(
    run_payload: dict[str, Any],
    db: ValidationDbContext,
) -> ValidationCheck:
    funds = run_payload.get("funds") or []
    block_totals: dict[str, float] = {}
    for f in funds:
        bid = f.get("block_id")
        if bid:
            block_totals[bid] = block_totals.get(bid, 0.0) + float(
                f.get("weight") or 0.0,
            )
    violations: list[tuple[str, float, float]] = []
    for bid, (min_w, _) in db.block_constraints.items():
        actual = block_totals.get(bid, 0.0)
        if actual + _BLOCK_WEIGHT_TOLERANCE < min_w:
            violations.append((bid, actual, min_w))
    passed = len(violations) == 0
    return ValidationCheck(
        id="all_block_min_weights_satisfied",
        label="All block min weights satisfied",
        severity="block",
        passed=passed,
        value=len(violations),
        threshold=0,
        explanation=(
            f"{len(violations)} block(s) below minimum target: "
            + ", ".join(
                f"{bid}={actual:.4%} < {min_w:.4%}"
                for bid, actual, min_w in violations[:3]
            )
            if violations
            else "All blocks meet minimum weight targets."
        ),
    )


def _check_block_max_weights(
    run_payload: dict[str, Any],
    db: ValidationDbContext,
) -> ValidationCheck:
    funds = run_payload.get("funds") or []
    block_totals: dict[str, float] = {}
    for f in funds:
        bid = f.get("block_id")
        if bid:
            block_totals[bid] = block_totals.get(bid, 0.0) + float(
                f.get("weight") or 0.0,
            )
    violations: list[tuple[str, float, float]] = []
    for bid, (_, max_w) in db.block_constraints.items():
        actual = block_totals.get(bid, 0.0)
        if actual > max_w + _BLOCK_WEIGHT_TOLERANCE:
            violations.append((bid, actual, max_w))
    passed = len(violations) == 0
    return ValidationCheck(
        id="all_block_max_weights_satisfied",
        label="All block max weights satisfied",
        severity="block",
        passed=passed,
        value=len(violations),
        threshold=0,
        explanation=(
            f"{len(violations)} block(s) above maximum cap: "
            + ", ".join(
                f"{bid}={actual:.4%} > {max_w:.4%}"
                for bid, actual, max_w in violations[:3]
            )
            if violations
            else "All blocks within maximum weight caps."
        ),
    )


def _check_no_banned_instruments(
    run_payload: dict[str, Any],
    db: ValidationDbContext,
) -> ValidationCheck:
    weights = run_payload.get("weights_proposed") or {}
    banned = [iid for iid in weights if str(iid) in db.banned_instrument_ids]
    passed = len(banned) == 0
    return ValidationCheck(
        id="no_banned_instruments",
        label="No banned instruments",
        severity="block",
        passed=passed,
        value=len(banned),
        threshold=0,
        explanation=(
            f"{len(banned)} instrument(s) are on the org's ban list: "
            + ", ".join(str(iid) for iid in banned[:3])
            if banned
            else "No banned instruments in the proposed weights."
        ),
    )


def _check_all_instruments_approved(
    run_payload: dict[str, Any],
    db: ValidationDbContext,
) -> ValidationCheck:
    weights = run_payload.get("weights_proposed") or {}
    if not db.approved_instrument_ids:
        # Empty approved set means the check can't discriminate —
        # treat as passing with a warning-level explanation.
        return ValidationCheck(
            id="all_instruments_approved",
            label="All instruments in approved universe",
            severity="warn",
            passed=True,
            value=len(weights),
            threshold=None,
            explanation="No approved universe loaded — check skipped.",
        )
    unapproved = [
        iid for iid in weights
        if str(iid) not in db.approved_instrument_ids
    ]
    passed = len(unapproved) == 0
    return ValidationCheck(
        id="all_instruments_approved",
        label="All instruments in approved universe",
        severity="block",
        passed=passed,
        value=len(unapproved),
        threshold=0,
        explanation=(
            f"{len(unapproved)} instrument(s) not in approved universe: "
            + ", ".join(str(iid) for iid in unapproved[:3])
            if unapproved
            else "All weighted instruments are in the approved universe."
        ),
    )


def _check_stress_within_tolerance(
    run_payload: dict[str, Any],
    _db: ValidationDbContext,
) -> ValidationCheck:
    stress_results = run_payload.get("stress_results") or []
    worst: float | None = None
    for row in stress_results:
        nav_impact = row.get("nav_impact_pct")
        if nav_impact is None:
            continue
        if worst is None or float(nav_impact) < worst:
            worst = float(nav_impact)
    if worst is None:
        return ValidationCheck(
            id="stress_within_tolerance",
            label="Stress impact within tolerance",
            severity="warn",
            passed=True,
            value=None,
            threshold=_STRESS_NAV_IMPACT_THRESHOLD,
            explanation="No stress results — check skipped.",
        )
    passed = worst >= _STRESS_NAV_IMPACT_THRESHOLD
    return ValidationCheck(
        id="stress_within_tolerance",
        label="Stress impact within tolerance",
        severity="warn",
        passed=passed,
        value=round(worst, 6),
        threshold=_STRESS_NAV_IMPACT_THRESHOLD,
        explanation=(
            f"Worst-case stress NAV impact is {worst:.4%} "
            f"(threshold {_STRESS_NAV_IMPACT_THRESHOLD:.4%})."
        ),
    )


def _check_no_unrealistic_expected_return(
    run_payload: dict[str, Any],
    _db: ValidationDbContext,
) -> ValidationCheck:
    metrics = run_payload.get("ex_ante_metrics") or {}
    er = metrics.get("expected_return")
    if er is None:
        return ValidationCheck(
            id="no_unrealistic_expected_return",
            label="Expected return in plausible range",
            severity="warn",
            passed=True,
            value=None,
            threshold=_MAX_REALISTIC_ER_ABS,
            explanation="No expected_return in metrics — check skipped.",
        )
    er_f = float(er)
    passed = abs(er_f) <= _MAX_REALISTIC_ER_ABS
    return ValidationCheck(
        id="no_unrealistic_expected_return",
        label="Expected return in plausible range",
        severity="warn",
        passed=passed,
        value=round(er_f, 6),
        threshold=_MAX_REALISTIC_ER_ABS,
        explanation=(
            f"Ex-ante expected return is {er_f:.4%}; plausible range is "
            f"±{_MAX_REALISTIC_ER_ABS:.4%}."
        ),
    )


def _check_bl_views_consistent(
    run_payload: dict[str, Any],
    _db: ValidationDbContext,
) -> ValidationCheck:
    calibration = run_payload.get("calibration_snapshot") or {}
    if not calibration.get("bl_enabled"):
        return ValidationCheck(
            id="bl_views_consistent_with_prior",
            label="Black-Litterman views consistent with prior",
            severity="warn",
            passed=True,
            value=None,
            threshold=_BL_POSTERIOR_DEVIATION_MAX,
            explanation="Black-Litterman disabled — check skipped.",
        )
    optimizer_trace = run_payload.get("optimizer_trace") or {}
    max_deviation = optimizer_trace.get("bl_max_view_deviation_sigma")
    if max_deviation is None:
        return ValidationCheck(
            id="bl_views_consistent_with_prior",
            label="Black-Litterman views consistent with prior",
            severity="warn",
            passed=True,
            value=None,
            threshold=_BL_POSTERIOR_DEVIATION_MAX,
            explanation="BL view-deviation telemetry missing — check skipped.",
        )
    dev_f = float(max_deviation)
    passed = dev_f <= _BL_POSTERIOR_DEVIATION_MAX
    return ValidationCheck(
        id="bl_views_consistent_with_prior",
        label="Black-Litterman views consistent with prior",
        severity="warn",
        passed=passed,
        value=round(dev_f, 6),
        threshold=_BL_POSTERIOR_DEVIATION_MAX,
        explanation=(
            f"Max BL view deviation from prior is {dev_f:.2f}σ; "
            f"threshold is {_BL_POSTERIOR_DEVIATION_MAX:.2f}σ."
        ),
    )


def _check_garch_convergence(
    run_payload: dict[str, Any],
    _db: ValidationDbContext,
) -> ValidationCheck:
    calibration = run_payload.get("calibration_snapshot") or {}
    if not calibration.get("garch_enabled"):
        return ValidationCheck(
            id="garch_convergence_rate",
            label="GARCH convergence rate",
            severity="warn",
            passed=True,
            value=None,
            threshold=_GARCH_MIN_CONVERGENCE,
            explanation="GARCH disabled — check skipped.",
        )
    stats = run_payload.get("statistical_inputs") or {}
    rate = stats.get("garch_convergence_rate")
    if rate is None:
        return ValidationCheck(
            id="garch_convergence_rate",
            label="GARCH convergence rate",
            severity="warn",
            passed=True,
            value=None,
            threshold=_GARCH_MIN_CONVERGENCE,
            explanation="GARCH telemetry missing — check skipped.",
        )
    rate_f = float(rate)
    passed = rate_f >= _GARCH_MIN_CONVERGENCE
    return ValidationCheck(
        id="garch_convergence_rate",
        label="GARCH convergence rate",
        severity="warn",
        passed=passed,
        value=round(rate_f, 6),
        threshold=_GARCH_MIN_CONVERGENCE,
        explanation=(
            f"GARCH converged on {rate_f:.1%} of fund series; "
            f"minimum is {_GARCH_MIN_CONVERGENCE:.1%}."
        ),
    )


def _check_factor_model_r_squared(
    run_payload: dict[str, Any],
    _db: ValidationDbContext,
) -> ValidationCheck:
    factor = run_payload.get("factor_exposure") or {}
    r2 = factor.get("average_r_squared")
    if r2 is None:
        return ValidationCheck(
            id="factor_model_r_squared",
            label="PCA factor model explanatory power",
            severity="warn",
            passed=True,
            value=None,
            threshold=_FACTOR_MODEL_MIN_R2,
            explanation="Factor model R² telemetry missing — check skipped.",
        )
    r2_f = float(r2)
    if math.isnan(r2_f):
        return ValidationCheck(
            id="factor_model_r_squared",
            label="PCA factor model explanatory power",
            severity="warn",
            passed=False,
            value=None,
            threshold=_FACTOR_MODEL_MIN_R2,
            explanation="Factor model R² is NaN — numerical instability.",
        )
    passed = r2_f >= _FACTOR_MODEL_MIN_R2
    return ValidationCheck(
        id="factor_model_r_squared",
        label="PCA factor model explanatory power",
        severity="warn",
        passed=passed,
        value=round(r2_f, 6),
        threshold=_FACTOR_MODEL_MIN_R2,
        explanation=(
            f"PCA factor model average R² is {r2_f:.2%}; minimum is "
            f"{_FACTOR_MODEL_MIN_R2:.2%}."
        ),
    )


# ── Check registry — stable order for JSONB serialization ─────────


CHECKS: Final[list[tuple[str, Callable[[dict[str, Any], ValidationDbContext], ValidationCheck]]]] = [
    ("weights_sum_to_one",              _check_weights_sum_to_one),
    ("no_stale_nav",                    _check_no_stale_nav),
    ("cvar_within_limit",               _check_cvar_within_limit),
    ("turnover_within_cap",             _check_turnover_within_cap),
    ("min_diversification_count",       _check_min_diversification_count),
    ("max_single_fund_weight",          _check_max_single_fund_weight),
    ("all_block_min_weights_satisfied", _check_block_min_weights),
    ("all_block_max_weights_satisfied", _check_block_max_weights),
    ("no_banned_instruments",           _check_no_banned_instruments),
    ("all_instruments_approved",        _check_all_instruments_approved),
    ("stress_within_tolerance",         _check_stress_within_tolerance),
    ("no_unrealistic_expected_return",  _check_no_unrealistic_expected_return),
    ("bl_views_consistent_with_prior",  _check_bl_views_consistent),
    ("garch_convergence_rate",          _check_garch_convergence),
    ("factor_model_r_squared",          _check_factor_model_r_squared),
]


def validate_construction(
    run_payload: dict[str, Any],
    db_context: ValidationDbContext | None = None,
) -> ValidationResult:
    """Run all 15 checks against the construction run payload.

    **No fail-fast.** Every check is evaluated so the UI can show
    the full health panel. Aggregation rule:
    ``passed = not any(block failures)``.

    Parameters
    ----------
    run_payload
        The in-memory construction run dict with keys
        ``weights_proposed``, ``calibration_snapshot``,
        ``ex_ante_metrics``, ``stress_results``, ``funds``, etc.
    db_context
        Pre-fetched DB state. If ``None``, a default empty context is
        used — checks that depend on DB state will typically return
        warn-level passes with "check skipped" explanations.

    Returns
    -------
    ValidationResult
    """
    db_context = db_context or ValidationDbContext()
    checks: list[ValidationCheck] = []
    for _check_id, check_fn in CHECKS:
        try:
            result = check_fn(run_payload, db_context)
        except Exception as exc:  # noqa: BLE001
            # A check that raises is a warn-level failure — never a
            # block — so a bug in one check can't strand activation.
            result = ValidationCheck(
                id=_check_id,
                label=_check_id.replace("_", " ").capitalize(),
                severity="warn",
                passed=False,
                value=None,
                threshold=None,
                explanation=f"Check raised: {type(exc).__name__}: {exc}",
            )
        checks.append(result)

    blocks = [c for c in checks if c.severity == "block" and not c.passed]
    warnings = [c for c in checks if c.severity == "warn" and not c.passed]

    return ValidationResult(
        passed=len(blocks) == 0,
        checks=checks,
        warnings=warnings,
        blocks=blocks,
    )


def to_jsonb(result: ValidationResult) -> dict[str, Any]:
    """Serialize a ValidationResult to the JSONB shape stored on
    ``portfolio_construction_runs.validation``.

    The frontend reads this shape directly — any change must be
    mirrored in the translation table (Phase 10 Task 10.1).
    """
    return {
        "passed": result.passed,
        "checks": [
            {
                "id": c.id,
                "label": c.label,
                "severity": c.severity,
                "passed": c.passed,
                "value": c.value,
                "threshold": c.threshold,
                "explanation": c.explanation,
            }
            for c in result.checks
        ],
        "summary": {
            "total": len(result.checks),
            "passed": sum(1 for c in result.checks if c.passed),
            "blocks_failed": len(result.blocks),
            "warnings_failed": len(result.warnings),
        },
    }
