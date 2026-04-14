"""Pure-logic tests for the apply-script CLI gates.

Full integration tests that round-trip through the stage table live in
``backend/tests/integration/test_apply_strategy_reclassification.py``
(seeded fixture with one row per severity tier). Here we focus on the
argparse / severity-resolution / gate logic which is fast and DB-free.
"""

from __future__ import annotations

import importlib
from uuid import uuid4

import pytest

apply_mod = importlib.import_module("scripts.apply_strategy_reclassification")


@pytest.fixture
def parser():
    return apply_mod._build_parser()


class TestSeverityResolution:
    def test_single_alias(self) -> None:
        assert apply_mod._resolve_severities("safe") == ["safe_auto_apply"]

    def test_comma_separated_aliases(self) -> None:
        out = apply_mod._resolve_severities("safe,style")
        assert out == ["safe_auto_apply", "style_refinement"]

    def test_all_token_expands_to_every_alias(self) -> None:
        out = apply_mod._resolve_severities("all")
        assert set(out) == {
            "safe_auto_apply",
            "style_refinement",
            "asset_class_change",
            "lost_class",
        }

    def test_unknown_alias_raises(self) -> None:
        with pytest.raises(SystemExit):
            apply_mod._resolve_severities("bogus")

    def test_empty_tokens_ignored(self) -> None:
        # Trailing commas or spaces should not crash.
        assert apply_mod._resolve_severities("safe, ") == ["safe_auto_apply"]


class TestParserGates:
    """Smoke-test that argparse accepts the documented invocations."""

    def test_dry_run_default(self, parser) -> None:
        args = parser.parse_args(
            ["--run-id", str(uuid4()), "--severity", "safe"],
        )
        assert args.confirm is False
        assert args.force is False
        assert args.justification is None

    def test_force_flag_parsed(self, parser) -> None:
        args = parser.parse_args(
            [
                "--run-id", str(uuid4()),
                "--severity", "asset_class",
                "--confirm", "--force",
            ],
        )
        assert args.force is True

    def test_yes_skips_interactive(self, parser) -> None:
        args = parser.parse_args(
            [
                "--run-id", str(uuid4()),
                "--severity", "safe",
                "--confirm", "--yes",
            ],
        )
        assert args.yes is True


class TestSeverityRequirements:
    def test_force_required_set_contains_p2_p3(self) -> None:
        assert "asset_class_change" in apply_mod.SEVERITIES_REQUIRING_FORCE
        assert "lost_class" in apply_mod.SEVERITIES_REQUIRING_FORCE

    def test_p0_p1_do_not_require_force(self) -> None:
        assert "safe_auto_apply" not in apply_mod.SEVERITIES_REQUIRING_FORCE
        assert "style_refinement" not in apply_mod.SEVERITIES_REQUIRING_FORCE

    def test_only_lost_requires_justification(self) -> None:
        assert frozenset({"lost_class"}) == apply_mod.SEVERITIES_REQUIRING_JUSTIFICATION  # noqa: SIM300


class TestLegacyToCanonical:
    """The ``--legacy-to-canonical-only`` filter must isolate vocabulary
    migrations from real cross-family changes.
    """

    def test_unknown_to_canonical_is_legacy(self) -> None:
        # "Hedge Fund" (legacy 37-cat) → "Multi-Strategy" (canonical)
        assert apply_mod._is_legacy_to_canonical(
            "Hedge Fund", "Multi-Strategy",
        ) is True

    def test_unknown_to_unknown_is_not_legacy(self) -> None:
        # Both off-taxonomy → not a legacy → canonical migration
        assert apply_mod._is_legacy_to_canonical(
            "Hedge Fund", "Some Other Legacy",
        ) is False

    def test_canonical_to_canonical_is_not_legacy(self) -> None:
        # True cross-family change — must NOT be misclassified as legacy
        assert apply_mod._is_legacy_to_canonical(
            "Large Blend", "High Yield Bond",
        ) is False

    def test_null_current_is_not_legacy(self) -> None:
        # NULL current is P0 safe_auto_apply, not a legacy migration
        assert apply_mod._is_legacy_to_canonical(
            None, "Large Blend",
        ) is False

    def test_canonical_to_null_is_not_legacy(self) -> None:
        # Canonical → NULL is P3 lost_class, not legacy
        assert apply_mod._is_legacy_to_canonical(
            "Large Blend", None,
        ) is False


class TestParserNewFlags:
    def test_legacy_only_flag(self, parser) -> None:
        args = parser.parse_args(
            [
                "--run-id", str(uuid4()),
                "--severity", "asset_class",
                "--legacy-to-canonical-only",
            ],
        )
        assert args.legacy_to_canonical_only is True

    def test_source_filter_choices_enforced(self, parser) -> None:
        # Bogus source value must fail at parse time
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "--run-id", str(uuid4()),
                    "--severity", "lost",
                    "--source-filter", "invented_source",
                ],
            )

    def test_source_filter_fallback_accepted(self, parser) -> None:
        args = parser.parse_args(
            [
                "--run-id", str(uuid4()),
                "--severity", "lost",
                "--source-filter", "fallback",
            ],
        )
        assert args.source_filter == "fallback"


class TestUpdateStmtCoverage:
    """Each source_table the worker writes must have an UPDATE statement."""

    EXPECTED_SOURCES = {
        "instruments_universe",
        "sec_manager_funds",
        "sec_registered_funds",
        "sec_etfs",
        "esma_funds",
    }

    def test_all_worker_sources_have_update_stmts(self) -> None:
        missing = self.EXPECTED_SOURCES - set(apply_mod._UPDATE_STMTS)
        assert missing == set(), (
            f"Source tables written by reclassification worker but with no "
            f"UPDATE statement in apply script: {missing}"
        )

    def test_jsonb_source_includes_ts_param(self) -> None:
        # instruments_universe lineage lives in JSONB; the SQL must bind
        # ``:ts`` so the ISO timestamp is recorded inside attributes.
        sql = apply_mod._UPDATE_STMTS["instruments_universe"]
        assert ":ts" in sql
        assert "classification_updated_at" in sql

    def test_column_sources_use_now_function(self) -> None:
        # All column-based UPDATEs should stamp NOW() server-side, not
        # bind a Python timestamp.
        for table, sql in apply_mod._UPDATE_STMTS.items():
            if table == "instruments_universe":
                continue
            assert "NOW()" in sql, f"{table} SQL missing NOW(): {sql}"
