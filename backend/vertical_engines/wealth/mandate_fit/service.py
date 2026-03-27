"""Mandate Fit service — entry point for mandate fit evaluation.

Filters approved instruments by client profile constraints.
Pure logic — no DB access. Caller provides instrument data and client profile.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from vertical_engines.wealth.mandate_fit.constraint_evaluator import (
    compute_suitability_score,
    evaluate_currency,
    evaluate_domicile,
    evaluate_esg,
    evaluate_liquidity,
    evaluate_risk_bucket,
)
from vertical_engines.wealth.mandate_fit.models import (
    ClientProfile,
    ConstraintResult,
    MandateFitResult,
    MandateFitRunResult,
)

logger = structlog.get_logger(__name__)


class MandateFitService:
    """Evaluates instruments against client mandate constraints."""

    def evaluate_instrument(
        self,
        instrument_id: uuid.UUID,
        instrument_name: str,
        instrument_type: str,
        asset_class: str,
        geography: str,
        currency: str,
        attributes: dict[str, Any],
        profile: ClientProfile,
    ) -> MandateFitResult:
        """Evaluate a single instrument against client profile.

        Args:
            instrument_id: UUID of the instrument.
            instrument_name: Display name.
            instrument_type: 'fund', 'bond', or 'equity'.
            asset_class: Asset class for risk classification.
            geography: Domicile/geography of the instrument.
            currency: ISO currency code.
            attributes: JSONB attributes dict.
            profile: Client investment profile.

        Returns:
            MandateFitResult with eligibility and constraint details.

        """
        results: list[ConstraintResult] = [
            evaluate_risk_bucket(asset_class, attributes, profile),
            evaluate_esg(attributes, profile),
            evaluate_domicile(geography, profile),
            evaluate_liquidity(attributes, profile),
            evaluate_currency(currency, profile),
        ]

        disqualifying = tuple(r.reason for r in results if not r.passed)
        eligible = len(disqualifying) == 0
        score = compute_suitability_score(results)

        return MandateFitResult(
            instrument_id=instrument_id,
            instrument_name=instrument_name,
            eligible=eligible,
            suitability_score=score,
            constraint_results=tuple(results),
            disqualifying_reasons=disqualifying,
        )

    def evaluate_universe(
        self,
        instruments: list[dict[str, Any]],
        profile: ClientProfile,
    ) -> MandateFitRunResult:
        """Evaluate all instruments against client profile.

        Args:
            instruments: List of dicts with instrument_id, name, instrument_type,
                        asset_class, geography, currency, attributes.
            profile: Client investment profile.

        Returns:
            MandateFitRunResult with aggregate counts and individual results.

        """
        results: list[MandateFitResult] = []

        for inst in instruments:
            try:
                result = self.evaluate_instrument(
                    instrument_id=inst["instrument_id"],
                    instrument_name=inst.get("name", str(inst["instrument_id"])),
                    instrument_type=inst.get("instrument_type", "fund"),
                    asset_class=inst.get("asset_class", ""),
                    geography=inst.get("geography", ""),
                    currency=inst.get("currency", "USD"),
                    attributes=inst.get("attributes", {}),
                    profile=profile,
                )
                results.append(result)
            except Exception:
                logger.warning(
                    "mandate_fit_evaluation_failed",
                    instrument_id=str(inst.get("instrument_id")),
                    exc_info=True,
                )

        eligible = sum(1 for r in results if r.eligible)
        return MandateFitRunResult(
            total_evaluated=len(results),
            eligible_count=eligible,
            ineligible_count=len(results) - eligible,
            results=tuple(results),
        )
