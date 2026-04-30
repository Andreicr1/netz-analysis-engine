"""Tests for PR-Q159 — QuantAnalyzer as_of deprecation + matview CIK rebuild."""
from __future__ import annotations

import warnings


class TestQuantAnalyzerAsOfDeprecation:
    """WMJ-004: as_of parameter should warn when non-None."""

    def test_as_of_none_no_warning(self):
        """Passing as_of=None should not emit a deprecation warning."""
        from unittest.mock import MagicMock

        from vertical_engines.wealth.quant_analyzer import QuantAnalyzer

        qa = QuantAnalyzer()
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []
        db.execute.return_value.scalar_one_or_none.return_value = None

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                qa.analyze_portfolio(
                    db,
                    instrument_id="00000000-0000-0000-0000-000000000001",
                    actor_id="test",
                    as_of=None,
                )
            except Exception:
                pass  # We expect DB errors since it's mocked
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 0

    def test_as_of_non_none_emits_deprecation(self):
        """Passing as_of='2025-12-31' should emit a DeprecationWarning."""
        from unittest.mock import MagicMock

        from vertical_engines.wealth.quant_analyzer import QuantAnalyzer

        qa = QuantAnalyzer()
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []
        db.execute.return_value.scalar_one_or_none.return_value = None

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                qa.analyze_portfolio(
                    db,
                    instrument_id="00000000-0000-0000-0000-000000000001",
                    actor_id="test",
                    as_of="2025-12-31",
                )
            except Exception:
                pass
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 1
            assert "not implemented" in str(deprecation_warnings[0].message).lower()


class TestMatviewCikPadded:
    """WMJ-006: matview rebuild + holdings rail simplification."""

    def test_migration_uses_cik_padded(self):
        """Migration DDL should reference cik_padded, not bare cik."""
        import importlib

        mod = importlib.import_module(
            "app.core.db.migrations.versions.0198_q159_rebuild_mv_nport_sector_attribution"
        )
        assert "cik_padded" in mod._MV_DDL
        # no bare h.cik (note trailing space to avoid matching cik_padded)
        assert "h.cik " not in mod._MV_DDL

    def test_holdings_rail_uses_padded_cik_directly(self):
        """holdings_based.latest_period_for_cik should use padded CIK directly."""
        import inspect

        from vertical_engines.wealth.attribution.holdings_based import (
            latest_period_for_cik,
        )

        src = inspect.getsource(latest_period_for_cik)
        # Should NOT use cik_variants anymore for matview queries
        assert "cik_variants" not in src

    def test_normalize_cik_pads_to_10(self):
        """_normalize_cik should zero-pad to 10 digits."""
        from vertical_engines.wealth.attribution.holdings_based import _normalize_cik

        assert _normalize_cik("12345") == "0000012345"
        assert _normalize_cik("1234567890") == "1234567890"
        assert _normalize_cik("") is None
        assert _normalize_cik(None) is None
        assert _normalize_cik("abc") is None

    def test_normalize_cik_strips_leading_zeros(self):
        """_normalize_cik should handle CIKs with leading zeros."""
        from vertical_engines.wealth.attribution.holdings_based import _normalize_cik

        assert _normalize_cik("0000012345") == "0000012345"
        assert _normalize_cik("00123") == "0000000123"

    def test_downgrade_ddl_uses_bare_cik(self):
        """Downgrade DDL should revert to bare h.cik."""
        import importlib

        mod = importlib.import_module(
            "app.core.db.migrations.versions.0198_q159_rebuild_mv_nport_sector_attribution"
        )
        assert "h.cik " in mod._MV_DDL_OLD
        assert "cik_padded" not in mod._MV_DDL_OLD
