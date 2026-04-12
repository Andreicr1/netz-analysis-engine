"""Tests for the ELITE ranking allocation source accessor.

These tests hit the live local-dev database because the ELITE
allocation source is a Form A accessor — it reads real rows that
the application seeds into ``vertical_config_defaults`` and
``allocation_blocks``. Mocking them would test nothing meaningful.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.db.engine import async_session_factory
from vertical_engines.wealth.elite_ranking.allocation_source import (
    CANONICAL_PROFILE,
    CANONICAL_VERTICAL,
    EliteAllocationSourceError,
    compute_target_counts,
    get_global_default_strategy_weights,
)


@pytest.mark.asyncio
async def test_get_global_default_strategy_weights_sums_to_one() -> None:
    """The aggregated per-asset_class weights must sum to 1.0 ± 1e-3."""
    async with async_session_factory() as db:
        weights = await get_global_default_strategy_weights(db)

    assert weights, "Expected non-empty weights map"
    assert abs(sum(weights.values()) - 1.0) < 1e-3, (
        f"Weights sum to {sum(weights.values()):.6f}, expected ~1.0. "
        f"Breakdown: {weights}"
    )


@pytest.mark.asyncio
async def test_get_global_default_strategy_weights_all_classes_in_catalog() -> None:
    """Every returned asset_class must exist in instruments_universe.

    ELITE ranking matches funds to strategy buckets via
    ``instruments_universe.asset_class``. A weight for an asset_class
    with zero funds in the catalog would waste target slots.
    """
    async with async_session_factory() as db:
        weights = await get_global_default_strategy_weights(db)

        catalog_rows = await db.execute(
            text(
                """
                SELECT DISTINCT asset_class
                FROM instruments_universe
                WHERE is_active = true
                """,
            ),
        )
        catalog_classes = {row[0] for row in catalog_rows.all()}

    unknown = set(weights.keys()) - catalog_classes
    assert not unknown, (
        f"ELITE weights reference asset_classes {unknown!r} that do "
        f"not appear in instruments_universe. Catalog classes: "
        f"{sorted(catalog_classes)}"
    )


@pytest.mark.asyncio
async def test_get_global_default_strategy_weights_has_canonical_classes() -> None:
    """The moderate profile must cover the four institutional buckets.

    Guards against accidental deletion of an asset class from the
    seeded ``portfolio_profiles`` config — if one of these four
    disappears, ELITE ranking silently loses ~10–50% of its target
    count, which would be a production-grade correctness regression.
    """
    expected = {"equity", "fixed_income", "alternatives", "cash"}
    async with async_session_factory() as db:
        weights = await get_global_default_strategy_weights(db)

    missing = expected - set(weights.keys())
    assert not missing, (
        f"Canonical asset classes {missing!r} missing from the "
        f"moderate profile. Got: {sorted(weights.keys())}"
    )


@pytest.mark.asyncio
async def test_raises_when_config_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if the config row is absent."""
    async with async_session_factory() as db:
        # Isolate the delete in a SAVEPOINT so the test cannot
        # corrupt the shared dev DB if an assertion fails early.
        async with db.begin():
            await db.execute(
                text(
                    """
                    DELETE FROM vertical_config_defaults
                    WHERE vertical = :vertical
                      AND config_type = 'portfolio_profiles'
                    """,
                ),
                {"vertical": CANONICAL_VERTICAL},
            )

            try:
                with pytest.raises(EliteAllocationSourceError):
                    await get_global_default_strategy_weights(db)
            finally:
                # Force rollback regardless of assertion outcome.
                await db.rollback()


def test_compute_target_counts_rounds_to_300() -> None:
    """round(300 * w) over the canonical distribution stays within 1."""
    canonical = {
        "equity": 0.50,
        "fixed_income": 0.33,
        "alternatives": 0.12,
        "cash": 0.05,
    }
    counts = compute_target_counts(canonical, total_elite=300)

    assert counts == {
        "equity": 150,
        "fixed_income": 99,
        "alternatives": 36,
        "cash": 15,
    }
    assert abs(sum(counts.values()) - 300) <= 3


def test_compute_target_counts_handles_arbitrary_bucket_count() -> None:
    """The helper is not hard-coded to 4 buckets."""
    counts = compute_target_counts({"a": 0.2, "b": 0.3, "c": 0.5}, total_elite=100)
    assert sum(counts.values()) == 100


def test_canonical_profile_is_moderate() -> None:
    """Freeze the canonical profile choice — any drift here is a
    product decision that must be audited, not a silent typo."""
    assert CANONICAL_PROFILE == "moderate"
    assert CANONICAL_VERTICAL == "liquid_funds"
    _ = Decimal  # keep import utilised for future numeric assertions
