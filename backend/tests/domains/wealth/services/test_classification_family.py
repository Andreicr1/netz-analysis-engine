"""Unit tests for the strategy-label family map and severity classifier."""

from __future__ import annotations

import pytest

from app.domains.wealth.services.classification_family import (
    STRATEGY_FAMILY,
    classify_severity,
    family_of,
    is_same_family,
)
from app.domains.wealth.services.strategy_classifier import STRATEGY_LABELS


class TestFamilyMap:
    """The family map MUST be in lockstep with the canonical taxonomy."""

    def test_every_label_has_family(self) -> None:
        missing = sorted(STRATEGY_LABELS - set(STRATEGY_FAMILY))
        assert missing == [], (
            f"strategy_classifier.STRATEGY_LABELS contains labels with no "
            f"family entry: {missing}"
        )

    def test_no_stale_family_entries(self) -> None:
        stale = sorted(set(STRATEGY_FAMILY) - STRATEGY_LABELS)
        assert stale == [], (
            f"classification_family.STRATEGY_FAMILY contains labels not in "
            f"STRATEGY_LABELS: {stale}"
        )

    def test_no_label_maps_to_unknown_family(self) -> None:
        # All values in STRATEGY_FAMILY should be one of the Family literals.
        valid = {
            "equity", "fixed_income", "alts", "private",
            "hedge", "multi_asset", "convertible", "cash", "other",
        }
        bad = {label: fam for label, fam in STRATEGY_FAMILY.items() if fam not in valid}
        assert bad == {}, f"Bad family value: {bad}"


class TestFamilyOf:
    def test_known_label(self) -> None:
        assert family_of("Large Blend") == "equity"
        assert family_of("High Yield Bond") == "fixed_income"
        assert family_of("Private Credit") == "private"

    def test_none_input(self) -> None:
        assert family_of(None) is None

    def test_unknown_label(self) -> None:
        assert family_of("Made Up Strategy") is None


class TestIsSameFamily:
    def test_same_family_true(self) -> None:
        assert is_same_family("Large Blend", "Small Value") is True
        assert is_same_family("Real Estate", "Infrastructure") is True

    def test_cross_family_false(self) -> None:
        assert is_same_family("Large Blend", "High Yield Bond") is False
        assert is_same_family("Private Credit", "Real Estate") is False

    def test_none_either_side_false(self) -> None:
        assert is_same_family(None, "Large Blend") is False
        assert is_same_family("Large Blend", None) is False
        assert is_same_family(None, None) is False

    def test_unknown_label_not_same_family(self) -> None:
        # Unknown label cannot establish family equivalence — defensively
        # treated as "not the same" so we never silently downgrade
        # severity below asset_class_change.
        assert is_same_family("Unknown", "Large Blend") is False
        assert is_same_family("Large Blend", "Unknown") is False


class TestClassifySeverity:
    @pytest.mark.parametrize(
        ("current", "proposed", "expected"),
        [
            # ── unchanged ─────────────────────────────────────────────
            ("Large Blend", "Large Blend", "unchanged"),
            (None, None, "unchanged"),
            # ── safe_auto_apply: NULL → label ─────────────────────────
            (None, "Large Blend", "safe_auto_apply"),
            (None, "Private Credit", "safe_auto_apply"),
            # ── lost_class: label → NULL ──────────────────────────────
            ("Large Blend", None, "lost_class"),
            ("Private Credit", None, "lost_class"),
            # ── style_refinement: same family ─────────────────────────
            ("Large Blend", "Large Growth", "style_refinement"),
            ("Real Estate", "Infrastructure", "style_refinement"),
            ("Short-Term Bond", "High Yield Bond", "style_refinement"),
            # ── asset_class_change: cross family ──────────────────────
            ("Large Blend", "High Yield Bond", "asset_class_change"),
            ("Private Equity", "Real Estate", "asset_class_change"),
            ("Large Blend", "Private Credit", "asset_class_change"),
            # ── unknown labels treated as cross-family ────────────────
            ("Large Blend", "Unknown Label", "asset_class_change"),
        ],
    )
    def test_severity_table(
        self, current: str | None, proposed: str | None, expected: str,
    ) -> None:
        assert classify_severity(current, proposed) == expected

    def test_convertible_securities_is_own_family(self) -> None:
        # Convertible Securities is intentionally distinct from
        # Convertible Arbitrage — moving between them is an asset class
        # change (mutual fund <-> hedge), NOT a style refinement.
        assert classify_severity(
            "Convertible Securities", "Convertible Arbitrage",
        ) == "asset_class_change"
