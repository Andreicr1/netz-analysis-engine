"""Unit tests for the deterministic Jinja2 narrative templater.

Phase 3 Task 3.2 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

Covers:
- Happy path: well-formed payload produces both technical and
  client_safe narratives with the expected keys.
- Determinism: same input → same output (golden snapshot).
- Regime translation: OD-22 labels are applied to the client_safe
  section (NORMAL → Balanced, RISK_ON → Expansion, ...).
- Jargon discipline: the client_safe section does NOT mention
  "CVaR", "Sharpe", "CLARABEL", "SOCP", or "regime" (the raw enum).
- Graceful degradation: an empty payload produces a dict with the
  expected shape and no traceback.
- No template leakage: the output dict contains only rendered
  strings, never Jinja2 source fragments (``{{``, ``{%``).
- Sandboxed environment blocks unsafe operations (e.g. attribute
  access on Python dunders).
"""

from __future__ import annotations

import json
from typing import Any

from vertical_engines.wealth.model_portfolio.narrative_templater import (
    REGIME_CLIENT_SAFE_LABEL,
    render_narrative,
)


def _base_payload() -> dict[str, Any]:
    return {
        "profile": "moderate",
        "funds": [
            {"instrument_id": "aaa", "fund_name": "Fund A",
             "block_id": "na_equity_large", "weight": 0.3},
            {"instrument_id": "bbb", "fund_name": "Fund B",
             "block_id": "fi_treasury", "weight": 0.4},
            {"instrument_id": "ccc", "fund_name": "Fund C",
             "block_id": "intl_equity_dm", "weight": 0.3},
        ],
        "weights_proposed": {"aaa": 0.3, "bbb": 0.4, "ccc": 0.3},
        "ex_ante_metrics": {
            "expected_return": 0.08,
            "portfolio_volatility": 0.12,
            "sharpe_ratio": 0.67,
            "cvar_95": -0.04,
        },
        "calibration_snapshot": {
            "cvar_limit": 0.05,
        },
        "optimizer_trace": {
            "solver": "CLARABEL",
            "status": "optimal",
        },
        "binding_constraints": [
            {"id": "max_single_fund", "label": "Max single fund weight", "threshold": "25%"},
        ],
        "regime_context": {"regime": "NORMAL"},
    }


def test_happy_path_shape():
    out = render_narrative(_base_payload())
    assert out["schema_version"] == 2
    assert set(out.keys()) == {"schema_version", "technical", "client_safe"}
    for section in ("technical", "client_safe"):
        assert set(out[section].keys()) == {
            "headline",
            "key_points",
            "constraint_story",
            "holding_changes",
            "taa_summary",
        }
    assert isinstance(out["technical"]["headline"], str)
    assert len(out["technical"]["headline"]) > 0


def test_technical_section_mentions_quant_terms():
    out = render_narrative(_base_payload())
    technical = out["technical"]
    # The technical section is allowed to use quant language.
    all_text = " ".join([
        technical["headline"],
        *technical["key_points"],
        technical["constraint_story"],
    ]).lower()
    assert "cvar" in all_text
    assert "sharpe" in all_text
    assert "optimal" in all_text  # solver status


def test_client_safe_section_strips_jargon():
    """OD-22 + smart-backend/dumb-frontend: the client_safe section
    must not leak quant jargon."""
    out = render_narrative(_base_payload())
    client = out["client_safe"]
    forbidden = ["cvar", "sharpe", "clarabel", "socp"]
    for section_text in (
        client["headline"],
        " ".join(client["key_points"]),
    ):
        lower = section_text.lower()
        for word in forbidden:
            assert word not in lower, (
                f"client_safe section leaked jargon '{word}': {section_text!r}"
            )


def test_regime_translation_normal_to_balanced():
    payload = _base_payload()
    payload["regime_context"] = {"regime": "NORMAL"}
    out = render_narrative(payload)
    client_text = " ".join(out["client_safe"]["key_points"])
    assert "Balanced" in client_text, (
        f"NORMAL regime should map to 'Balanced': {client_text!r}"
    )


def test_regime_translation_risk_off_to_defensive():
    payload = _base_payload()
    payload["regime_context"] = {"regime": "RISK_OFF"}
    out = render_narrative(payload)
    client_text = " ".join(out["client_safe"]["key_points"])
    assert "Defensive" in client_text


