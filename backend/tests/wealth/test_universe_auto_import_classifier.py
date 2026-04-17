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
    investment_geography: str | None = None,
    **extra_attrs: str,
) -> dict:
    attrs: dict = {k: v for k, v in {
        "strategy_label": strategy_label,
        "fund_type": fund_type,
        **extra_attrs,
    }.items() if v is not None}
    payload: dict = {
        "asset_class": asset_class,
        "instrument_type": instrument_type,
        "name": name,
        "attributes": attrs,
    }
    if investment_geography is not None:
        payload["investment_geography"] = investment_geography
    return payload


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
        # 5. FI fallback (no strategy_label, no name match)
        (
            _inst(asset_class="fixed_income"),
            "fi_us_aggregate",
            "fallback_fi_aggregate",
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


def test_valid_blocks_filters_primary_to_secondary() -> None:
    """Long/Short Equity maps to [alt_hedge_fund, na_equity_large]; when the
    primary block is not seeded in allocation_blocks, classify_block must
    fall back to the first valid secondary rather than raising.
    """
    inst = _inst(strategy_label="Long/Short Equity")
    valid = {"na_equity_large", "fi_us_aggregate", "cash"}
    block_id, reason = classify_block(inst, valid_blocks=valid)
    assert block_id == "na_equity_large"
    assert reason == "strategy_label"


@pytest.mark.parametrize(
    "geography, expected_block, reason_suffix",
    [
        ("US", "na_equity_large", "us"),
        ("North America", "na_equity_large", "north_america"),
        ("Emerging Markets", "em_equity", "emerging_markets"),
        ("Latin America", "em_equity", "latin_america"),
        ("Europe", "dm_europe_equity", "europe"),
        ("Asia Pacific", "dm_asia_equity", "asia_pacific"),
        ("Japan", "dm_asia_equity", "japan"),
        ("Global", "na_equity_large", "global"),
    ],
)
def test_equity_geography_routing(
    geography: str, expected_block: str, reason_suffix: str,
) -> None:
    inst = _inst(asset_class="equity", investment_geography=geography)
    valid = {"na_equity_large", "em_equity", "dm_europe_equity", "dm_asia_equity"}
    block_id, reason = classify_block(inst, valid_blocks=valid)
    assert block_id == expected_block
    assert reason == f"fallback_equity_{reason_suffix}"


def test_equity_unknown_geography_falls_through_to_default() -> None:
    inst = _inst(asset_class="equity", investment_geography="Antarctica")
    valid = {"na_equity_large", "em_equity", "dm_europe_equity", "dm_asia_equity"}
    block_id, reason = classify_block(inst, valid_blocks=valid)
    assert block_id == "na_equity_large"
    assert reason == "fallback_equity"


def test_equity_missing_geography_falls_through_to_default() -> None:
    """Legacy rows without investment_geography keep current PR-A6 behaviour."""
    inst = _inst(asset_class="equity")  # investment_geography omitted
    block_id, reason = classify_block(inst)
    assert block_id == "na_equity_large"
    assert reason == "fallback_equity"


def test_equity_geography_mapped_block_not_registered_falls_through() -> None:
    """When the mapped geography block is not in valid_blocks, fall
    through to the plain ``na_equity_large`` default rather than silently
    dropping the fund.
    """
    inst = _inst(asset_class="equity", investment_geography="Emerging Markets")
    valid = {"na_equity_large"}  # em_equity intentionally absent
    block_id, reason = classify_block(inst, valid_blocks=valid)
    assert block_id == "na_equity_large"
    assert reason == "fallback_equity"


def test_strategy_label_beats_geography() -> None:
    """Strategy-label cascade must run first; geography routing is
    fallback-only so funds with granular labels are not re-routed by
    their domicile region.
    """
    inst = _inst(
        asset_class="equity",
        investment_geography="Emerging Markets",
        strategy_label="Growth",
    )
    valid = {"na_equity_large", "na_equity_growth", "em_equity"}
    block_id, reason = classify_block(inst, valid_blocks=valid)
    assert block_id == "na_equity_growth"
    assert reason == "strategy_label"


@pytest.mark.parametrize(
    "name, expected_block, expected_reason",
    [
        ("iShares 7-10 Year Treasury ETF", "fi_us_treasury", "fallback_fi_name_fi_us_treasury"),
        ("Vanguard Short-Term Treasury Index", "fi_us_treasury", "fallback_fi_name_fi_us_treasury"),
        ("SPDR Bloomberg 1-3 Month T-Bill ETF", "fi_us_treasury", "fallback_fi_name_fi_us_treasury"),
        ("iShares Core U.S. GOVT Bond ETF", "fi_us_treasury", "fallback_fi_name_fi_us_treasury"),
        ("SPDR Bloomberg TIPS ETF", "fi_us_tips", "fallback_fi_name_fi_us_tips"),
        ("iShares Inflation-Protected Bond ETF", "fi_us_tips", "fallback_fi_name_fi_us_tips"),
        ("PIMCO Inflation Protected Securities", "fi_us_tips", "fallback_fi_name_fi_us_tips"),
        ("iShares iBoxx $ High Yield Corporate Bond ETF", "fi_us_high_yield", "fallback_fi_name_fi_us_high_yield"),
        ("SPDR High-Yield Corporate", "fi_us_high_yield", "fallback_fi_name_fi_us_high_yield"),
        ("AllianceBernstein Junk Bond Fund", "fi_us_high_yield", "fallback_fi_name_fi_us_high_yield"),
        ("Vanguard Total Bond Market Index", "fi_us_aggregate", "fallback_fi_aggregate"),
        ("PIMCO Total Return Fund", "fi_us_aggregate", "fallback_fi_aggregate"),
    ],
)
def test_fi_name_heuristic(
    name: str, expected_block: str, expected_reason: str,
) -> None:
    inst = _inst(
        asset_class="fixed_income", investment_geography="US", name=name,
    )
    valid = {
        "fi_us_aggregate", "fi_us_treasury", "fi_us_tips",
        "fi_us_high_yield", "fi_em_debt",
    }
    block_id, reason = classify_block(inst, valid_blocks=valid)
    assert block_id == expected_block
    assert reason == expected_reason


def test_fi_tips_beats_treasury_specificity() -> None:
    """A fund titled 'Treasury Inflation-Protected' must route to
    fi_us_tips, not fi_us_treasury — TIPS heuristic is checked first
    because it's more specific.
    """
    inst = _inst(
        asset_class="fixed_income", investment_geography="US",
        name="iShares Treasury Inflation-Protected Securities ETF",
    )
    valid = {"fi_us_aggregate", "fi_us_treasury", "fi_us_tips", "fi_us_high_yield"}
    block_id, reason = classify_block(inst, valid_blocks=valid)
    assert block_id == "fi_us_tips"
    assert reason == "fallback_fi_name_fi_us_tips"


def test_fi_geography_em_routes_to_em_debt() -> None:
    inst = _inst(
        asset_class="fixed_income", investment_geography="Emerging Markets",
        name="iShares JP Morgan EM Debt ETF",
    )
    valid = {"fi_us_aggregate", "fi_em_debt"}
    block_id, reason = classify_block(inst, valid_blocks=valid)
    assert block_id == "fi_em_debt"
    assert reason == "fallback_fi_em"


def test_fi_geography_em_falls_through_if_block_missing() -> None:
    """If fi_em_debt is not registered, EM FI degrades gracefully to
    name-heuristic / aggregate rather than silently dropping the fund.
    """
    inst = _inst(
        asset_class="fixed_income", investment_geography="Emerging Markets",
        name="Generic EM Bond Fund",
    )
    valid = {"fi_us_aggregate"}  # fi_em_debt intentionally absent
    block_id, reason = classify_block(inst, valid_blocks=valid)
    assert block_id == "fi_us_aggregate"
    assert reason == "fallback_fi_aggregate"


def test_fi_geography_europe_falls_through_if_block_missing() -> None:
    """fi_europe_aggregate is NOT in the default seed; the classifier
    must gracefully fall through to US name heuristics / aggregate.
    """
    inst = _inst(
        asset_class="fixed_income", investment_geography="Europe",
        name="iShares Euro Aggregate Bond ETF",
    )
    valid = {"fi_us_aggregate", "fi_us_treasury"}
    block_id, reason = classify_block(inst, valid_blocks=valid)
    assert block_id == "fi_us_aggregate"
    assert reason == "fallback_fi_aggregate"


def test_fi_strategy_label_beats_name_heuristic() -> None:
    """Strategy-label cascade must still run first. A fund whose name
    mentions 'Treasury' but has strategy_label='High Yield Bond' should
    hit fi_us_high_yield via the label, not fi_us_treasury via the name.
    """
    inst = _inst(
        asset_class="fixed_income", investment_geography="US",
        name="Fictional Treasury High Yield Cross Fund",
        strategy_label="High Yield Bond",
    )
    valid = {"fi_us_aggregate", "fi_us_treasury", "fi_us_high_yield"}
    block_id, reason = classify_block(inst, valid_blocks=valid)
    assert block_id == "fi_us_high_yield"
    assert reason == "strategy_label"


def test_valid_blocks_no_valid_candidate_surfaces_block_not_registered() -> None:
    """Multi-Strategy only maps to [alt_hedge_fund]; when none of the
    candidate blocks are seeded the classifier must skip the row with a
    distinct reason so the admin dashboard can surface the drift.
    """
    inst = _inst(strategy_label="Multi-Strategy", asset_class="alternatives")
    valid = {"na_equity_large", "fi_us_aggregate", "cash"}
    block_id, reason = classify_block(inst, valid_blocks=valid)
    assert block_id is None
    assert reason == "block_not_registered"
