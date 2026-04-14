"""Backtest regime weight profiles against historical macro_data.

Compares three weight profiles across four crisis periods:
- Static (old 55/45, 9 signals, no amplification)
- Profile A (40/60, 12 signals, dynamic amplification)
- Profile B (25/75, 12 signals, dynamic amplification)

Usage:
    python -m scripts.backtest_regime_weights
"""

from __future__ import annotations

import asyncio
import csv
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory
from app.shared.models import MacroData
from quant_engine.regime_service import (
    _amplify_weights,
    _compute_credit_impulse,
    _compute_icsa_zscore,
    _compute_permits_roc,
    _compute_series_roc,
    _compute_series_zscore,
    _ramp,
)

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Weight profiles
# ---------------------------------------------------------------------------

# Static (old 55/45) — 9 signals, no ICSA/credit_impulse/permits
STATIC_WEIGHTS: dict[str, float] = {
    "vix": 0.15,
    "hy_oas": 0.15,
    "baa_spread": 0.10,
    "yield_curve": 0.10,
    "dxy": 0.05,
    "energy_shock": 0.10,
    "cfnai": 0.15,
    "sahm": 0.10,
    "ff_roc": 0.05,
}

# Profile A (40/60) — 12 signals
PROFILE_A_WEIGHTS: dict[str, float] = {
    "vix": 0.10,
    "hy_oas": 0.12,
    "baa_spread": 0.05,
    "yield_curve": 0.05,
    "dxy": 0.08,
    "energy_shock": 0.12,
    "cfnai": 0.18,
    "sahm": 0.08,
    "ff_roc": 0.05,
    "icsa": 0.08,
    "credit_impulse": 0.05,
    "permits": 0.04,
}

# Profile B (25/75) — 12 signals, heavy real-economy
PROFILE_B_WEIGHTS: dict[str, float] = {
    "vix": 0.05,
    "hy_oas": 0.07,
    "baa_spread": 0.03,
    "yield_curve": 0.06,
    "dxy": 0.05,
    "energy_shock": 0.05,
    "cfnai": 0.22,
    "sahm": 0.10,
    "ff_roc": 0.06,
    "icsa": 0.12,
    "credit_impulse": 0.10,
    "permits": 0.09,
}

# Ramp parameters for each signal (calm, panic)
RAMP_PARAMS: dict[str, tuple[float, float]] = {
    "vix": (18.0, 35.0),
    "hy_oas": (2.5, 6.0),
    "baa_spread": (1.2, 2.5),
    "yield_curve": (-1.0, 0.5),      # inverted
    "dxy": (0.0, 2.0),
    "energy_shock": (0.0, 100.0),
    "cfnai": (0.20, 0.70),           # inverted
    "sahm": (0.0, 0.50),
    "ff_roc": (-0.50, 1.50),
    "icsa": (0.5, 2.5),
    "credit_impulse": (-0.5, 2.0),   # inverted
    "permits": (-5.0, 20.0),         # inverted
}

# Signals that use inverted values for _ramp
INVERTED_SIGNALS = {"yield_curve", "cfnai", "credit_impulse", "permits"}

# Backtest periods — constrained to macro_data availability (2016+).
# GFC (2007) and Oil Crash (2014) excluded: no FRED data prior to 2016.
# Substituted with Q4 2018 Correction and 2023 SVB Banking Crisis.
BACKTEST_PERIODS = [
    ("Q4 2018 Correction", date(2018, 9, 1), date(2019, 3, 31)),
    ("COVID", date(2019, 9, 1), date(2020, 6, 30)),
    ("Ukraine/Energy", date(2022, 1, 1), date(2022, 12, 31)),
    ("2023 SVB Crisis", date(2023, 1, 1), date(2023, 9, 30)),
    ("Oil Decline 2018", date(2018, 6, 1), date(2019, 1, 31)),
]

# NBER recession periods for lead-time analysis
NBER_RECESSIONS = [
    (date(2020, 2, 1), date(2020, 4, 30)),   # COVID recession
]

# Approximate market trough dates (S&P 500)
MARKET_TROUGHS = {
    "Q4 2018 Correction": date(2018, 12, 24),
    "COVID": date(2020, 3, 23),
    "Ukraine/Energy": date(2022, 10, 12),
    "2023 SVB Crisis": date(2023, 3, 13),
    "Oil Decline 2018": date(2018, 12, 24),  # WTI bottomed ~$42
}


