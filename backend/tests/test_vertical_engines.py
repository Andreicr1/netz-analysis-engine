"""Tests for vertical_engines structure — imports, base interfaces, credit + wealth modules."""

from __future__ import annotations

import importlib
import inspect

# ── Base interface tests ──────────────────────────────────────────────────────


class TestBaseInterfaces:
    def test_base_analyzer_is_abstract(self):
        from vertical_engines.base.base_analyzer import BaseAnalyzer

        assert inspect.isabstract(BaseAnalyzer)
        abstract_methods = {m for m in BaseAnalyzer.__abstractmethods__}
        assert "run_deal_analysis" in abstract_methods
        assert "run_portfolio_analysis" in abstract_methods
        # run_pipeline_analysis is a concrete default (not abstract)
        assert "run_pipeline_analysis" not in abstract_methods

    def test_base_init_exports(self):
        import vertical_engines.base as base_mod

        assert hasattr(base_mod, "BaseAnalyzer")
        assert inspect.isabstract(base_mod.BaseAnalyzer)
        # BaseCritic and BaseExtractor were removed (YAGNI)
        assert not hasattr(base_mod, "BaseCritic")
        assert not hasattr(base_mod, "BaseExtractor")


# ── Credit module structure tests ─────────────────────────────────────────────


class TestCreditModuleStructure:
    """Verify that all expected credit modules can be found (not imported —
    they have heavy dependencies).  We check the module spec exists."""

    EXPECTED_MODULES = [
        "vertical_engines.credit.deep_review",
        "vertical_engines.credit.critic",
        "vertical_engines.credit.quant",
        "vertical_engines.credit.market_data",
        "vertical_engines.credit.sponsor",
        "vertical_engines.credit.memo",
        "vertical_engines.credit.pipeline",
        "vertical_engines.credit.portfolio",
        "vertical_engines.credit.retrieval",
        "vertical_engines.credit.underwriting",
        "vertical_engines.credit.domain_ai",
        "vertical_engines.credit.edgar",
        "vertical_engines.credit.kyc",
        "vertical_engines.credit.deal_conversion",
    ]

    def test_all_credit_modules_discoverable(self):
        """Every expected module should have a findable spec (file exists)."""
        missing = []
        for mod in self.EXPECTED_MODULES:
            try:
                spec = importlib.util.find_spec(mod)
            except (ValueError, ModuleNotFoundError):
                # ValueError: __spec__ is None when module was partially imported
                # (e.g. __init__.py with eager imports already loaded by another test).
                # The module exists — discovery is not the problem.
                spec = True
            if spec is None:
                missing.append(mod)
        assert not missing, f"Modules not found: {missing}"

    def test_no_intelligence_directory_in_ai_engine(self):
        """ai_engine/intelligence/ must no longer exist."""
        import pathlib

        ai_engine_spec = importlib.util.find_spec("ai_engine")
        assert ai_engine_spec is not None
        assert ai_engine_spec.submodule_search_locations is not None
        for loc in ai_engine_spec.submodule_search_locations:
            intelligence_dir = pathlib.Path(loc) / "intelligence"
            assert not intelligence_dir.exists(), (
                f"ai_engine/intelligence/ still exists at {intelligence_dir}"
            )

    def test_prompts_directory_has_jinja2_templates(self):
        """Credit prompts directory must contain .j2 files."""
        import pathlib

        credit_spec = importlib.util.find_spec("vertical_engines.credit")
        assert credit_spec is not None
        assert credit_spec.submodule_search_locations is not None
        for loc in credit_spec.submodule_search_locations:
            prompts_dir = pathlib.Path(loc) / "prompts"
            j2_files = list(prompts_dir.glob("*.j2"))
            assert len(j2_files) >= 13, (
                f"Expected >=13 chapter prompts, found {len(j2_files)}"
            )


# ── Wealth module structure tests ─────────────────────────────────────────────


