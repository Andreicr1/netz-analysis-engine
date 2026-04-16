"""Tests for universe auto-import block classifier."""

import pytest

from app.domains.wealth.services.universe_auto_import_classifier import classify_block


def _inst(
    *,
    asset_class: str = "equity",
    instrument_type: str = "fund",
    name: str = "Test Fund",
    strategy_label: str | None = None,
    fund_type: str | None = None,
    **extra_attrs: str,
) -> dict:
    attrs: dict = {k: v for k, v in {
        "strategy_label": strategy_label,
        "fund_type": fund_type,
        **extra_attrs,
    }.items() if v is not None}
    return {
        "asset_class": asset_class,
        "instrument_type": instrument_type,
        "name": name,
        "attributes": attrs,
    }


@pytest.mark.parametrize(
    "instrument, expected_block, expected_reason",
    [
        # 1. Strategy label -> direct mapping
        (
            _inst(strategy_label="Large Blend"),
            "na_equity_large",
            "strategy_label",
        ),
        # 2. Strategy label -> FI mapping
        (
            _inst(asset_class="fixed_income", strategy_label="High Yield Bond"),
            "fi_us_high_yield",
            "strategy_label",
        ),
        # 3. Cash via asset_class
        (
            _inst(asset_class="cash"),
            "cash",
            "asset_class_cash",
        ),
        # 4. Money market via instrument_type
        (
            _inst(asset_class="cash", instrument_type="money_market"),
            "cash",
            "asset_class_cash",
        ),
        # 5. FI fallback (no strategy_label)
        (
            _inst(asset_class="fixed_income"),
            "fi_us_aggregate",
            "fallback_fi",
        ),
        # 6. Equity fallback (no strategy_label)
        (
            _inst(asset_class="equity"),
            "na_equity_large",
            "fallback_equity",
        ),
        # 7. Real estate fund type
        (
            _inst(asset_class="alternatives", fund_type="Real Estate Fund"),
            "alt_real_estate",
            "fund_type_real_estate",
        ),
        # 8. Private fund type -> skip (alternatives asset_class, no strategy_label)
        (
            _inst(asset_class="alternatives", fund_type="Hedge Fund"),
            None,
            "private_fund_type",
        ),
        # 9. BDC -> skip
        (
            _inst(instrument_type="bdc", asset_class="alternatives"),
            None,
            "bdc_manual_only",
        ),
        # 10. Hybrid / multi-asset -> skip
        (
            _inst(strategy_label="Allocation--50% to 70% Equity"),
            None,
            "hybrid_unsupported",
        ),
        # 11. Unclassified (unknown asset_class, no signals)
        (
            _inst(asset_class="other", instrument_type="unknown"),
            None,
            "unclassified",
        ),
        # 12. Regression: Private Credit maps to fi_us_high_yield via strategy_label
        # (auto-import worker skips privates separately; classifier returns the mapping)
        (
            _inst(
                asset_class="fixed_income",
                strategy_label="Private Credit",
                fund_type="Private Equity Fund",
            ),
            "fi_us_high_yield",
            "strategy_label",
        ),
        # 13. ETF commodity: Precious Metals -> alt_gold
        (
            _inst(
                instrument_type="etf",
                asset_class="alternatives",
                strategy_label="Precious Metals",
            ),
            "alt_gold",
            "strategy_label",
        ),
        # 14. EM equity
        (
            _inst(strategy_label="Diversified Emerging Mkts"),
            "em_equity",
            "strategy_label",
        ),
    ],
    ids=[
        "strategy_label_equity",
        "strategy_label_fi",
        "cash_asset_class",
        "money_market_type",
        "fi_fallback",
        "equity_fallback",
        "real_estate_fund_type",
        "private_skip",
        "bdc_skip",
        "hybrid_skip",
        "unclassified",
        "private_credit_regression",
        "precious_metals_etf",
        "em_equity",
    ],
)
def test_classify_block(
    instrument: dict,
    expected_block: str | None,
    expected_reason: str,
) -> None:
    block_id, reason = classify_block(instrument)
    assert block_id == expected_block
    assert reason == expected_reason


def test_classify_block_empty_attributes() -> None:
    inst = {"asset_class": "equity", "instrument_type": "fund", "attributes": None, "name": "X"}
    block_id, reason = classify_block(inst)
    assert block_id == "na_equity_large"
    assert reason == "fallback_equity"
