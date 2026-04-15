"""
Style drift analyzer.

Compares a fund's current ``HoldingsAnalysis`` against the mean of its
historical quarterly compositions and emits a drift signal. Designed as
a complementary measure to the existing performance-metric drift
(``strategy_drift_alerts`` populated by the strategy-drift scan route),
which detects changes in volatility / Sharpe / drawdown via z-scores.

Style drift detects changes in *what the fund holds*:
  • Asset-mix shifts        (e.g., 80% equity → 60% equity / 40% bonds)
  • FI subtype shifts        (e.g., Treasuries → corporates within FI)
  • Geography shifts         (e.g., US → emerging markets)
  • Issuer-category shifts   (diagnostic — based on N-PORT issuerCat,
    not GICS, so kept at low weight in the composite score)

This is the institutional-grade signal Morningstar charges for under
"Style Drift" — a fund that gradually morphs its mandate without a
formal prospectus update. Operators want this surfaced because it
breaks peer-group comparison, allocation block mapping, and IC
expectations downstream.

Coupling to the FI-only Layer 0 classifier (Sprint B):
  • The classifier rejects equity-side composition inference because
    of structural data limits (ADR confounder, no GICS, etc.).
  • Style drift is unaffected by those limits — it's a *delta* signal
    over time, not an absolute classification. A fund's GICS-less
    issuer-category distribution at T1 vs T8 is still a valid drift
    indicator even when the absolute mix isn't interpretable.
  • Severity thresholds and the worker's CIK guard mirror the
    classifier's posture: only run drift on coherent, single-fund
    CIKs. Trust-CIK aggregations are skipped to avoid noise.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from statistics import mean

from app.domains.wealth.services.holdings_analyzer import HoldingsAnalysis

# Minimum historical quarters required for a meaningful drift signal.
# Below this, the result is "insufficient_data" with composite_drift=0.
_MIN_HISTORICAL_QUARTERS = 4

# Composite weights — sum to 1.0. Asset-mix and FI subtype carry the
# most weight because they're derived from clean signals (asset_class
# bucketing, issuerCat). Geography is next (ISIN-based, ADR-confounded
# but still reliable for non-equity sleeves). Issuer-category is last
# (diagnostic only because issuerCat is N-PORT, not GICS).
_WEIGHTS: dict[str, float] = {
    "asset_mix": 0.40,
    "fi_subtype": 0.30,
    "geography": 0.20,
    "issuer_category": 0.10,
}

# Severity thresholds on the composite score (0-100 scale). Match the
# 3-level convention used by the existing strategy_drift_alerts schema.
_SEVERITY_MODERATE = 10.0
_SEVERITY_SEVERE = 25.0


@dataclass(frozen=True)
class StyleDriftResult:
    """Drift signal between a current snapshot and historical mean."""

    instrument_id: str
    current_date: date
    historical_window_quarters: int

    # Per-dimension L2 distances (0-100 scale)
    asset_mix_drift: float
    fi_subtype_drift: float
    geography_drift: float
    issuer_category_drift: float

    # Weighted composite (0-100 scale)
    composite_drift: float

    # Status mirrors strategy_drift_alerts CHECK constraint
    status: str    # "stable" | "drift_detected" | "insufficient_data"
    severity: str  # "none" | "moderate" | "severe"

    # Top 3 contributing dimensions (by weighted contribution)
    drivers: list[str]


def compute_style_drift(
    current: HoldingsAnalysis,
    historical: list[HoldingsAnalysis],
    *,
    instrument_id: str,
) -> StyleDriftResult:
    """Compare current composition against historical mean.

    Args:
        current: Latest ``HoldingsAnalysis`` for the fund.
        historical: List of ``HoldingsAnalysis`` for prior quarters,
            most-recent-first ordering not required (we average). Need
            at least ``_MIN_HISTORICAL_QUARTERS`` (4) for a meaningful
            signal.
        instrument_id: UUID string of the fund (for downstream JOIN to
            ``instruments_universe``).

    Returns:
        ``StyleDriftResult`` with severity "none" when historical
        sample is insufficient, otherwise composite_drift in 0-100.
    """
    if len(historical) < _MIN_HISTORICAL_QUARTERS:
        return _insufficient_history(current, instrument_id, len(historical))

    # ── Per-dimension L2 distances ──
    asset_drift = _l2_distance(
        (current.equity_pct, current.fixed_income_pct, current.cash_pct,
         current.derivatives_pct, current.other_pct),
        _mean_tuple(historical, [
            "equity_pct", "fixed_income_pct", "cash_pct",
            "derivatives_pct", "other_pct",
        ]),
    )
    fi_drift = _l2_distance(
        (current.fi_government_pct, current.fi_municipal_pct,
         current.fi_corporate_pct, current.fi_mbs_pct, current.fi_abs_pct),
        _mean_tuple(historical, [
            "fi_government_pct", "fi_municipal_pct", "fi_corporate_pct",
            "fi_mbs_pct", "fi_abs_pct",
        ]),
    )
    geo_drift = _l2_distance(
        (current.geography_us_pct, current.geography_europe_pct,
         current.geography_asia_developed_pct, current.geography_em_pct,
         current.geography_other_pct),
        _mean_tuple(historical, [
            "geography_us_pct", "geography_europe_pct",
            "geography_asia_developed_pct", "geography_em_pct",
            "geography_other_pct",
        ]),
    )
    issuer_drift = _issuer_category_drift(current, historical)

    # ── Weighted composite ──
    contributions = {
        "asset_mix": asset_drift * _WEIGHTS["asset_mix"],
        "fi_subtype": fi_drift * _WEIGHTS["fi_subtype"],
        "geography": geo_drift * _WEIGHTS["geography"],
        "issuer_category": issuer_drift * _WEIGHTS["issuer_category"],
    }
    composite = sum(contributions.values())

    # ── Severity ──
    if composite < _SEVERITY_MODERATE:
        severity = "none"
        status = "stable"
    elif composite < _SEVERITY_SEVERE:
        severity = "moderate"
        status = "drift_detected"
    else:
        severity = "severe"
        status = "drift_detected"

    drivers = [
        d[0] for d in
        sorted(contributions.items(), key=lambda x: -x[1])[:3]
    ]

    return StyleDriftResult(
        instrument_id=instrument_id,
        current_date=current.as_of_date,
        historical_window_quarters=len(historical),
        asset_mix_drift=asset_drift,
        fi_subtype_drift=fi_drift,
        geography_drift=geo_drift,
        issuer_category_drift=issuer_drift,
        composite_drift=composite,
        status=status,
        severity=severity,
        drivers=drivers,
    )


# ── Helpers ────────────────────────────────────────────────────────


def _l2_distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def _mean_tuple(
    historical: list[HoldingsAnalysis], attrs: list[str],
) -> tuple[float, ...]:
    return tuple(
        mean(getattr(h, attr) for h in historical) for attr in attrs
    )


def _issuer_category_drift(
    current: HoldingsAnalysis, historical: list[HoldingsAnalysis],
) -> float:
    """L2 drift on the issuerCat distribution within the equity sleeve.

    Diagnostic only — issuerCat is not GICS, so absolute concentration
    isn't interpretable, but a *change* in the distribution over time
    is still a valid drift indicator (e.g., a fund that switches from
    holding mostly CORP-tagged to mostly RF-tagged holdings has shifted
    its underlying sleeve, even if we can't say to *what*).
    """
    curr_pcts: dict[str, float] = dict(current.top_issuer_categories[:5])
    hist_means: dict[str, float] = {}
    n = len(historical)
    for h in historical:
        for name, pct in h.top_issuer_categories[:5]:
            hist_means[name] = hist_means.get(name, 0.0) + pct / n

    universe = set(curr_pcts.keys()) | set(hist_means.keys())
    return math.sqrt(sum(
        (curr_pcts.get(c, 0.0) - hist_means.get(c, 0.0)) ** 2
        for c in universe
    ))


def _insufficient_history(
    current: HoldingsAnalysis, instrument_id: str, n: int,
) -> StyleDriftResult:
    return StyleDriftResult(
        instrument_id=instrument_id,
        current_date=current.as_of_date,
        historical_window_quarters=n,
        asset_mix_drift=0.0,
        fi_subtype_drift=0.0,
        geography_drift=0.0,
        issuer_category_drift=0.0,
        composite_drift=0.0,
        status="insufficient_data",
        severity="none",
        drivers=[],
    )
