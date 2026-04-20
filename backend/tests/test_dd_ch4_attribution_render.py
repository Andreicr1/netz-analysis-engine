"""DD ch.4 attribution copy is sanitised and rail-aware.

Verifies the smart-backend / dumb-frontend rule: no raw quant jargon
(cornish-fisher, meucci, brinson-fachler, ipca, cvar, r_squared, sharpe
regression) leaks into the chapter's user content.
"""

from __future__ import annotations

from vertical_engines.wealth.dd_report.chapters import _build_user_content

_BLOCKLIST = (
    "cornish-fisher",
    "meucci",
    "brinson-fachler",
    "ipca",
    "cvar",
    "opdyke",
    "sharpe regression",
    "r_squared",
    "r-squared",
    "tracking error",
)


def _sample_context(attribution) -> dict:
    return {
        "fund_name": "Acme Global Growth",
        "isin": "US1234567890",
        "quant_profile": {"sharpe_1y": 1.2, "return_1y": 0.08},
        "attribution": attribution,
    }


def test_rail_returns_renders_sanitised_exposure_table() -> None:
    attribution = {
        "badge": "RAIL_RETURNS",
        "reason": None,
        "returns_based": {
            "n_months": 60,
            "exposures": [
                {"ticker": "SPY", "weight": 0.60},
                {"ticker": "AGG", "weight": 0.30},
                {"ticker": "LQD", "weight": 0.10},
            ],
        },
    }
    body = _build_user_content("performance_analysis", _sample_context(attribution))
    assert "LOW-MEDIUM CONFIDENCE" in body
    assert "SPY: 60.0%" in body
    assert "AGG: 30.0%" in body
    assert "60 months" in body
    lower = body.lower()
    for term in _BLOCKLIST:
        assert term not in lower, f"leaked raw term: {term}"


def test_rail_none_renders_insufficient_copy() -> None:
    attribution = {"badge": "RAIL_NONE", "reason": "insufficient_history"}
    body = _build_user_content("performance_analysis", _sample_context(attribution))
    assert "INSUFFICIENT DATA" in body
    lower = body.lower()
    for term in _BLOCKLIST:
        assert term not in lower


def test_missing_attribution_renders_no_block() -> None:
    body = _build_user_content("performance_analysis", {"fund_name": "A"})
    assert "## Attribution" not in body


def test_other_chapters_ignore_attribution() -> None:
    attribution = {
        "badge": "RAIL_RETURNS",
        "returns_based": {
            "n_months": 60,
            "exposures": [{"ticker": "SPY", "weight": 1.0}],
        },
    }
    body = _build_user_content("risk_framework", _sample_context(attribution))
    assert "Style Exposures" not in body
    assert "RAIL_RETURNS" not in body
