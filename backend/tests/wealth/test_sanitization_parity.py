"""Sanitization parity test — backend ↔ frontend i18n drift gate.

Enforces that every metric / regime / scenario key emitted by the
backend (``backend/app/domains/wealth/schemas/sanitized.py``) is
representable on the frontend
(``packages/ii-terminal-core/src/lib/i18n/quant-labels.ts``).

The frontend dictionary is the *single* canonical TypeScript source
(the wealth-side ``frontends/wealth/src/lib/i18n/quant-labels.ts`` is a
re-export shim — see PR-UX-5). Backend keys ⊆ frontend keys means
nothing the backend can emit will reach the UI as untranslated jargon.

The test parses the TypeScript source with simple regexes — there is
no Node runtime in CI for this test. Anything that defeats those
regexes (e.g. computed keys, dynamic ``Object.keys`` of an external
import) will surface as a parity failure, which is the correct
behaviour: the test should fail loudly when the introspection contract
breaks, not silently pass.

Spec: ``docs/plans/2026-04-30-builder-workspace-redesign-final.md`` §8.

PR-UX-5 — sanitization parity (canonize quant-labels + CI gate).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.domains.wealth.schemas.sanitized import (
    EVENT_TYPE_LABELS,
    METRIC_LABELS,
    REGIME_LABELS,
)

# ── §8 canonical fixture ─────────────────────────────────────────────
#
# The plan §8 mappings table. Hardcoded here on purpose — markdown
# parsing is brittle and §8 is a stable institutional contract. If the
# doc table changes, update this fixture in the same PR.
#
# Each entry is the raw key that crosses the wire; both backend and
# frontend MUST be able to translate it.

DOC_SECTION_8_METRIC_KEYS: tuple[str, ...] = (
    # CVaR / Expected Shortfall family
    "cvar_95",
    "expected_shortfall",
    "cvar_95_1m",
    "cvar_95_3m",
    "cvar_95_6m",
    "cvar_95_12m",
    "cvar_95_conditional",
    # Regime
    "regime",
    "market_regime",
    # Volatility models
    "garch_volatility",
    "ewma_volatility",
    "volatility_garch",
    # Macro composite
    "cfnai",
    "macro_score",
    # Drawdown
    "max_drawdown",
    "drawdown",
    "max_drawdown_1y",
    "max_drawdown_3y",
    # Strategy drift
    "dtw_drift_score",
)

DOC_SECTION_8_REGIME_KEYS: tuple[str, ...] = (
    "RISK_ON",
    "RISK_OFF",
    "NEUTRAL",
    "CRISIS",
    "EXPANSION",
    "CAUTIOUS",
    "STRESS",
)

DOC_SECTION_8_SCENARIO_KEYS: tuple[str, ...] = (
    "gfc_2008",
    "covid_2020",
    "taper_2013",
    "rate_shock_200bps",
)

# ── Frontend file location ───────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_QUANT_LABELS = (
    REPO_ROOT
    / "packages"
    / "ii-terminal-core"
    / "src"
    / "lib"
    / "i18n"
    / "quant-labels.ts"
)
WEALTH_QUANT_LABELS_SHIM = (
    REPO_ROOT
    / "frontends"
    / "wealth"
    / "src"
    / "lib"
    / "i18n"
    / "quant-labels.ts"
)


def _read_frontend_source() -> str:
    if not FRONTEND_QUANT_LABELS.exists():
        pytest.fail(
            f"Canonical frontend dictionary missing: {FRONTEND_QUANT_LABELS}"
        )
    return FRONTEND_QUANT_LABELS.read_text(encoding="utf-8")


def _parse_metric_label_keys(source: str) -> set[str]:
    """Extract canonical METRIC_LABELS keys.

    Matches the body of the ``METRIC_LABELS`` const declaration and
    pulls out the bare-identifier or quoted keys on each line.
    """
    block_match = re.search(
        r"const\s+METRIC_LABELS\s*:[^=]*=\s*\{(?P<body>.*?)\};",
        source,
        re.DOTALL,
    )
    if not block_match:
        pytest.fail(
            "Could not locate METRIC_LABELS const in canonical frontend "
            "dictionary — parser regex needs an update or the dictionary "
            "structure has drifted."
        )
    body = block_match.group("body")
    return _extract_keys(body)


def _parse_normalise_aliases(source: str) -> set[str]:
    """Extract every ``case "..."`` literal inside the ``normalise`` switch.

    These are the alternate spellings that ``humanizeMetric`` understands
    via the normalisation step. Backend can emit any of them and the
    frontend will resolve to a known canonical key.
    """
    func_match = re.search(
        r"function\s+normalise\s*\([^)]*\)\s*:[^{]*\{(?P<body>.*?)^\}",
        source,
        re.DOTALL | re.MULTILINE,
    )
    if not func_match:
        pytest.fail(
            "Could not locate normalise() function in canonical frontend "
            "dictionary — parser regex needs an update."
        )
    body = func_match.group("body")
    return set(re.findall(r'case\s+"([^"]+)"\s*:', body))


def _parse_scenario_label_keys(source: str) -> set[str]:
    block_match = re.search(
        r"const\s+SCENARIO_LABELS\s*:[^=]*=\s*\{(?P<body>.*?)\};",
        source,
        re.DOTALL,
    )
    if not block_match:
        pytest.fail("Could not locate SCENARIO_LABELS const.")
    return _extract_keys(block_match.group("body"))


def _parse_regime_label_keys(source: str) -> set[str]:
    """Pull regime tokens out of the ``regimeLabel`` switch."""
    func_match = re.search(
        r"function\s+regimeLabel\s*\([^)]*\)\s*:[^{]*\{(?P<body>.*?)^\}",
        source,
        re.DOTALL | re.MULTILINE,
    )
    if not func_match:
        pytest.fail("Could not locate regimeLabel() function.")
    return set(re.findall(r'case\s+"([^"]+)"\s*:', func_match.group("body")))


def _extract_keys(body: str) -> set[str]:
    """Parse ``key: "value",`` and ``"key": "value",`` pairs from a block.

    Strips line/block comments first so a ``// case "foo"`` reference
    inside a comment isn't picked up as a real key.
    """
    cleaned = re.sub(r"//.*?$", "", body, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    bare = set(re.findall(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", cleaned, re.MULTILINE))
    quoted = set(re.findall(r'^\s*"([^"]+)"\s*:', cleaned, re.MULTILINE))
    return bare | quoted


# ── Tests ────────────────────────────────────────────────────────────


def test_backend_metric_keys_subset_of_frontend() -> None:
    """Every backend METRIC_LABELS key must be representable on the frontend.

    Frontend "representable" means: either a top-level entry in
    ``METRIC_LABELS`` OR an alias case in the ``normalise`` switch.
    """
    source = _read_frontend_source()
    frontend_keys = _parse_metric_label_keys(source)
    frontend_aliases = _parse_normalise_aliases(source)
    representable = frontend_keys | frontend_aliases

    backend_keys = set(METRIC_LABELS.keys())
    missing = backend_keys - representable
    assert not missing, (
        f"Backend METRIC_LABELS keys missing from frontend canonical "
        f"dictionary (drift): {sorted(missing)}. Add them to "
        f"packages/ii-terminal-core/src/lib/i18n/quant-labels.ts — either "
        f"as a METRIC_LABELS entry or as a normalise() case."
    )


def test_backend_regime_keys_subset_of_frontend() -> None:
    source = _read_frontend_source()
    frontend_regime_keys = _parse_regime_label_keys(source)
    backend_regime_keys = set(REGIME_LABELS.keys())
    missing = backend_regime_keys - frontend_regime_keys
    assert not missing, (
        f"Backend REGIME_LABELS keys missing from frontend regimeLabel(): "
        f"{sorted(missing)}."
    )


def test_doc_section_8_metric_keys_have_backend_representation() -> None:
    """Every §8 doc-table key must be representable in the backend dict."""
    backend_keys = set(METRIC_LABELS.keys())
    missing = set(DOC_SECTION_8_METRIC_KEYS) - backend_keys
    assert not missing, (
        f"§8 metric keys missing from backend METRIC_LABELS: "
        f"{sorted(missing)}. Add them to "
        f"backend/app/domains/wealth/schemas/sanitized.py::METRIC_LABELS."
    )


def test_doc_section_8_metric_keys_have_frontend_representation() -> None:
    """Every §8 doc-table key must be representable on the frontend."""
    source = _read_frontend_source()
    representable = _parse_metric_label_keys(source) | _parse_normalise_aliases(
        source
    )
    missing = set(DOC_SECTION_8_METRIC_KEYS) - representable
    assert not missing, (
        f"§8 metric keys missing from frontend canonical dictionary: "
        f"{sorted(missing)}."
    )


def test_doc_section_8_regime_keys_have_backend_representation() -> None:
    backend = set(REGIME_LABELS.keys())
    missing = set(DOC_SECTION_8_REGIME_KEYS) - backend
    assert not missing, (
        f"§8 regime keys missing from backend REGIME_LABELS: "
        f"{sorted(missing)}."
    )


def test_doc_section_8_regime_keys_have_frontend_representation() -> None:
    source = _read_frontend_source()
    representable = _parse_regime_label_keys(source)
    missing = set(DOC_SECTION_8_REGIME_KEYS) - representable
    assert not missing, (
        f"§8 regime keys missing from frontend regimeLabel(): "
        f"{sorted(missing)}."
    )


def test_doc_section_8_scenario_keys_have_frontend_representation() -> None:
    """Stress scenario slugs are frontend-only — backend just emits the
    raw slug. The frontend ``scenarioLabel()`` helper must translate
    every §8 scenario."""
    source = _read_frontend_source()
    representable = _parse_scenario_label_keys(source)
    missing = set(DOC_SECTION_8_SCENARIO_KEYS) - representable
    assert not missing, (
        f"§8 scenario keys missing from frontend SCENARIO_LABELS: "
        f"{sorted(missing)}."
    )


def test_event_type_labels_are_non_empty() -> None:
    """``EVENT_TYPE_LABELS`` is backend-only (no frontend mirror needed —
    the backend already humanises ``type``/``message`` before SSE emit).
    Sanity-check that it isn't empty so the wire stays sanitised."""
    assert len(EVENT_TYPE_LABELS) > 0
    # Spot-check a few high-traffic events.
    for required in ("run_started", "run_failed", "optimizer_started"):
        assert required in EVENT_TYPE_LABELS, (
            f"EVENT_TYPE_LABELS missing required key {required!r}."
        )


def test_wealth_shim_re_exports_terminal_core() -> None:
    """The wealth-side ``quant-labels.ts`` must be a pure re-export of the
    canonical terminal-core module — no duplicate dictionary."""
    if not WEALTH_QUANT_LABELS_SHIM.exists():
        pytest.fail(f"Wealth shim missing: {WEALTH_QUANT_LABELS_SHIM}")
    src = WEALTH_QUANT_LABELS_SHIM.read_text(encoding="utf-8")
    assert (
        '@investintell/ii-terminal-core/i18n/quant-labels' in src
    ), "Wealth shim must re-export from @investintell/ii-terminal-core/i18n/quant-labels."
    # No locally-defined METRIC_LABELS / SCENARIO_LABELS const blocks.
    assert not re.search(
        r"const\s+METRIC_LABELS\s*:[^=]*=\s*\{", src
    ), "Wealth shim must NOT declare its own METRIC_LABELS — drift risk."
    assert not re.search(
        r"const\s+SCENARIO_LABELS\s*:[^=]*=\s*\{", src
    ), "Wealth shim must NOT declare its own SCENARIO_LABELS — drift risk."
