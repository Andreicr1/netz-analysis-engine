"""PR-A19.1 Section A — canonical block map determinism.

Migration 0146 uses a hardcoded CANONICAL_BLOCK_MAP to place liquid-beta
tickers into existing allocation_blocks. This test pins the map so
accidental edits surface in review rather than in live smoke.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "app" / "core" / "db" / "migrations" / "versions"
        / "0146_canonical_liquid_beta_backfill.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0146", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_canonical_tickers_complete() -> None:
    mod = _load_migration_module()
    assert set(mod.CANONICAL_BLOCK_MAP) == {
        "SPY", "IVV", "VTI", "AGG", "BND", "IEF", "TLT", "SHY", "GLD", "VTEB",
    }


def test_equity_tickers_map_to_na_equity_large() -> None:
    mod = _load_migration_module()
    for t in ("SPY", "IVV", "VTI"):
        assert mod.CANONICAL_BLOCK_MAP[t] == "na_equity_large"


def test_aggregate_bond_tickers_map_to_fi_aggregate() -> None:
    mod = _load_migration_module()
    for t in ("AGG", "BND"):
        assert mod.CANONICAL_BLOCK_MAP[t] == "fi_aggregate"


def test_treasury_tickers_map_to_fi_govt() -> None:
    mod = _load_migration_module()
    for t in ("IEF", "TLT"):
        assert mod.CANONICAL_BLOCK_MAP[t] == "fi_govt"


def test_shy_maps_to_fi_short_term() -> None:
    mod = _load_migration_module()
    assert mod.CANONICAL_BLOCK_MAP["SHY"] == "fi_short_term"


def test_gld_and_vteb_have_null_block() -> None:
    mod = _load_migration_module()
    # No alternatives_gold / fi_muni block in allocation_blocks; operator
    # remaps via Builder UI. Must be explicit NULL rather than a fabricated
    # block_id.
    assert mod.CANONICAL_BLOCK_MAP["GLD"] is None
    assert mod.CANONICAL_BLOCK_MAP["VTEB"] is None
