"""PR-A26.3.5 Session 1 — seed consistency test for migration 0158.

Ensures every ``strategy_label`` referenced in ``SEED_OVERRIDES`` exists
as a key in ``STRATEGY_LABEL_TO_BLOCKS``. Without this guard, a seeded
override would resolve successfully at refresh time but the construction
advisor's candidate discovery would return zero funds — silent failure.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from vertical_engines.wealth.model_portfolio.block_mapping import (
    STRATEGY_LABEL_TO_BLOCKS,
)


def _load_migration_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "core"
        / "db"
        / "migrations"
        / "versions"
        / "0158_instrument_strategy_overrides.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0158", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_seed_label_maps_to_a_block() -> None:
    mod = _load_migration_module()
    unmapped: list[tuple[str, str]] = []
    for ticker, label, _rationale in mod.SEED_OVERRIDES:
        if label not in STRATEGY_LABEL_TO_BLOCKS:
            unmapped.append((ticker, label))
    assert not unmapped, (
        f"{len(unmapped)} seed labels missing from STRATEGY_LABEL_TO_BLOCKS: "
        f"{unmapped}"
    )


def test_seed_tickers_are_unique() -> None:
    mod = _load_migration_module()
    tickers = [t for t, _, _ in mod.SEED_OVERRIDES]
    duplicates = {t for t in tickers if tickers.count(t) > 1}
    assert not duplicates, f"duplicate tickers in SEED_OVERRIDES: {duplicates}"


def test_regression_targets_are_seeded() -> None:
    """SCHD, QQQM, SCHB, VMIAX, AGG, XLF must be in seed list — the plan
    explicitly commits to flipping these back to canonical labels in the
    apply report.
    """
    mod = _load_migration_module()
    seeded = {t: label for t, label, _ in mod.SEED_OVERRIDES}
    required = {
        "SCHD": "Large Value",
        "QQQM": "Large Growth",
        "SCHB": "Large Blend",
        "VMIAX": "Sector Equity",
        "AGG": "Intermediate Core Bond",
        "XLF": "Sector Equity",
    }
    for ticker, expected_label in required.items():
        assert ticker in seeded, f"{ticker} missing from seed list"
        assert seeded[ticker] == expected_label, (
            f"{ticker} seeded as {seeded[ticker]!r}, expected {expected_label!r}"
        )