@dataclass
class SignalSnapshot:
    """All signal values for a single date."""
    dt: date
    vix: float | None = None
    hy_oas: float | None = None
    baa_spread: float | None = None
    yield_curve: float | None = None
    dxy: float | None = None
    energy_shock: float | None = None
    cfnai: float | None = None
    sahm: float | None = None
    ff_roc: float | None = None
    icsa: float | None = None
    credit_impulse: float | None = None
    permits: float | None = None


@dataclass
class ClassificationResult:
    regime: str
    score: float
    n_signals: int


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------

async def _build_signals_for_date(
    db: AsyncSession, target_date: date,
) -> SignalSnapshot:
    """Build all signal values for a historical date.

    Bypasses staleness checks (irrelevant for backtesting).
    """
    snap = SignalSnapshot(dt=target_date)

    # Bulk-fetch latest raw values at target_date
    series_ids = [
        "VIXCLS", "DGS10", "DGS2", "CPIAUCSL", "SAHMREALTIME",
        "BAMLH0A0HYM2", "BAA10Y", "DFF", "DTWEXBGS", "DCOILWTICO", "CFNAI",
    ]
    stmt = (
        select(MacroData.series_id, MacroData.value)
        .where(MacroData.series_id.in_(series_ids))
        .where(MacroData.obs_date <= target_date)
        .where(MacroData.value.is_not(None))
        .distinct(MacroData.series_id)
        .order_by(MacroData.series_id, MacroData.obs_date.desc())
    )
    rows = (await db.execute(stmt)).all()
    latest: dict[str, float] = {r[0]: float(r[1]) for r in rows}

    # VIX
    snap.vix = latest.get("VIXCLS")

    # HY OAS
    snap.hy_oas = latest.get("BAMLH0A0HYM2")

    # BAA-10Y
    snap.baa_spread = latest.get("BAA10Y")

    # Yield curve
    dgs10 = latest.get("DGS10")
    dgs2 = latest.get("DGS2")
    if dgs10 is not None and dgs2 is not None:
        snap.yield_curve = dgs10 - dgs2

    # CFNAI
    snap.cfnai = latest.get("CFNAI")

    # Sahm Rule
    snap.sahm = latest.get("SAHMREALTIME")

    # DXY Z-score
    snap.dxy = await _compute_series_zscore(
        db, "DTWEXBGS", lookback_days=252, as_of_date=target_date,
    )

    # Energy Shock Composite
    crude_z = await _compute_series_zscore(
        db, "DCOILWTICO", lookback_days=252, as_of_date=target_date,
    )
    crude_roc = await _compute_series_roc(
        db, "DCOILWTICO", months=3, as_of_date=target_date,
    )
    if crude_z is not None or crude_roc is not None:
        z_score = _ramp(crude_z, calm=0.5, panic=3.0) if crude_z is not None else 0.0
        roc_score = _ramp(crude_roc, calm=0.0, panic=50.0) if crude_roc is not None else 0.0
        snap.energy_shock = max(z_score, roc_score)

    # Fed Funds delta 6m
    from quant_engine.regime_service import _compute_ff_delta_6m
    snap.ff_roc = await _compute_ff_delta_6m(db, as_of_date=target_date)

    # ICSA Z-score
    snap.icsa = await _compute_icsa_zscore(db, as_of_date=target_date)

    # Credit Impulse
    snap.credit_impulse = await _compute_credit_impulse(db, as_of_date=target_date)

    # Building Permits RoC
    snap.permits = await _compute_permits_roc(db, as_of_date=target_date)

    return snap


def _compute_sub_score(signal_name: str, value: float) -> float:
    """Compute sub-score 0-100 for a signal value."""
    calm, panic = RAMP_PARAMS[signal_name]
    if signal_name in INVERTED_SIGNALS:
        return _ramp(-value, calm=calm, panic=panic)
    return _ramp(value, calm=calm, panic=panic)


