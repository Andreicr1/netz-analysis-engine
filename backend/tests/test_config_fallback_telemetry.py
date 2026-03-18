"""Tests for CFG-03 — YAML fallback telemetry and source-chain contract."""

from __future__ import annotations

import logging

from app.core.config.config_service import (
    _YAML_FALLBACK_DIR,
    _YAML_FALLBACK_MAP,
    ConfigService,
)


class TestSourceChainDocumentation:
    """Config-source hierarchy is documented and testable."""

    def test_get_docstring_documents_hierarchy(self):
        doc = ConfigService.get.__doc__
        assert doc is not None
        assert "In-process TTLCache" in doc
        assert "DB override" in doc
        assert "DB default" in doc
        assert "YAML fallback" in doc
        assert "Total miss" in doc

    def test_yaml_fallback_map_is_explicit_contract(self):
        """Every YAML fallback entry must map to a real file."""
        for (vertical, config_type), rel_path in _YAML_FALLBACK_MAP.items():
            full = _YAML_FALLBACK_DIR / rel_path
            assert full.exists(), (
                f"YAML fallback file missing for ({vertical}, {config_type}): {full}"
            )

    def test_yaml_fallback_dir_is_project_root(self):
        """_YAML_FALLBACK_DIR must be the project root, not backend/."""
        assert (_YAML_FALLBACK_DIR / "calibration").is_dir(), (
            f"_YAML_FALLBACK_DIR does not point to project root: {_YAML_FALLBACK_DIR}"
        )
        assert (_YAML_FALLBACK_DIR / "profiles").is_dir()


class TestYamlFallbackTelemetry:
    """Every YAML fallback event emits structured telemetry."""

    def test_yaml_fallback_success_emits_structured_log(self, caplog):
        """Successful YAML fallback emits event with source chain info."""
        key = next(iter(_YAML_FALLBACK_MAP))
        with caplog.at_level(logging.ERROR, logger="app.core.config.config_service"):
            result = ConfigService._yaml_fallback(key[0], key[1])
        assert result is not None
        assert isinstance(result, dict)
        assert "config system degraded" in caplog.text

    def test_yaml_fallback_no_mapping_returns_none(self):
        """Config type with no YAML mapping returns None silently."""
        result = ConfigService._yaml_fallback("nonexistent", "bogus")
        assert result is None

    def test_yaml_fallback_file_missing_emits_error(self, caplog):
        """Missing file emits structured error."""
        from app.core.config import config_service as cs

        original_map = cs._YAML_FALLBACK_MAP.copy()
        cs._YAML_FALLBACK_MAP[("test_v", "test_t")] = "nonexistent/path/file.yaml"
        try:
            with caplog.at_level(logging.ERROR, logger="app.core.config.config_service"):
                result = ConfigService._yaml_fallback("test_v", "test_t")
        finally:
            cs._YAML_FALLBACK_MAP = original_map

        assert result is None
        assert "file missing" in caplog.text.lower()

    def test_yaml_fallback_parse_error_emits_error(self, tmp_path, caplog):
        """YAML parse failure emits structured error, returns None."""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text(":\n  bad: [unclosed", encoding="utf-8")

        from app.core.config import config_service as cs

        original_map = cs._YAML_FALLBACK_MAP.copy()
        original_dir = cs._YAML_FALLBACK_DIR
        cs._YAML_FALLBACK_MAP = {("test_v", "test_t"): bad_file.name}
        cs._YAML_FALLBACK_DIR = tmp_path
        try:
            with caplog.at_level(logging.ERROR, logger="app.core.config.config_service"):
                result = ConfigService._yaml_fallback("test_v", "test_t")
        finally:
            cs._YAML_FALLBACK_MAP = original_map
            cs._YAML_FALLBACK_DIR = original_dir

        assert result is None
        assert "parse failure" in caplog.text.lower()

    def test_yaml_fallback_non_dict_emits_error(self, tmp_path, caplog):
        """YAML that parses to a non-dict emits structured error."""
        list_file = tmp_path / "list.yaml"
        list_file.write_text("- item1\n- item2\n", encoding="utf-8")

        from app.core.config import config_service as cs

        original_map = cs._YAML_FALLBACK_MAP.copy()
        original_dir = cs._YAML_FALLBACK_DIR
        cs._YAML_FALLBACK_MAP = {("test_v", "test_t"): list_file.name}
        cs._YAML_FALLBACK_DIR = tmp_path
        try:
            with caplog.at_level(logging.ERROR, logger="app.core.config.config_service"):
                result = ConfigService._yaml_fallback("test_v", "test_t")
        finally:
            cs._YAML_FALLBACK_MAP = original_map
            cs._YAML_FALLBACK_DIR = original_dir

        assert result is None
        assert "non-dict" in caplog.text.lower()


class TestPromptMetadataTelemetry:
    """Prompt metadata parse failures produce typed degraded signal."""

    def test_parse_error_returns_marker(self, tmp_path):
        """YAML parse error in metadata returns _metadata_parse_error marker."""
        from ai_engine.prompts.registry import PromptRegistry

        template_dir = tmp_path / "prompts"
        template_dir.mkdir()
        bad_template = template_dir / "bad_meta.j2"
        bad_template.write_text(
            "{#- metadata\n  bad: [unclosed\n-#}\nHello {{ name }}",
            encoding="utf-8",
        )

        registry = PromptRegistry(prompts_dir=template_dir)
        meta = registry.get_metadata("bad_meta.j2")
        assert meta.get("_metadata_parse_error") is True

    def test_valid_metadata_returns_dict(self, tmp_path):
        """Valid YAML metadata returns parsed dict without error marker."""
        from ai_engine.prompts.registry import PromptRegistry

        template_dir = tmp_path / "prompts"
        template_dir.mkdir()
        good = template_dir / "good.j2"
        good.write_text(
            "{#- metadata\n  stage: test\n  version: 1\n-#}\nHello",
            encoding="utf-8",
        )

        registry = PromptRegistry(prompts_dir=template_dir)
        meta = registry.get_metadata("good.j2")
        assert meta["stage"] == "test"
        assert meta["version"] == 1
        assert "_metadata_parse_error" not in meta

    def test_no_metadata_returns_empty(self, tmp_path):
        """Template without metadata block returns empty dict."""
        from ai_engine.prompts.registry import PromptRegistry

        template_dir = tmp_path / "prompts"
        template_dir.mkdir()
        plain = template_dir / "plain.j2"
        plain.write_text("Just a template", encoding="utf-8")

        registry = PromptRegistry(prompts_dir=template_dir)
        meta = registry.get_metadata("plain.j2")
        assert meta == {}
