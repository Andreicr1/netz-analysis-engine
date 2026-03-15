"""Tests for vertical_engines structure — imports, base interfaces, credit module."""

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
        assert "run_pipeline_analysis" in abstract_methods

    def test_base_extractor_is_abstract(self):
        from vertical_engines.base.base_extractor import BaseExtractor

        assert inspect.isabstract(BaseExtractor)
        assert "extract_structured" in BaseExtractor.__abstractmethods__

    def test_base_critic_is_abstract(self):
        from vertical_engines.base.base_critic import BaseCritic

        assert inspect.isabstract(BaseCritic)
        assert "critique" in BaseCritic.__abstractmethods__

    def test_base_init_exports(self):
        from vertical_engines.base import BaseAnalyzer, BaseCritic, BaseExtractor

        assert inspect.isabstract(BaseAnalyzer)
        assert inspect.isabstract(BaseCritic)
        assert inspect.isabstract(BaseExtractor)


# ── Credit module structure tests ─────────────────────────────────────────────


class TestCreditModuleStructure:
    """Verify that all expected credit modules can be found (not imported —
    they have heavy dependencies).  We check the module spec exists."""

    EXPECTED_MODULES = [
        "vertical_engines.credit.deep_review",
        "vertical_engines.credit.ic_critic_engine",
        "vertical_engines.credit.ic_quant_engine",
        "vertical_engines.credit.market_data_engine",
        "vertical_engines.credit.sponsor_engine",
        "vertical_engines.credit.memo_chapter_engine",
        "vertical_engines.credit.memo_book_generator",
        "vertical_engines.credit.pipeline_engine",
        "vertical_engines.credit.pipeline_intelligence",
        "vertical_engines.credit.portfolio_intelligence",
        "vertical_engines.credit.retrieval_governance",
        "vertical_engines.credit.tone_normalizer",
        "vertical_engines.credit.underwriting_artifact",
        "vertical_engines.credit.deep_review_corpus",
        "vertical_engines.credit.deep_review_helpers",
        "vertical_engines.credit.deep_review_policy",
        "vertical_engines.credit.deep_review_prompts",
        "vertical_engines.credit.deep_review_confidence",
        "vertical_engines.credit.memo_evidence_pack",
        "vertical_engines.credit.domain_ai_engine",
        "vertical_engines.credit.batch_client",
        "vertical_engines.credit.ic_edgar_engine",
        "vertical_engines.credit.kyc_client",
        "vertical_engines.credit.kyc_models",
        "vertical_engines.credit.kyc_pipeline_screening",
        "vertical_engines.credit.memo_chapter_prompts",
        "vertical_engines.credit.deal_conversion_engine",
    ]

    def test_all_credit_modules_discoverable(self):
        """Every expected module should have a findable spec (file exists)."""
        missing = []
        for mod in self.EXPECTED_MODULES:
            spec = importlib.util.find_spec(mod)
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
