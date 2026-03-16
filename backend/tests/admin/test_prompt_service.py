"""Tests for PromptService — validation, preview, snapshot."""

from __future__ import annotations

from app.core.prompts.prompt_service import PromptService
from app.core.prompts.schemas import PromptContent


class TestPromptValidation:
    def test_valid_template(self):
        result = PromptService.validate("Hello {{ name }}, welcome to {{ company }}.")
        assert result.valid is True
        assert result.errors == []

    def test_valid_template_with_control_flow(self):
        result = PromptService.validate("{% if show %}Show this{% endif %}")
        assert result.valid is True

    def test_syntax_error_unclosed_tag(self):
        result = PromptService.validate("Hello {{ name }")
        assert result.valid is False
        assert len(result.errors) > 0
        assert "Syntax error" in result.errors[0]

    def test_syntax_error_unclosed_block(self):
        result = PromptService.validate("{% if true %}no endif")
        assert result.valid is False

    def test_dangerous_dunder_class(self):
        result = PromptService.validate("{{ obj.__class__.__mro__ }}")
        assert result.valid is False
        assert any("forbidden" in e.lower() or "dunder" in e.lower() for e in result.errors)

    def test_dangerous_dunder_import(self):
        result = PromptService.validate("{{ __import__('os') }}")
        assert result.valid is False

    def test_dangerous_dunder_globals(self):
        result = PromptService.validate("{{ config.__globals__ }}")
        assert result.valid is False

    def test_empty_template_valid(self):
        result = PromptService.validate("")
        assert result.valid is True

    def test_plain_text_valid(self):
        result = PromptService.validate("Just plain text, no Jinja2.")
        assert result.valid is True


class TestPromptPreview:
    def test_simple_render(self):
        result = PromptService.preview(
            content="Hello {{ name }}, you have {{ count }} items.",
            sample_data={"name": "Alice", "count": 5},
        )
        assert result.rendered == "Hello Alice, you have 5 items."
        assert result.errors is None

    def test_render_with_loop(self):
        result = PromptService.preview(
            content="{% for item in items %}{{ item }} {% endfor %}",
            sample_data={"items": ["A", "B", "C"]},
        )
        assert result.rendered.strip() == "A B C"

    def test_render_syntax_error(self):
        result = PromptService.preview(
            content="Hello {{ name }",
            sample_data={"name": "Alice"},
        )
        assert result.rendered == ""
        assert result.errors is not None
        assert len(result.errors) > 0

    def test_render_blocks_dunder_access(self):
        result = PromptService.preview(
            content="{{ obj.__class__.__mro__ }}",
            sample_data={"obj": "test"},
        )
        assert result.rendered == ""
        assert result.errors is not None
        assert any("forbidden" in e.lower() or "dunder" in e.lower() for e in result.errors)

    def test_render_missing_variable(self):
        """Missing variables should render as empty string (Jinja2 default)."""
        result = PromptService.preview(
            content="Hello {{ name }}, welcome.",
            sample_data={},
        )
        assert result.rendered == "Hello , welcome."
        assert result.errors is None


class TestPromptFilterWhitelist:
    """Verify AdminSandboxedEnvironment enforces _SAFE_FILTERS."""

    def test_safe_filter_allowed(self):
        result = PromptService.preview(
            content="{{ name | upper }}",
            sample_data={"name": "alice"},
        )
        assert result.rendered == "ALICE"
        assert result.errors is None

    def test_safe_filter_default_allowed(self):
        result = PromptService.preview(
            content="{{ missing | default('fallback') }}",
            sample_data={},
        )
        assert result.rendered == "fallback"
        assert result.errors is None

    def test_unsafe_filter_blocked(self):
        result = PromptService.preview(
            content="{{ '<b>x</b>' | forceescape }}",
            sample_data={},
        )
        assert result.rendered == ""
        assert result.errors is not None
        assert any("filter" in e.lower() for e in result.errors)

    def test_unsafe_filter_xmlattr_blocked(self):
        result = PromptService.preview(
            content="{{ items | xmlattr }}",
            sample_data={"items": {"class": "x"}},
        )
        assert result.rendered == ""
        assert result.errors is not None
        assert any("filter" in e.lower() for e in result.errors)

    def test_chained_safe_filters_allowed(self):
        result = PromptService.preview(
            content="{{ name | lower | capitalize }}",
            sample_data={"name": "BOB"},
        )
        assert result.rendered == "Bob"
        assert result.errors is None


class TestPromptSnapshot:
    def test_snapshot_creates_frozen_dict(self):
        prompts = [
            PromptContent(
                vertical="credit",
                template_name="ch01_exec.j2",
                content="Executive summary for {{ deal_name }}",
                source_level="filesystem",
            ),
            PromptContent(
                vertical="credit",
                template_name="ch02_risk.j2",
                content="Risk analysis for {{ deal_name }}",
                source_level="org",
                version=3,
            ),
        ]
        snapshot = PromptService.snapshot_prompts(prompts)
        assert snapshot == {
            "ch01_exec.j2": "Executive summary for {{ deal_name }}",
            "ch02_risk.j2": "Risk analysis for {{ deal_name }}",
        }

    def test_snapshot_empty_list(self):
        snapshot = PromptService.snapshot_prompts([])
        assert snapshot == {}