def _classify_with_profile(
    snap: SignalSnapshot,
    weights: dict[str, float],
    use_amplification: bool = False,
    alpha: float = 2.0,
    gamma: float = 2.0,
    w_max: float = 0.35,
) -> ClassificationResult:
    """Classify regime using a specific weight profile."""
    # Build available signals
    signal_values: dict[str, float] = {}
    for name in weights:
        val = getattr(snap, name, None)
        if val is not None:
            signal_values[name] = val

    if len(signal_values) < 2:
        return ClassificationResult(regime="RISK_OFF", score=50.0, n_signals=len(signal_values))

    # Compute sub-scores and build signal tuples
    signals: list[tuple[str, float, float, str]] = []
    for name, val in signal_values.items():
        sub_score = _compute_sub_score(name, val)
        signals.append((name, sub_score, weights[name], ""))

    # Renormalize weights for available signals
    w_sum = sum(w for _, _, w, _ in signals)
    if w_sum > 0 and abs(w_sum - 1.0) > 0.001:
        signals = [(l, s, w / w_sum, r) for l, s, w, r in signals]

    # Apply dynamic amplification
    if use_amplification:
        signals = _amplify_weights(signals, alpha=alpha, gamma=gamma, w_max=w_max)

    # Compute composite
    stress = sum(s * w for _, s, w, _ in signals)
    stress = round(min(100.0, max(0.0, stress)), 1)

    # Classify
    if stress >= 50:
        regime = "CRISIS"
    elif stress >= 25:
        regime = "RISK_OFF"
    else:
        regime = "RISK_ON"

    return ClassificationResult(regime=regime, score=stress, n_signals=len(signals))


# ---------------------------------------------------------------------------
# Main backtest
# ---------------------------------------------------------------------------

async def run_backtest(db: AsyncSession) -> list[dict]:
    """Run backtest across all periods, return row dicts."""
    all_rows: list[dict] = []

    for period_name, start, end in BACKTEST_PERIODS:
        logger.info("Backtesting period", period=period_name, start=str(start), end=str(end))

        # Generate monthly dates
        current = start
        while current <= end:
            snap = await _build_signals_for_date(db, current)

            static = _classify_with_profile(snap, STATIC_WEIGHTS, use_amplification=False)
            prof_a = _classify_with_profile(snap, PROFILE_A_WEIGHTS, use_amplification=True)
            prof_b = _classify_with_profile(snap, PROFILE_B_WEIGHTS, use_amplification=True)

            row = {
                "period": period_name,
                "date": current.isoformat(),
                "static_regime": static.regime,
                "static_score": static.score,
                "static_signals": static.n_signals,
                "profile_a_regime": prof_a.regime,
                "profile_a_score": prof_a.score,
                "profile_a_signals": prof_a.n_signals,
                "profile_b_regime": prof_b.regime,
                "profile_b_score": prof_b.score,
                "profile_b_signals": prof_b.n_signals,
                # Raw signal values for analysis
                "vix": snap.vix,
                "hy_oas": snap.hy_oas,
                "energy_shock": snap.energy_shock,
                "cfnai": snap.cfnai,
                "sahm": snap.sahm,
                "icsa": snap.icsa,
                "credit_impulse": snap.credit_impulse,
                "permits": snap.permits,
            }
            all_rows.append(row)

            logger.info(
                "classified",
                date=current.isoformat(),
                static=f"{static.regime}({static.score:.0f})",
                prof_a=f"{prof_a.regime}({prof_a.score:.0f})",
                prof_b=f"{prof_b.regime}({prof_b.score:.0f})",
                vix=snap.vix,
                energy=snap.energy_shock,
            )

            # Advance 1 month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

    return all_rows


def _write_csv(rows: list[dict], path: Path) -> None:
    """Write backtest results to CSV."""
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("CSV written", path=str(path), n_rows=len(rows))


