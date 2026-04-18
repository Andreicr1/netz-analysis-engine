"""PR-A20 — canonical ingestion backfill determinism.

Migration 0147 seeds 4 canonical tickers absent from the upstream
universe_sync discovery paths; migration 0148 replays the per-org
backfill for those 4 plus VTI. This test pins:

* the seed ticker set on 0147,
* the block map on 0148,
* the attribute keys required by the ``chk_fund_attrs`` CHECK on
  ``instruments_universe`` (aum_usd, manager_name, inception_date).

Edits that drift from the spec surface in review rather than in
live smoke.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration(filename: str):
    path = (
        Path(__file__).resolve().parents[2]
        / "app" / "core" / "db" / "migrations" / "versions" / filename
    )
    spec = importlib.util.spec_from_file_location(filename.split(".")[0], path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Migration 0147 (catalog backfill) ────────────────────────────────


def test_0147_seed_targets_four_missing_tickers() -> None:
    mod = _load_migration("0147_canonical_catalog_backfill.py")
    tickers = {row["ticker"] for row in mod._CANONICAL_SEED}
    assert tickers == {"IVV", "BND", "TLT", "SHY"}


def test_0147_equity_vs_fixed_income_asset_class() -> None:
    mod = _load_migration("0147_canonical_catalog_backfill.py")
    by_ticker = {row["ticker"]: row["asset_class"] for row in mod._CANONICAL_SEED}
    assert by_ticker["IVV"] == "equity"
    assert by_ticker["BND"] == "fixed_income"
    assert by_ticker["TLT"] == "fixed_income"
    assert by_ticker["SHY"] == "fixed_income"


def test_0147_seed_rows_carry_required_attribute_fields() -> None:
    # chk_fund_attrs on instruments_universe requires aum_usd +
    # manager_name + inception_date. The migration injects these via
    # jsonb_build_object with parameter placeholders; the seed list
    # must carry manager_name and inception_date (aum_usd is hard-
    # coded in the SQL literal).
    mod = _load_migration("0147_canonical_catalog_backfill.py")
    for row in mod._CANONICAL_SEED:
        assert row["manager_name"], row
        assert row["inception_date"], row
        assert row["name"], row


# ── Migration 0148 (org backfill) ────────────────────────────────────


def test_0148_scope_covers_five_canonical_tickers() -> None:
    mod = _load_migration("0148_canonical_org_backfill.py")
    assert set(mod.CANONICAL_BLOCK_MAP) == {"VTI", "IVV", "BND", "TLT", "SHY"}


def test_0148_block_map_matches_0146() -> None:
    # Prevent drift between the A19.1 and A20 backfill paths — both must
    # assign the same ticker → block_id mapping so operators see a
    # single consistent allocation layout.
    a146 = _load_migration("0146_canonical_liquid_beta_backfill.py")
    a148 = _load_migration("0148_canonical_org_backfill.py")
    for ticker, block_id in a148.CANONICAL_BLOCK_MAP.items():
        assert a146.CANONICAL_BLOCK_MAP[ticker] == block_id, ticker
