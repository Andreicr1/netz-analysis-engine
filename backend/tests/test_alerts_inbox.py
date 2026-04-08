"""Tests for the Phase 7 Alerts Unification routes.

Three layers, mirroring the test_model_portfolios_allowed_actions.py
pattern:

1. **Route smoke tests** — confirm the new endpoints are mounted and
   require auth (no DB required). 401 responses prove the routes are
   wired in; 404 would mean the router never registered.

2. **Severity normalization unit tests** — exercise the pure mappers
   so the unified scale (info|warning|critical) is locked.

3. **Mapper unit tests** — project synthetic ORM rows onto
   ``UnifiedAlertRead`` so the title / subtitle / href derivation
   stays stable across refactors.

No DB fixtures needed — the route smoke tests hit the real router
with no auth header and assert 401. The unit tests work on plain
MagicMock-shaped objects.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

BASE = "/api/v1/alerts"

ALERT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
PORTFOLIO_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
INSTRUMENT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000c1")


# ── Route smoke tests (no DB) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_get_alerts_inbox_requires_auth(client: AsyncClient):
    """GET /alerts/inbox must require auth."""
    resp = await client.get(f"{BASE}/inbox")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_alerts_inbox_route_exists(client: AsyncClient):
    """401 (not 404) proves the alerts router is mounted."""
    resp = await client.get(f"{BASE}/inbox")
    assert resp.status_code != 404


@pytest.mark.asyncio
async def test_post_acknowledge_alert_requires_auth(client: AsyncClient):
    """POST /alerts/{source}/{id}/acknowledge must require auth."""
    resp = await client.post(
        f"{BASE}/drift/{ALERT_ID}/acknowledge",
        json={},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_acknowledge_alert_route_exists(client: AsyncClient):
    """401 (not 404) proves the acknowledge route is mounted."""
    resp = await client.post(
        f"{BASE}/drift/{ALERT_ID}/acknowledge",
        json={},
    )
    assert resp.status_code != 404


@pytest.mark.asyncio
async def test_get_portfolio_alert_count_requires_auth(client: AsyncClient):
    """GET /alerts/portfolio/{id}/count must require auth."""
    resp = await client.get(f"{BASE}/portfolio/{PORTFOLIO_ID}/count")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_portfolio_alert_count_route_exists(client: AsyncClient):
    """401 (not 404) proves the portfolio count route is mounted."""
    resp = await client.get(f"{BASE}/portfolio/{PORTFOLIO_ID}/count")
    assert resp.status_code != 404


# ── Severity normalization ─────────────────────────────────────────


def test_normalize_drift_severity_severe_to_critical():
    from app.domains.wealth.routes.alerts import _normalize_drift_severity

    assert _normalize_drift_severity("severe") == "critical"


def test_normalize_drift_severity_moderate_to_warning():
    from app.domains.wealth.routes.alerts import _normalize_drift_severity

    assert _normalize_drift_severity("moderate") == "warning"


def test_normalize_drift_severity_none_to_info():
    from app.domains.wealth.routes.alerts import _normalize_drift_severity

    assert _normalize_drift_severity("none") == "info"


def test_normalize_drift_severity_unknown_falls_back_to_info():
    """Unknown drift severities should never raise — they fall through
    to info per the conservative defaults."""
    from app.domains.wealth.routes.alerts import _normalize_drift_severity

    assert _normalize_drift_severity("unrecognized") == "info"


def test_normalize_portfolio_severity_passes_through():
    """portfolio_alerts already uses the unified scale — pass through."""
    from app.domains.wealth.routes.alerts import _normalize_portfolio_severity

    assert _normalize_portfolio_severity("info") == "info"
    assert _normalize_portfolio_severity("warning") == "warning"
    assert _normalize_portfolio_severity("critical") == "critical"


def test_normalize_portfolio_severity_unknown_falls_back_to_info():
    from app.domains.wealth.routes.alerts import _normalize_portfolio_severity

    assert _normalize_portfolio_severity("unrecognized") == "info"


# ── Mapper unit tests ──────────────────────────────────────────────


def _fake_drift_alert(severity: str = "severe") -> MagicMock:
    """Synthesize a StrategyDriftAlert-shaped MagicMock."""
    a = MagicMock()
    a.id = ALERT_ID
    a.instrument_id = INSTRUMENT_ID
    a.severity = severity
    a.status = "drift_detected"
    a.anomalous_count = 3
    a.total_metrics = 9
    a.detected_at = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    a.acknowledged_at = None
    a.acknowledged_by = None
    return a


def _fake_portfolio_alert(severity: str = "warning") -> MagicMock:
    a = MagicMock()
    a.id = ALERT_ID
    a.portfolio_id = PORTFOLIO_ID
    a.alert_type = "cvar_breach"
    a.severity = severity
    a.title = "CVaR breach"
    a.created_at = datetime(2026, 4, 8, 13, 0, tzinfo=timezone.utc)
    a.acknowledged_at = None
    a.acknowledged_by = None
    return a


def test_drift_to_unified_emits_critical_for_severe():
    from app.domains.wealth.routes.alerts import _drift_to_unified

    rendered = _drift_to_unified(_fake_drift_alert("severe"), "Vanguard 500 ETF")
    assert rendered.source == "drift"
    assert rendered.alert_type == "drift"
    assert rendered.severity == "critical"
    assert rendered.subject_kind == "instrument"
    assert rendered.subject_id == INSTRUMENT_ID
    assert rendered.subject_name == "Vanguard 500 ETF"
    assert "Vanguard 500 ETF" in rendered.title
    assert "3 of 9 metrics" in (rendered.subtitle or "")
    assert rendered.href is not None
    assert str(INSTRUMENT_ID) in rendered.href


def test_drift_to_unified_handles_missing_instrument_name():
    from app.domains.wealth.routes.alerts import _drift_to_unified

    rendered = _drift_to_unified(_fake_drift_alert("moderate"), None)
    assert rendered.severity == "warning"
    assert rendered.subject_name is None
    # Title falls back to a generic label rather than crashing.
    assert "Instrument" in rendered.title


def test_portfolio_to_unified_passes_through_title_and_severity():
    from app.domains.wealth.routes.alerts import _portfolio_to_unified

    rendered = _portfolio_to_unified(
        _fake_portfolio_alert("critical"), "Institutional Balanced",
    )
    assert rendered.source == "portfolio"
    assert rendered.alert_type == "cvar_breach"
    assert rendered.severity == "critical"
    assert rendered.title == "CVaR breach"
    assert rendered.subject_kind == "portfolio"
    assert rendered.subject_id == PORTFOLIO_ID
    assert rendered.subject_name == "Institutional Balanced"
    assert rendered.href is not None
    assert str(PORTFOLIO_ID) in rendered.href