def _analyze_results(rows: list[dict]) -> str:
    """Generate markdown analysis of backtest results."""
    lines: list[str] = []
    lines.append("# Regime Backtest Results")
    lines.append("")
    lines.append(f"**Generated:** {date.today().isoformat()}")
    lines.append(f"**Total observations:** {len(rows)}")
    lines.append("")

    # Group by period
    periods: dict[str, list[dict]] = {}
    for r in rows:
        periods.setdefault(r["period"], []).append(r)

    for period_name, period_rows in periods.items():
        lines.append(f"## {period_name}")
        lines.append("")

        # Regime distribution per profile
        for profile_key, profile_name in [
            ("static", "Static (55/45)"),
            ("profile_a", "Profile A (40/60)"),
            ("profile_b", "Profile B (25/75)"),
        ]:
            regime_counts: dict[str, int] = {}
            scores: list[float] = []
            for r in period_rows:
                regime = r[f"{profile_key}_regime"]
                regime_counts[regime] = regime_counts.get(regime, 0) + 1
                scores.append(r[f"{profile_key}_score"])

            avg_score = sum(scores) / len(scores) if scores else 0
            max_score = max(scores) if scores else 0

            lines.append(f"### {profile_name}")
            lines.append("")
            lines.append(f"- Avg stress: {avg_score:.1f}/100, Peak: {max_score:.1f}/100")
            dist_str = ", ".join(f"{k}: {v}" for k, v in sorted(regime_counts.items()))
            lines.append(f"- Regime distribution: {dist_str}")

            # First RISK_OFF/CRISIS date
            first_stress = None
            for r in period_rows:
                if r[f"{profile_key}_regime"] in ("RISK_OFF", "CRISIS"):
                    first_stress = r["date"]
                    break
            if first_stress:
                lines.append(f"- First stress detection: {first_stress}")

            # Regime at trough
            trough_date = MARKET_TROUGHS.get(period_name)
            if trough_date:
                closest = min(period_rows, key=lambda r: abs((date.fromisoformat(r["date"]) - trough_date).days))
                lines.append(f"- Regime at trough ({trough_date}): {closest[f'{profile_key}_regime']} ({closest[f'{profile_key}_score']:.0f})")

            lines.append("")

        # Lead time analysis for NBER recession periods
        for rec_start, rec_end in NBER_RECESSIONS:
            if period_rows[0]["date"] <= rec_start.isoformat() <= period_rows[-1]["date"]:
                lines.append(f"### Lead Time vs NBER Recession ({rec_start})")
                lines.append("")
                for profile_key, profile_name in [
                    ("static", "Static"),
                    ("profile_a", "Profile A"),
                    ("profile_b", "Profile B"),
                ]:
                    first_stress = None
                    for r in period_rows:
                        if r[f"{profile_key}_regime"] in ("RISK_OFF", "CRISIS"):
                            first_stress = date.fromisoformat(r["date"])
                            break
                    if first_stress and first_stress < rec_start:
                        lead_days = (rec_start - first_stress).days
                        lines.append(f"- **{profile_name}:** {lead_days} days lead ({first_stress})")
                    elif first_stress:
                        lag_days = (first_stress - rec_start).days
                        lines.append(f"- **{profile_name}:** {lag_days} days LATE ({first_stress})")
                    else:
                        lines.append(f"- **{profile_name}:** never detected")
                lines.append("")

        # Divergence table
        lines.append("### Monthly Timeline")
        lines.append("")
        lines.append("| Date | Static | Score | Prof A | Score | Prof B | Score | VIX | Energy | CFNAI |")
        lines.append("|------|--------|-------|--------|-------|--------|-------|-----|--------|-------|")
        for r in period_rows:
            vix = f"{r['vix']:.1f}" if r['vix'] is not None else "N/A"
            energy = f"{r['energy_shock']:.0f}" if r['energy_shock'] is not None else "N/A"
            cfnai = f"{r['cfnai']:+.2f}" if r['cfnai'] is not None else "N/A"
            lines.append(
                f"| {r['date']} | {r['static_regime']} | {r['static_score']:.0f} "
                f"| {r['profile_a_regime']} | {r['profile_a_score']:.0f} "
                f"| {r['profile_b_regime']} | {r['profile_b_score']:.0f} "
                f"| {vix} | {energy} | {cfnai} |"
            )
        lines.append("")

    # False positive analysis: Oil Decline 2018
    lines.append("## False Positive Analysis (Oil Decline 2018)")
    lines.append("")
    lines.append("Tests whether falling oil prices trigger false energy stress.")
    lines.append("Energy shock uses upward WTI ramps only, so falling oil should produce zero energy stress.")
    lines.append("")
    oil_rows = periods.get("Oil Decline 2018", [])
    if oil_rows:
        for profile_key, profile_name in [
            ("static", "Static"),
            ("profile_a", "Profile A"),
            ("profile_b", "Profile B"),
        ]:
            fp_months = sum(1 for r in oil_rows if r[f"{profile_key}_regime"] in ("RISK_OFF", "CRISIS"))
            lines.append(f"- **{profile_name}:** {fp_months}/{len(oil_rows)} months in RISK_OFF/CRISIS")
    lines.append("")

    return "\n".join(lines)


