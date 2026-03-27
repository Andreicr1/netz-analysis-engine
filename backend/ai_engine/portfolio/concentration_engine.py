"""Concentration Engine — deterministic portfolio-level concentration analysis.

Thresholds are loaded dynamically from fund policy documents via policy_loader.py:
  - fund-constitution-index (IMA, M&A — legally binding)
  - risk-policy-index       (Credit Policy, Investment Policy)
  - Auditable defaults      (only if documents don't specify limits)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_engine.governance.policy_loader import PolicyThresholds, load_policy_thresholds
from app.domains.credit.modules.ai.models import ActiveInvestment

logger = logging.getLogger(__name__)


@dataclass
class ConcentrationBucket:
    name: str
    exposure_usd: float
    weight_pct: float
    breaches_limit: bool = False
    limit_pct: float = 0.0
    limit_source: str = "DEFAULT"


@dataclass
class ConcentrationProfile:
    total_exposure_usd: float = 0.0
    investment_count: int = 0
    excluded_count: int = 0
    metrics_status: str = "COMPLETE"

    manager_buckets: list[ConcentrationBucket] = field(default_factory=list)
    manager_hhi: float = 0.0
    manager_limit_breached: bool = False

    sector_buckets: list[ConcentrationBucket] = field(default_factory=list)
    sector_hhi: float = 0.0
    sector_limit_breached: bool = False

    geography_buckets: list[ConcentrationBucket] = field(default_factory=list)
    geography_hhi: float = 0.0
    geography_limit_breached: bool = False

    top3_weight_pct: float = 0.0
    top3_limit_breached: bool = False

    non_usd_unhedged_pct: float | None = None
    non_usd_unhedged_breached: bool = False
    hard_lockup_pct: float | None = None
    hard_lockup_breached: bool = False

    any_limit_breached: bool = False
    requires_board_override: bool = False
    board_override_reasons: list[str] = field(default_factory=list)

    policy_summary: dict = field(default_factory=dict)

    @property
    def total_nav_usd(self) -> float:
        return self.total_exposure_usd

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_exposure_usd": self.total_exposure_usd,
            "total_nav_usd": self.total_exposure_usd,
            "investment_count": self.investment_count,
            "excluded_count": self.excluded_count,
            "metrics_status": self.metrics_status,
            "manager_buckets": [
                {"name": b.name, "exposure_usd": b.exposure_usd, "weight_pct": b.weight_pct,
                 "breaches_limit": b.breaches_limit, "limit_pct": b.limit_pct, "limit_source": b.limit_source}
                for b in self.manager_buckets
            ],
            "manager_hhi": self.manager_hhi,
            "manager_limit_breached": self.manager_limit_breached,
            "sector_buckets": [
                {"name": b.name, "exposure_usd": b.exposure_usd, "weight_pct": b.weight_pct,
                 "breaches_limit": b.breaches_limit, "limit_pct": b.limit_pct, "limit_source": b.limit_source}
                for b in self.sector_buckets
            ],
            "sector_hhi": self.sector_hhi,
            "sector_limit_breached": self.sector_limit_breached,
            "geography_buckets": [
                {"name": b.name, "exposure_usd": b.exposure_usd, "weight_pct": b.weight_pct,
                 "breaches_limit": b.breaches_limit, "limit_pct": b.limit_pct, "limit_source": b.limit_source}
                for b in self.geography_buckets
            ],
            "geography_hhi": self.geography_hhi,
            "geography_limit_breached": self.geography_limit_breached,
            "top3_weight_pct": self.top3_weight_pct,
            "top3_limit_breached": self.top3_limit_breached,
            "non_usd_unhedged_pct": self.non_usd_unhedged_pct,
            "non_usd_unhedged_breached": self.non_usd_unhedged_breached,
            "hard_lockup_pct": self.hard_lockup_pct,
            "hard_lockup_breached": self.hard_lockup_breached,
            "any_limit_breached": self.any_limit_breached,
            "requires_board_override": self.requires_board_override,
            "board_override_reasons": self.board_override_reasons,
            "policy_summary": self.policy_summary,
        }


def _compute_hhi(weights_pct: list[float]) -> float:
    return round(sum(w * w for w in weights_pct), 2)


def _normalize_name(name: str) -> str:
    return name.strip().lower() if name else "unknown"


def _build_buckets(
    exposures: dict[str, float],
    total: float,
    limit_pct: float,
    limit_source: str,
) -> tuple[list[ConcentrationBucket], bool]:
    buckets: list[ConcentrationBucket] = []
    any_breach = False
    for name, exposure in sorted(exposures.items(), key=lambda x: -x[1]):
        weight = round((exposure / total) * 100.0, 2) if total > 0 else 0.0
        breach = weight > limit_pct
        if breach:
            any_breach = True
        buckets.append(ConcentrationBucket(
            name=name, exposure_usd=round(exposure, 2),
            weight_pct=weight, breaches_limit=breach,
            limit_pct=limit_pct, limit_source=limit_source,
        ))
    return buckets, any_breach


def _check_board_override(profile: ConcentrationProfile, policy: PolicyThresholds) -> None:
    triggers: list[str] = policy.board_override_triggers.value or []
    reasons: list[str] = []

    trigger_map = {
        "single_manager":   profile.manager_limit_breached,
        "single_investment": profile.manager_limit_breached,  # proxy via manager
        "single_sector":    profile.sector_limit_breached,
        "single_geography": profile.geography_limit_breached,
        "top3_names":       profile.top3_limit_breached,
        "non_usd_unhedged": profile.non_usd_unhedged_breached,
        "hard_lockup":      profile.hard_lockup_breached,
    }

    for trigger in triggers:
        if trigger_map.get(trigger, False):
            reasons.append(
                f"{trigger} breach — policy source: {policy.board_override_triggers.source}",
            )

    # Safety net: manager breach always requires board override
    if profile.manager_limit_breached and not any("single_manager" in r for r in reasons):
        reasons.append(
            f"single_manager breach (limit: {policy.single_manager_pct.value}% "
            f"from {policy.single_manager_pct.source})",
        )

    profile.requires_board_override = len(reasons) > 0
    profile.board_override_reasons = reasons


def compute_concentration(
    db: Session,
    *,
    fund_id: Any,
    include_pending_deal: dict[str, Any] | None = None,
    policy: PolicyThresholds | None = None,
) -> ConcentrationProfile:
    """Compute portfolio concentration profile for a fund.

    Args:
        db: Active SQLAlchemy session.
        fund_id: Fund UUID.
        include_pending_deal: Optional dict:
            {deal_name, manager_name, strategy_type, geography,
             committed_capital_usd, is_non_usd_unhedged, has_hard_lockup}
        policy: Pre-loaded PolicyThresholds. If None, loaded from cache/indices.

    """
    if policy is None:
        # TODO(Sprint 3): wire ConfigService when async session migration lands
        policy = load_policy_thresholds()

    investments = list(
        db.execute(
            select(ActiveInvestment).where(
                ActiveInvestment.fund_id == fund_id,
                ActiveInvestment.lifecycle_status.in_(["ACTIVE", "MONITORING"]),
            ),
        ).scalars().all(),
    )

    profile = ConcentrationProfile()
    profile.investment_count = len(investments)
    profile.policy_summary = policy.summary()

    manager_exp: dict[str, float] = {}
    sector_exp:  dict[str, float] = {}
    geo_exp:     dict[str, float] = {}
    name_exp:    dict[str, float] = {}
    total_exposure = 0.0
    excluded_count = 0

    for inv in investments:
        exposure = inv.deployed_capital_usd or inv.committed_capital_usd
        if not exposure or exposure <= 0:
            excluded_count += 1
            logger.warning("CONCENTRATION_MISSING_EXPOSURE", extra={
                "investment_id": str(inv.id), "investment_name": inv.investment_name,
                "deployed": inv.deployed_capital_usd, "committed": inv.committed_capital_usd,
            })
            continue

        total_exposure += exposure

        mgr = _normalize_name(inv.manager_name or "Unknown")
        manager_exp[mgr] = manager_exp.get(mgr, 0.0) + exposure

        sector = _normalize_name(inv.strategy_type or "Unclassified")
        sector_exp[sector] = sector_exp.get(sector, 0.0) + exposure

        geo = _normalize_name(
            getattr(inv, "geography", None)
            or getattr(inv, "domicile", None)
            or getattr(inv, "country", None)
            or "global",
        )
        geo_exp[geo] = geo_exp.get(geo, 0.0) + exposure
        name_exp[inv.investment_name] = name_exp.get(inv.investment_name, 0.0) + exposure

    profile.excluded_count = excluded_count

    if include_pending_deal:
        pending_exposure = include_pending_deal.get("committed_capital_usd", 0.0) or 0.0
        if pending_exposure > 0:
            total_exposure += pending_exposure
            profile.investment_count += 1
            mgr = _normalize_name(include_pending_deal.get("manager_name", "Unknown"))
            manager_exp[mgr] = manager_exp.get(mgr, 0.0) + pending_exposure
            sector = _normalize_name(include_pending_deal.get("strategy_type", "Unclassified"))
            sector_exp[sector] = sector_exp.get(sector, 0.0) + pending_exposure
            geo = _normalize_name(include_pending_deal.get("geography", "global"))
            geo_exp[geo] = geo_exp.get(geo, 0.0) + pending_exposure
            deal_name = include_pending_deal.get("deal_name", "Pending Deal")
            name_exp[deal_name] = name_exp.get(deal_name, 0.0) + pending_exposure
        else:
            excluded_count += 1
            logger.warning("CONCENTRATION_PENDING_DEAL_NO_EXPOSURE",
                           extra={"deal": include_pending_deal.get("deal_name", "?")})

    profile.total_exposure_usd = round(total_exposure, 2)

    if profile.investment_count == 0 or total_exposure <= 0:
        profile.metrics_status = "INSUFFICIENT_DATA"
        return profile
    if excluded_count > 0:
        profile.metrics_status = "PARTIAL"
    else:
        profile.metrics_status = "COMPLETE"

    mgr_limit = policy.single_manager_pct
    profile.manager_buckets, profile.manager_limit_breached = _build_buckets(
        manager_exp, total_exposure, mgr_limit.value, mgr_limit.source)
    profile.manager_hhi = _compute_hhi([b.weight_pct for b in profile.manager_buckets])

    sec_limit = policy.single_sector_pct
    profile.sector_buckets, profile.sector_limit_breached = _build_buckets(
        sector_exp, total_exposure, sec_limit.value, sec_limit.source)
    profile.sector_hhi = _compute_hhi([b.weight_pct for b in profile.sector_buckets])

    geo_limit = policy.single_geography_pct
    profile.geography_buckets, profile.geography_limit_breached = _build_buckets(
        geo_exp, total_exposure, geo_limit.value, geo_limit.source)
    profile.geography_hhi = _compute_hhi([b.weight_pct for b in profile.geography_buckets])

    top3_limit = policy.top3_names_pct
    sorted_names = sorted(name_exp.values(), reverse=True)
    top3_exposure = sum(sorted_names[:3])
    profile.top3_weight_pct = round((top3_exposure / total_exposure) * 100.0, 2)
    profile.top3_limit_breached = profile.top3_weight_pct > top3_limit.value

    # Allocation constraint checks (Investment Policy s.4)
    if include_pending_deal and total_exposure > 0:
        pending_exposure = include_pending_deal.get("committed_capital_usd", 0.0) or 0.0

        if include_pending_deal.get("is_non_usd_unhedged"):
            non_usd_exp = sum(
                (inv.deployed_capital_usd or inv.committed_capital_usd or 0)
                for inv in investments
                if getattr(inv, "is_non_usd_unhedged", False)
            ) + pending_exposure
            profile.non_usd_unhedged_pct = round((non_usd_exp / total_exposure) * 100.0, 2)
            profile.non_usd_unhedged_breached = (
                profile.non_usd_unhedged_pct > policy.non_usd_unhedged_pct.value
            )

        if include_pending_deal.get("has_hard_lockup"):
            lockup_exp = sum(
                (inv.deployed_capital_usd or inv.committed_capital_usd or 0)
                for inv in investments
                if getattr(inv, "has_hard_lockup", False)
            ) + pending_exposure
            profile.hard_lockup_pct = round((lockup_exp / total_exposure) * 100.0, 2)
            profile.hard_lockup_breached = (
                profile.hard_lockup_pct > policy.max_hard_lockup_pct.value
            )

    profile.any_limit_breached = (
        profile.manager_limit_breached
        or profile.sector_limit_breached
        or profile.geography_limit_breached
        or profile.top3_limit_breached
        or profile.non_usd_unhedged_breached
        or profile.hard_lockup_breached
    )

    _check_board_override(profile, policy)

    logger.info("CONCENTRATION_COMPUTED", extra={
        "fund_id": str(fund_id),
        "investment_count": profile.investment_count,
        "excluded_count": profile.excluded_count,
        "metrics_status": profile.metrics_status,
        "total_exposure_usd": profile.total_exposure_usd,
        "manager_breached": profile.manager_limit_breached,
        "sector_breached": profile.sector_limit_breached,
        "geography_breached": profile.geography_limit_breached,
        "top3_pct": profile.top3_weight_pct,
        "requires_board_override": profile.requires_board_override,
        "policy_sources": {k: v["source"] for k, v in profile.policy_summary.items()},
    })

    return profile
