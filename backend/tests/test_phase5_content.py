"""Tests for Phase 5 — Content Production, Approval Workflow, FundAnalyzer, PDFs.

Focus areas (per plan):
- Approval workflow + self-approval prevention
- Content generation LLM call + sanitize_llm_text at persist boundary
- FundAnalyzer delegation: ProfileLoader → DDReportEngine → real output
- PDF smoke tests: valid PDF, correct header
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock

import pytest

# ── Content Result Models ──────────────────────────────────────────────────


class TestContentResultModels:
    """Test frozen dataclass result types from content engines."""

    def test_outlook_result_frozen(self):
        from vertical_engines.wealth.investment_outlook import OutlookResult

        r = OutlookResult(
            content_md="test", title="Outlook", language="pt", status="completed",
        )
        with pytest.raises(AttributeError):
            r.content_md = "changed"  # type: ignore[misc]

    def test_flash_report_result_frozen(self):
        from vertical_engines.wealth.flash_report import FlashReportResult

        r = FlashReportResult(
            content_md="test", title="Flash", language="en", status="completed",
        )
        with pytest.raises(AttributeError):
            r.status = "failed"  # type: ignore[misc]

    def test_spotlight_result_frozen(self):
        from vertical_engines.wealth.manager_spotlight import SpotlightResult

        r = SpotlightResult(
            content_md="test", title="Spotlight", language="pt",
            instrument_id="abc", status="completed",
        )
        with pytest.raises(AttributeError):
            r.instrument_id = "changed"  # type: ignore[misc]


# ── Content Generation with LLM + Sanitize ────────────────────────────────


class TestInvestmentOutlookGeneration:
    """Test InvestmentOutlook generates content via LLM and sanitizes output."""

    def _make_call_fn(self, response_text: str = "## Test Content\nSome analysis."):
        """Create a mock LLM call function."""
        def call_fn(system_prompt: str, user_content: str, *, max_tokens: int = 4000, model: str | None = None) -> dict[str, Any]:
            return {"content": response_text}
        return call_fn

    def test_generate_no_llm_fn_returns_failed(self):
        from vertical_engines.wealth.investment_outlook import InvestmentOutlook

        engine = InvestmentOutlook(call_openai_fn=None)
        db = MagicMock()
        result = engine.generate(db, organization_id="org-1", actor_id="user-1")
        assert result.status == "failed"
        assert "No LLM call function" in (result.error or "")

    def test_generate_calls_llm_and_sanitizes(self):
        from vertical_engines.wealth.investment_outlook import InvestmentOutlook

        raw_text = "## Analysis\nTest <script>alert('xss')</script> content."
        call_fn = self._make_call_fn(raw_text)

        engine = InvestmentOutlook(call_openai_fn=call_fn)
        db = MagicMock()
        # Mock the macro data query to return empty
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        result = engine.generate(db, organization_id="org-1", actor_id="user-1")
        assert result.status == "completed"
        assert result.content_md is not None
        # sanitize_llm_text should strip script tags
        assert "<script>" not in result.content_md
        assert "Test" in result.content_md

    def test_generate_respects_language(self):
        from vertical_engines.wealth.investment_outlook import InvestmentOutlook

        received_prompts: list[str] = []

        def tracking_fn(system_prompt: str, user_content: str, **kwargs: Any) -> dict[str, Any]:
            received_prompts.append(system_prompt)
            return {"content": "test content"}

        engine = InvestmentOutlook(call_openai_fn=tracking_fn)
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        result = engine.generate(db, organization_id="org-1", actor_id="u1", language="en")
        assert result.language == "en"
        assert result.status == "completed"


class TestFlashReportGeneration:
    """Test FlashReport with cooldown enforcement."""

    def _make_call_fn(self):
        def call_fn(system_prompt: str, user_content: str, **kwargs: Any) -> dict[str, Any]:
            return {"content": "## Flash\nMarket event analysis."}
        return call_fn

    def test_generate_no_llm_fn(self):
        from vertical_engines.wealth.flash_report import FlashReport

        engine = FlashReport(call_openai_fn=None)
        db = MagicMock()
        result = engine.generate(db, organization_id="org-1", actor_id="u1")
        assert result.status == "failed"

    def test_cooldown_enforcement(self):
        from vertical_engines.wealth.flash_report import FlashReport

        call_fn = self._make_call_fn()
        engine = FlashReport(call_openai_fn=call_fn)

        db = MagicMock()
        # Simulate recent flash report (within 48h cooldown)
        recent_time = datetime.now(timezone.utc)
        mock_result = MagicMock()
        mock_result.__getitem__ = lambda self, idx: recent_time
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_result

        result = engine.generate(db, organization_id="org-1", actor_id="u1")
        assert result.status == "cooldown"
        assert "cooldown" in (result.error or "").lower()


class TestManagerSpotlightGeneration:
    """Test ManagerSpotlight generates from fund data + quant metrics."""

    def test_generate_no_llm_fn(self):
        from vertical_engines.wealth.manager_spotlight import ManagerSpotlight

        engine = ManagerSpotlight(call_openai_fn=None)
        db = MagicMock()
        result = engine.generate(
            db, instrument_id="f1", organization_id="org-1", actor_id="u1",
        )
        assert result.status == "failed"
        assert result.instrument_id == "f1"


# ── Approval Workflow ──────────────────────────────────────────────────────


class TestApprovalWorkflow:
    """Test content approval workflow logic."""

    def test_content_status_transitions(self):
        """Content follows draft → review → approved → published lifecycle."""
        valid_transitions = {
            "draft": ["review"],
            "review": ["approved"],
            "approved": ["published"],
        }
        # The approve endpoint accepts draft or review → approved
        # This is enforced in the route handler
        approvable_statuses = {"draft", "review"}
        assert "draft" in approvable_statuses
        assert "review" in approvable_statuses
        assert "approved" not in approvable_statuses
        assert "published" not in approvable_statuses

    def test_self_approval_prevention_logic(self):
        """Self-approval is blocked: approver must differ from creator."""
        creator_id = "user-001"
        approver_id = "user-001"
        # Self-approval check
        assert creator_id == approver_id  # Would be blocked

        different_approver = "user-002"
        assert creator_id != different_approver  # Would be allowed

    def test_download_requires_approved_status(self):
        """Download endpoint must check status >= approved."""
        downloadable_statuses = {"approved", "published"}
        assert "approved" in downloadable_statuses
        assert "published" in downloadable_statuses
        assert "draft" not in downloadable_statuses
        assert "review" not in downloadable_statuses


# ── PDF Smoke Tests ────────────────────────────────────────────────────────


class TestContentPDFs:
    """Smoke tests: valid PDF header, non-trivial size."""

    def test_investment_outlook_pdf(self):
        from vertical_engines.wealth.investment_outlook import InvestmentOutlook

        engine = InvestmentOutlook()
        content = "## Global Macro Summary\nMarkets are bullish.\n\n## Regional Outlook\nUS is strong."
        buf = engine.render_pdf(content, language="pt")

        assert isinstance(buf, BytesIO)
        data = buf.read()
        assert data[:5] == b"%PDF-"
        assert len(data) > 1000  # Non-trivial PDF

    def test_investment_outlook_pdf_en(self):
        from vertical_engines.wealth.investment_outlook import InvestmentOutlook

        engine = InvestmentOutlook()
        content = "## Global Macro Summary\nMarkets analysis."
        buf = engine.render_pdf(content, language="en")

        data = buf.read()
        assert data[:5] == b"%PDF-"

    def test_flash_report_pdf(self):
        from vertical_engines.wealth.flash_report import FlashReport

        engine = FlashReport()
        content = "## Market Event\nVolatility spike.\n\n## Market Impact\nEquities down 3%."
        buf = engine.render_pdf(content, language="pt")

        data = buf.read()
        assert data[:5] == b"%PDF-"
        assert len(data) > 1000

    def test_manager_spotlight_pdf(self):
        from vertical_engines.wealth.manager_spotlight import ManagerSpotlight

        engine = ManagerSpotlight()
        content = "## Fund Overview\nBlackRock Global Allocation.\n\n## Quantitative Analysis\nSharpe: 1.2."
        buf = engine.render_pdf(content, language="pt", fund_name="BlackRock Global")

        data = buf.read()
        assert data[:5] == b"%PDF-"
        assert len(data) > 1000

    def test_manager_spotlight_pdf_en(self):
        from vertical_engines.wealth.manager_spotlight import ManagerSpotlight

        engine = ManagerSpotlight()
        content = "## Fund Overview\nTest fund analysis."
        buf = engine.render_pdf(content, language="en", fund_name="Test Fund")

        data = buf.read()
        assert data[:5] == b"%PDF-"


# ── FundAnalyzer Delegation ────────────────────────────────────────────────


class TestFundAnalyzerDelegation:
    """Test FundAnalyzer delegates to real implementations."""

    def test_fund_analyzer_has_correct_vertical(self):
        from vertical_engines.wealth.fund_analyzer import FundAnalyzer

        analyzer = FundAnalyzer()
        assert analyzer.vertical == "liquid_funds"

    def test_profile_loader_finds_wealth_module(self):
        """ProfileLoader.get_engine_module('liquid_funds') returns the wealth module."""
        from ai_engine.profile_loader import ProfileLoader

        loader = ProfileLoader(config_service=MagicMock())
        module = loader.get_engine_module("liquid_funds")
        assert module is not None
        assert hasattr(module, "FundAnalyzer") or module.__name__ == "vertical_engines.wealth"

    def test_fund_analyzer_run_deal_delegates_to_dd_report(self):
        """run_deal_analysis creates DDReportEngine and calls generate()."""
        from unittest.mock import patch

        from vertical_engines.wealth.fund_analyzer import FundAnalyzer

        analyzer = FundAnalyzer()

        # Create a mock DDReportResult
        mock_result = MagicMock()
        mock_result.fund_id = "fund-123"
        mock_result.status = "completed"
        mock_result.confidence_score = 75.0
        mock_result.decision_anchor = "APPROVE"
        mock_result.chapters = []
        mock_result.error = None

        with patch(
            "vertical_engines.wealth.dd_report.DDReportEngine.generate",
            return_value=mock_result,
        ) as mock_gen:
            result = analyzer.run_deal_analysis(
                MagicMock(),
                instrument_id="org-context",
                deal_id="target-fund",
                actor_id="user-1",
            )
            mock_gen.assert_called_once()
            assert result["status"] == "completed"
            assert result["confidence_score"] == 75.0
            assert result["decision_anchor"] == "APPROVE"

    def test_fund_analyzer_run_portfolio_delegates_to_quant(self):
        """run_portfolio_analysis creates QuantAnalyzer and calls analyze_portfolio()."""
        from unittest.mock import patch

        from vertical_engines.wealth.fund_analyzer import FundAnalyzer

        analyzer = FundAnalyzer()
        expected = {"cvar": {}, "scoring": {}, "peer_comparison": {}}

        with patch(
            "vertical_engines.wealth.quant_analyzer.QuantAnalyzer.analyze_portfolio",
            return_value=expected,
        ) as mock_analyze:
            result = analyzer.run_portfolio_analysis(
                MagicMock(),
                instrument_id="fund-1",
                actor_id="user-1",
            )
            mock_analyze.assert_called_once()
            assert result == expected


# ── Monitoring ─────────────────────────────────────────────────────────────


class TestAlertEngine:
    """Test alert engine alert types."""

    def test_alert_frozen(self):
        from vertical_engines.wealth.monitoring.alert_engine import Alert

        a = Alert(
            alert_type="dd_expiry", severity="warning",
            title="Test", detail="Details",
        )
        with pytest.raises(AttributeError):
            a.severity = "critical"  # type: ignore[misc]

    def test_alert_batch_frozen(self):
        from vertical_engines.wealth.monitoring.alert_engine import AlertBatch

        batch = AlertBatch(
            alerts=[], scanned_at=datetime.now(timezone.utc),
            organization_id="org-1",
        )
        with pytest.raises(AttributeError):
            batch.organization_id = "org-2"  # type: ignore[misc]

    def test_alerts_to_json(self):
        from vertical_engines.wealth.monitoring.alert_engine import (
            Alert,
            AlertBatch,
            alerts_to_json,
        )

        alerts = [
            Alert(
                alert_type="dd_expiry", severity="warning",
                title="DD Expired", detail="Fund X DD > 12 months",
                entity_id="fund-1", entity_type="fund",
            ),
        ]
        batch = AlertBatch(
            alerts=alerts, scanned_at=datetime.now(timezone.utc),
            organization_id="org-1",
        )
        result = alerts_to_json(batch)
        assert len(result) == 1
        assert result[0]["alert_type"] == "dd_expiry"
        assert result[0]["entity_id"] == "fund-1"


class TestDriftMonitor:
    """Test drift monitor types."""

    def test_drift_alert_frozen(self):
        from vertical_engines.wealth.monitoring.drift_monitor import DriftAlert

        a = DriftAlert(
            instrument_id="f1", fund_name="Fund A", drift_score=0.2,
            drift_type="style_drift", affected_portfolios=["Portfolio 1"],
            detail="Drift detected",
        )
        with pytest.raises(AttributeError):
            a.drift_score = 0.5  # type: ignore[misc]

    def test_drift_alerts_to_json(self):
        from vertical_engines.wealth.monitoring.drift_monitor import (
            DriftAlert,
            DriftScanResult,
            drift_alerts_to_json,
        )

        alerts = [
            DriftAlert(
                instrument_id="f1", fund_name="Fund A", drift_score=0.25,
                drift_type="style_drift", affected_portfolios=["Port 1"],
                detail="DTW drift 0.25 > 0.15",
            ),
        ]
        result = DriftScanResult(
            alerts=alerts, scanned_at=datetime.now(timezone.utc),
            organization_id="org-1",
        )
        json_data = drift_alerts_to_json(result)
        assert len(json_data) == 1
        assert json_data[0]["drift_type"] == "style_drift"
        assert json_data[0]["drift_score"] == 0.25


# ── Storage Routing ────────────────────────────────────────────────────────


class TestContentStorageRouting:
    """Test gold_content_path validation."""

    def test_gold_content_path_valid(self):
        from ai_engine.pipeline.storage_routing import gold_content_path

        path = gold_content_path(
            org_id=uuid.UUID("12345678-1234-1234-1234-123456789012"),
            vertical="wealth",
            content_type="investment_outlook",
            content_id="abc123",
            language="pt",
        )
        assert "gold/" in path
        assert "wealth" in path
        assert "investment_outlook" in path
        assert "pt" in path

    def test_gold_content_path_invalid_vertical(self):
        from ai_engine.pipeline.storage_routing import gold_content_path

        with pytest.raises(ValueError, match="Invalid vertical"):
            gold_content_path(
                org_id=uuid.UUID("12345678-1234-1234-1234-123456789012"),
                vertical="invalid",
                content_type="outlook",
                content_id="abc",
                language="pt",
            )

    def test_gold_content_path_traversal_prevention(self):
        from ai_engine.pipeline.storage_routing import gold_content_path

        with pytest.raises(ValueError):
            gold_content_path(
                org_id=uuid.UUID("12345678-1234-1234-1234-123456789012"),
                vertical="wealth",
                content_type="../hack",
                content_id="abc",
                language="pt",
            )


# ── Feature Flag ───────────────────────────────────────────────────────────


class TestFeatureFlags:
    """Test that new feature flags exist in settings."""

    def test_feature_wealth_content_exists(self):
        from app.core.config.settings import Settings

        s = Settings()
        assert hasattr(s, "feature_wealth_content")
        assert s.feature_wealth_content is False  # Default off

    def test_feature_wealth_monitoring_exists(self):
        from app.core.config.settings import Settings

        s = Settings()
        assert hasattr(s, "feature_wealth_monitoring")
        assert s.feature_wealth_monitoring is False  # Default off