def _run_calibration_sweep(
    snapshots: dict[str, SignalSnapshot],
) -> str:
    """Run parameter sweep on key dates and return markdown table."""
    # Key test dates: Ukraine Mar 2022 (should be CRISIS) and SVB Mar 2023 (should NOT be CRISIS)
    ukraine_snap = snapshots.get("ukraine")
    svb_snap = snapshots.get("svb")

    if ukraine_snap is None or svb_snap is None:
        return ""

    lines: list[str] = []
    lines.append("## Calibration Sweep")
    lines.append("")
    lines.append("Parameter sweep on two discriminating dates:")
    lines.append("- **Ukraine Mar 2022** (energy=100, VIX=33) -- should be CRISIS")
    lines.append("- **SVB Mar 2023** (VIX=21, CFNAI=-0.41) -- should be RISK_OFF")
    lines.append("")
    lines.append("| alpha | gamma | w_max | Ukraine Score | Ukraine Regime | SVB Score | SVB Regime | Assessment |")
    lines.append("|-------|-------|-------|---------------|----------------|-----------|------------|------------|")

    sweep_params = [
        (1.0, 2.0, 0.35),
        (1.5, 2.0, 0.35),
        (2.0, 2.0, 0.35),  # current default
        (2.5, 2.0, 0.35),
        (3.0, 2.0, 0.35),
        (2.0, 1.0, 0.35),
        (2.0, 1.5, 0.35),
        (2.0, 2.5, 0.35),
        (2.0, 3.0, 0.35),
        (2.0, 2.0, 0.25),
        (2.0, 2.0, 0.30),
        (2.0, 2.0, 0.40),
        (2.0, 2.0, 0.50),
    ]

    for alpha, gamma, w_max in sweep_params:
        ukr = _classify_with_profile(
            ukraine_snap, PROFILE_A_WEIGHTS, use_amplification=True,
            alpha=alpha, gamma=gamma, w_max=w_max,
        )
        svb = _classify_with_profile(
            svb_snap, PROFILE_A_WEIGHTS, use_amplification=True,
            alpha=alpha, gamma=gamma, w_max=w_max,
        )

        is_default = alpha == 2.0 and gamma == 2.0 and w_max == 0.35
        ukraine_ok = ukr.regime == "CRISIS"
        svb_ok = svb.regime != "CRISIS"

        if ukraine_ok and svb_ok:
            assessment = "PASS"
        elif not ukraine_ok:
            assessment = "FAIL (misses Ukraine)"
        else:
            assessment = "FAIL (SVB false positive)"

        marker = " **<-- default**" if is_default else ""
        lines.append(
            f"| {alpha} | {gamma} | {w_max} | {ukr.score:.1f} | {ukr.regime} "
            f"| {svb.score:.1f} | {svb.regime} | {assessment}{marker} |"
        )

    lines.append("")
    return "\n".join(lines)


async def main() -> None:
    logger.info("Starting regime backtest")

    output_dir = Path(__file__).parent.parent.parent / "docs" / "reference"
    csv_path = output_dir / "regime-backtest-data.csv"
    md_path = output_dir / "regime-backtest-results.md"

    async with async_session_factory() as db:
        # Check data availability first
        stmt = (
            select(MacroData.series_id)
            .distinct()
            .where(MacroData.series_id.in_([
                "VIXCLS", "BAMLH0A0HYM2", "DCOILWTICO", "CFNAI",
                "SAHMREALTIME", "ICSA", "TOTBKCR", "PERMIT",
            ]))
        )
        available = {r[0] for r in (await db.execute(stmt)).all()}
        logger.info("Available series", series=sorted(available))

        missing = {"VIXCLS", "BAMLH0A0HYM2", "DCOILWTICO", "CFNAI"} - available
        if missing:
            logger.error("Missing critical series -- run macro_ingestion first", missing=sorted(missing))
            sys.exit(1)

        new_missing = {"ICSA", "TOTBKCR", "PERMIT"} - available
        if new_missing:
            logger.warning(
                "New leading indicators not yet ingested -- backtest will run without them",
                missing=sorted(new_missing),
            )

        rows = await run_backtest(db)

        # Build snapshots for calibration sweep on key dates
        ukraine_snap = await _build_signals_for_date(db, date(2022, 3, 1))
        svb_snap = await _build_signals_for_date(db, date(2023, 3, 1))

    sweep_snapshots = {"ukraine": ukraine_snap, "svb": svb_snap}

    # Write outputs
    _write_csv(rows, csv_path)

    analysis = _analyze_results(rows)
    sweep = _run_calibration_sweep(sweep_snapshots)
    full_output = analysis + "\n" + sweep if sweep else analysis

    md_path.write_text(full_output, encoding="utf-8")
    logger.info("Analysis written", path=str(md_path))

    # Print summary to stdout
    print("\n" + "=" * 70)
    print(full_output)
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