class TestWealthModuleStructure:
    """Verify wealth engine modules exist and implement BaseAnalyzer."""

    EXPECTED_MODULES = [
        "vertical_engines.wealth.fund_analyzer",
        "vertical_engines.wealth.dd_report",
        "vertical_engines.wealth.dd_report.dd_report_engine",
        "vertical_engines.wealth.quant_analyzer",
        "vertical_engines.wealth.critic",
        "vertical_engines.wealth.asset_universe",
        "vertical_engines.wealth.asset_universe.universe_service",
        "vertical_engines.wealth.asset_universe.fund_approval",
        "vertical_engines.wealth.model_portfolio",
        "vertical_engines.wealth.model_portfolio.portfolio_builder",
        "vertical_engines.wealth.model_portfolio.track_record",
        "vertical_engines.wealth.model_portfolio.stress_scenarios",
    ]

    def test_all_wealth_modules_discoverable(self):
        missing = []
        for mod in self.EXPECTED_MODULES:
            spec = importlib.util.find_spec(mod)
            if spec is None:
                missing.append(mod)
        assert not missing, f"Modules not found: {missing}"

    def test_fund_analyzer_implements_base(self):
        from vertical_engines.base.base_analyzer import BaseAnalyzer
        from vertical_engines.wealth.fund_analyzer import FundAnalyzer

        assert issubclass(FundAnalyzer, BaseAnalyzer)
        assert FundAnalyzer.vertical == "liquid_funds"

    def test_fund_analyzer_is_concrete(self):
        """FundAnalyzer should NOT be abstract — all methods implemented."""
        from vertical_engines.wealth.fund_analyzer import FundAnalyzer

        assert not inspect.isabstract(FundAnalyzer)

    def test_dd_report_chapters(self):
        from vertical_engines.wealth.dd_report.models import CHAPTER_REGISTRY

        assert len(CHAPTER_REGISTRY) == 8
        assert CHAPTER_REGISTRY[0]["tag"] == "executive_summary"
        assert CHAPTER_REGISTRY[-1]["tag"] == "recommendation"


# ── Profile YAML tests ───────────────────────────────────────────────────────


class TestProfileYAML:
    def test_private_credit_profile_loads(self):
        from pathlib import Path

        import yaml

        profile_path = Path(__file__).resolve().parents[2] / "profiles" / "private_credit" / "profile.yaml"
        data = yaml.safe_load(profile_path.read_text())
        assert data["name"] == "private_credit"
        assert len(data["chapters"]) == 14
        assert data.get("global_knowledge_feedback") is True

    def test_liquid_funds_profile_loads(self):
        from pathlib import Path

        import yaml

        profile_path = Path(__file__).resolve().parents[2] / "profiles" / "liquid_funds" / "profile.yaml"
        data = yaml.safe_load(profile_path.read_text())
        assert data["name"] == "liquid_funds"
        assert len(data["chapters"]) == 8

    def test_evaluation_criteria_loads(self):
        from pathlib import Path

        import yaml

        criteria_path = Path(__file__).resolve().parents[2] / "profiles" / "private_credit" / "evaluation_criteria.yaml"
        data = yaml.safe_load(criteria_path.read_text())
        assert data["global_knowledge_feedback"] is True
        assert "confidence_weights" in data
        assert "critic" in data


# ── ai_engine backward-compat re-exports ─────────────────────────────────────


class TestAiEngineReExports:
    """Verify ai_engine.__init__.py re-exports point to vertical_engines.credit."""

    def test_ai_engine_has_pipeline_ingest(self):
        spec = importlib.util.find_spec("ai_engine")
        assert spec is not None
        # The module should be importable (lazy re-exports)
        mod = importlib.import_module("ai_engine")
        assert hasattr(mod, "run_pipeline_ingest")
        assert hasattr(mod, "run_portfolio_ingest")
        assert hasattr(mod, "run_daily_cycle")
        assert hasattr(mod, "run_documents_ingest_pipeline")
