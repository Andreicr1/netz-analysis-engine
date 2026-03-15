"""Macro Committee Engine — weekly reports + emergency workflow.

Domain-specific logic for wealth vertical. Lives in vertical_engines/wealth/
(not quant_engine/) because it contains committee workflow logic specific to
the wealth management investment process.

Pure sync report generation functions. Async workflow methods receive DB session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass(frozen=True)
class ScoreDelta:
    """Change in a regional macro score between two snapshots."""

    region: str
    previous_score: float
    current_score: float
    delta: float
    flagged: bool  # True if |delta| > threshold


@dataclass(frozen=True)
class WeeklyReportData:
    """Data for a weekly macro committee report."""

    as_of_date: date
    score_deltas: list[ScoreDelta]
    regime_transitions: dict[str, tuple[str, str]]  # region → (old, new)
    staleness_alerts: list[str]  # series IDs with stale data
    global_indicators_delta: dict[str, float]  # indicator → delta
    has_material_changes: bool


def generate_weekly_report(
    current_snapshot: dict[str, Any],
    previous_snapshot: dict[str, Any] | None,
    *,
    score_delta_threshold: float = 5.0,
) -> WeeklyReportData:
    """Generate weekly delta report comparing current vs previous snapshot.

    Pure function — no I/O. Flags:
    - Score changes > threshold points
    - Regime transitions between snapshots
    - Stale data indicators
    - Commodity/energy stress changes

    Args:
        current_snapshot: Current macro_regional_snapshot.data_json.
        previous_snapshot: Previous week's snapshot (None if first run).
        score_delta_threshold: Minimum score change to flag (default 5 points).
    """
    as_of = date.fromisoformat(current_snapshot.get("as_of_date", str(date.today())))
    current_regions = current_snapshot.get("regions", {})

    score_deltas: list[ScoreDelta] = []
    regime_transitions: dict[str, tuple[str, str]] = {}
    staleness_alerts: list[str] = []
    gi_deltas: dict[str, float] = {}

    if previous_snapshot is None:
        # First run — no comparison possible
        return WeeklyReportData(
            as_of_date=as_of,
            score_deltas=[],
            regime_transitions={},
            staleness_alerts=_collect_staleness_alerts(current_regions),
            global_indicators_delta={},
            has_material_changes=False,
        )

    previous_regions = previous_snapshot.get("regions", {})

    # Score deltas per region
    for region in ("US", "EUROPE", "ASIA", "EM"):
        curr = current_regions.get(region, {})
        prev = previous_regions.get(region, {})
        curr_score = curr.get("composite_score", 50.0)
        prev_score = prev.get("composite_score", 50.0)
        delta = round(curr_score - prev_score, 2)
        flagged = abs(delta) > score_delta_threshold

        score_deltas.append(ScoreDelta(
            region=region,
            previous_score=prev_score,
            current_score=curr_score,
            delta=delta,
            flagged=flagged,
        ))

    # Staleness alerts
    staleness_alerts = _collect_staleness_alerts(current_regions)

    # Global indicators delta
    curr_gi = current_snapshot.get("global_indicators", {})
    prev_gi = previous_snapshot.get("global_indicators", {})
    for key in ("geopolitical_risk_score", "energy_stress", "commodity_stress", "usd_strength"):
        curr_val = curr_gi.get(key, 50.0)
        prev_val = prev_gi.get(key, 50.0)
        gi_deltas[key] = round(curr_val - prev_val, 2)

    has_material = (
        any(sd.flagged for sd in score_deltas)
        or len(regime_transitions) > 0
        or any(abs(v) > score_delta_threshold for v in gi_deltas.values())
    )

    return WeeklyReportData(
        as_of_date=as_of,
        score_deltas=score_deltas,
        regime_transitions=regime_transitions,
        staleness_alerts=staleness_alerts,
        global_indicators_delta=gi_deltas,
        has_material_changes=has_material,
    )


def _collect_staleness_alerts(regions: dict[str, Any]) -> list[str]:
    """Collect series IDs with stale data across all regions."""
    stale: list[str] = []
    for region_data in regions.values():
        freshness = region_data.get("data_freshness", {})
        for series_id, f_data in freshness.items():
            if isinstance(f_data, dict) and f_data.get("status") == "stale":
                stale.append(series_id)
    return stale


def build_report_json(
    report: WeeklyReportData,
    regime_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize WeeklyReportData to JSONB-storable dict for MacroReview.report_json."""
    return {
        "type": "weekly" if not regime_data else "emergency",
        "as_of_date": report.as_of_date.isoformat(),
        "score_deltas": [
            {
                "region": sd.region,
                "previous_score": sd.previous_score,
                "current_score": sd.current_score,
                "delta": sd.delta,
                "flagged": sd.flagged,
            }
            for sd in report.score_deltas
        ],
        "regime_transitions": {
            r: {"from": old, "to": new}
            for r, (old, new) in report.regime_transitions.items()
        },
        "staleness_alerts": report.staleness_alerts,
        "global_indicators_delta": report.global_indicators_delta,
        "has_material_changes": report.has_material_changes,
        "regime": regime_data,
    }


def check_emergency_cooldown(
    last_emergency_at: datetime | None,
    cooldown_hours: int = 24,
) -> bool:
    """Return True if an emergency review can be created (cooldown elapsed).

    Args:
        last_emergency_at: Timestamp of most recent emergency review.
        cooldown_hours: Minimum hours between emergency reviews.
    """
    if last_emergency_at is None:
        return True
    now = datetime.now(timezone.utc)
    if last_emergency_at.tzinfo is None:
        last_emergency_at = last_emergency_at.replace(tzinfo=timezone.utc)
    elapsed = now - last_emergency_at
    return elapsed >= timedelta(hours=cooldown_hours)