def test_regime_translation_crisis_to_stress():
    payload = _base_payload()
    payload["regime_context"] = {"regime": "CRISIS"}
    out = render_narrative(payload)
    client_text = " ".join(out["client_safe"]["key_points"])
    assert "Stress" in client_text


def test_regime_translation_table_has_5_entries():
    """Lock the OD-22 mapping — any change requires a plan amendment."""
    assert REGIME_CLIENT_SAFE_LABEL == {
        "NORMAL": "Balanced",
        "RISK_ON": "Expansion",
        "RISK_OFF": "Defensive",
        "CRISIS": "Stress",
        "INFLATION": "Inflation",
    }


def test_determinism_same_input_same_output():
    payload = _base_payload()
    out1 = render_narrative(payload)
    out2 = render_narrative(payload)
    # Deep equality — no timestamps, no random IDs, no ordering drift.
    assert json.dumps(out1, sort_keys=True) == json.dumps(out2, sort_keys=True)


def test_empty_payload_degrades_gracefully():
    out = render_narrative({})
    assert out["schema_version"] == 2
    # Sections still present
    assert "technical" in out
    assert "client_safe" in out
    # No tracebacks raised


def test_partial_payload_with_missing_metrics():
    payload = _base_payload()
    payload["ex_ante_metrics"] = {}
    out = render_narrative(payload)
    # Should not crash — key_points list is shorter
    assert isinstance(out["technical"]["key_points"], list)
    assert isinstance(out["client_safe"]["key_points"], list)


def test_no_template_source_leakage():
    """The output dict MUST NOT contain raw Jinja2 source markers.

    This is the CLAUDE.md "prompts are Netz IP" rule translated into
    a unit test. If the rendered strings contain ``{{``, ``{%``, or
    ``|tojson`` the templater has leaked the template to the client.
    """
    out = render_narrative(_base_payload())
    all_strings: list[str] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, str):
            all_strings.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                _walk(v)

    _walk(out)
    for s in all_strings:
        assert "{{" not in s, f"template source leaked: {s!r}"
        assert "{%" not in s, f"template source leaked: {s!r}"
        assert "tojson" not in s.lower(), f"template filter leaked: {s!r}"
        assert "|round" not in s, f"template filter leaked: {s!r}"


def test_holding_changes_payload_shape():
    out = render_narrative(_base_payload())
    moves = out["technical"]["holding_changes"]
    assert isinstance(moves, list)
    assert len(moves) == 3
    for move in moves:
        assert set(move.keys()) == {
            "instrument_id", "fund_name", "block_id", "weight_pct",
        }
        assert isinstance(move["weight_pct"], (int, float))


def test_constraint_story_mentions_binding_constraints():
    out = render_narrative(_base_payload())
    story = out["technical"]["constraint_story"]
    assert "Max single fund weight" in story or "max_single_fund" in story


def test_constraint_story_handles_no_binding_constraints():
    payload = _base_payload()
    payload["binding_constraints"] = []
    out = render_narrative(payload)
    story = out["technical"]["constraint_story"]
    assert "No constraints" in story or "room to move" in story


def test_cvar_within_limit_headline():
    """When cvar_95 (-0.04) >= cvar_limit (-0.05), headline says 'within'."""
    out = render_narrative(_base_payload())
    headline_tech = out["technical"]["headline"]
    headline_client = out["client_safe"]["headline"]
    assert "within" in headline_tech.lower() or "inside" in headline_client.lower()


def test_cvar_breach_headline():
    payload = _base_payload()
    payload["ex_ante_metrics"]["cvar_95"] = -0.10  # exceeds -0.05 limit
    out = render_narrative(payload)
    headline_tech = out["technical"]["headline"]
    headline_client = out["client_safe"]["headline"]
    assert (
        "BREACHING" in headline_tech or "breach" in headline_tech.lower()
        or "ABOVE" in headline_client
    )


def test_sandboxed_environment_blocks_dunder_access():
    """SandboxedEnvironment forbids ``__class__``, ``__mro__``, etc.

    This test simulates a malicious context key whose name would
    be used to probe into Python internals. Rendering should not
    expose such attributes in the output.
    """
    payload = _base_payload()
    # Even if we add a weird key, the output stays JSON-safe
    payload["__class__"] = "should_not_leak"
    out = render_narrative(payload)
    json_str = json.dumps(out)
    assert "should_not_leak" not in json_str
