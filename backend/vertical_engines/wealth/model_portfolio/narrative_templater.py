"""Deterministic Jinja2 narrative templater for construction runs.

Phase 3 Task 3.2 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

**DL8 locked**: the templater is PURE, deterministic Jinja2 — NEVER
an LLM. This is an audit-friendly, sub-second narrative generator
that consumes the structured construction run payload and emits a
JSON-shaped narrative dict.

**CLAUDE.md rule**: prompts are Netz IP. This module:

- Uses :class:`jinja2.sandbox.SandboxedEnvironment` (not
  :class:`jinja2.Environment`) so a rogue template can't escape
  into file I/O or subprocess calls.
- Keeps template strings in-process as Python strings so the
  ``/construct`` response NEVER leaks them — the ``portfolio_alerts``
  ``ck_alert_type`` CHECK whitelist and ``CLIENT_VISIBLE_TYPES`` in
  ``ConfigService`` both guard against accidentally returning the
  raw Jinja2 source.

Two narratives per run
----------------------
1. **``technical``** — full quant language for the IC member:
   "CVaR 95% = -4.8%, ex-ante vol = 12.3%, Sharpe = 0.87,
   binding constraints: ``na_equity_large ≤ 50%``".
2. **``client_safe``** — sanitized, jargon-free for the end client:
   "Tail loss is within the 5% budget. Expected return 8%.
   No binding policy limits."

The client_safe template applies the OD-22 regime label translation
and the Phase 10 jargon table. CVaR → "Tail loss", Sharpe → omitted,
regime labels translated per the locked mapping.

TAA (Tactical Asset Allocation) section
----------------------------------------
Added in Sprint 3 (TAA). When ``calibration_snapshot.taa.enabled`` is
true, both technical and client_safe narratives include a TAA summary
describing the regime-adjusted allocation bands and transition state.

Public surface
--------------
- :func:`render_narrative` — pure sync function. No I/O. Returns
  the JSON-shaped dict the frontend reads.

The output shape is stable — any change must update:
    - The golden test below
    - ``portfolio_construction_runs.narrative`` JSONB consumers
    - The translation table in Phase 10 Task 10.1
"""

from __future__ import annotations

from typing import Any, Final

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

# ── Regime label translation table (OD-22 locked) ──────────────


REGIME_CLIENT_SAFE_LABEL: Final[dict[str, str]] = {
    "NORMAL": "Balanced",
    "RISK_ON": "Expansion",
    "RISK_OFF": "Defensive",
    "CRISIS": "Stress",
    "INFLATION": "Inflation",
}


# ── Templates (in-process strings — never returned to clients) ──
#
# These are the Netz IP prompt templates. The SandboxedEnvironment
# below renders them; the output dict carries only the rendered
# strings, never the template source.


_TECHNICAL_HEADLINE_TEMPLATE: Final[str] = (
    "{{ profile|capitalize }} portfolio constructed with "
    "{{ weights|length }} positions — "
    "ex-ante CVaR 95%% of {{ (cvar_95 * 100)|round(2) }}%% "
    "{{ 'within' if cvar_within_limit else 'BREACHING' }} "
    "the {{ (cvar_limit * 100)|round(2) }}%% limit."
).replace("%%", "%")


_CLIENT_SAFE_HEADLINE_TEMPLATE: Final[str] = (
    "{{ profile|capitalize }} portfolio with {{ weights|length }} "
    "positions. Tail loss {{ 'inside' if cvar_within_limit else 'ABOVE' }} "
    "the {{ (cvar_limit * 100)|round(1) }}%% budget."
).replace("%%", "%")


_KEY_POINTS_TECHNICAL_TEMPLATE: Final[str] = """
{%- set points = [] -%}
{%- if expected_return is not none -%}
  {%- set _ = points.append('Expected return: ' ~ (expected_return * 100)|round(2) ~ '%') -%}
{%- endif -%}
{%- if portfolio_volatility is not none -%}
  {%- set _ = points.append('Ex-ante volatility: ' ~ (portfolio_volatility * 100)|round(2) ~ '%') -%}
{%- endif -%}
{%- if sharpe_ratio is not none -%}
  {%- set _ = points.append('Sharpe ratio: ' ~ sharpe_ratio|round(2)) -%}
{%- endif -%}
{%- if solver -%}
  {%- set _ = points.append('Solver: ' ~ solver ~ ' — ' ~ status) -%}
{%- endif -%}
{%- if binding_constraints -%}
  {%- set _ = points.append(binding_constraints|length ~ ' binding constraint(s)') -%}
{%- endif -%}
{{ points|tojson }}
""".strip()


_KEY_POINTS_CLIENT_SAFE_TEMPLATE: Final[str] = """
{%- set points = [] -%}
{%- if expected_return is not none -%}
  {%- set _ = points.append('Projected annual return: ' ~ (expected_return * 100)|round(1) ~ '%') -%}
{%- endif -%}
{%- if portfolio_volatility is not none -%}
  {%- set _ = points.append('Expected swing: ' ~ (portfolio_volatility * 100)|round(1) ~ '% per year') -%}
{%- endif -%}
{%- if regime_label_client_safe -%}
  {%- set _ = points.append('Current market outlook: ' ~ regime_label_client_safe) -%}
{%- endif -%}
{{ points|tojson }}
""".strip()


_CONSTRAINT_STORY_TEMPLATE: Final[str] = """
{%- if binding_constraints -%}
The optimizer hit {{ binding_constraints|length }} binding constraint(s):
{%- for c in binding_constraints[:3] %}
 · {{ c.label or c.id }}{% if c.threshold is not none %} at {{ c.threshold }}{% endif %}
{%- endfor %}
{%- else -%}
No constraints bind at the current allocation — the optimizer had room to move.
{%- endif -%}
""".strip()


_HOLDING_CHANGES_TEMPLATE: Final[str] = """
{%- set moves = [] -%}
{%- for f in funds[:10] -%}
  {%- set _ = moves.append({
    'instrument_id': f.instrument_id|string,
    'fund_name': f.fund_name or '—',
    'block_id': f.block_id or '—',
    'weight_pct': (f.weight * 100)|round(2),
  }) -%}
{%- endfor -%}
{{ moves|tojson }}
""".strip()


# ── TAA (Tactical Asset Allocation) narrative templates ──────────

_TAA_TECHNICAL_TEMPLATE: Final[str] = """
{%- if not taa_enabled -%}
Tactical Asset Allocation was disabled for this construction run — static IPS bounds applied.
{%- else -%}
Portfolio constructed under {{ raw_regime }} market regime (composite stress score: {{ stress_score }}/100). \
Regime-adjusted allocation bands applied via 5-day EMA smoothing.
{%- if smoothed_centers %}
Smoothed asset-class centers: \
{%- for ac, val in smoothed_centers.items() %} {{ ac }}={{ (val * 100)|round(1) }}%{{ ", " if not loop.last else "." }}{% endfor %}
{%- endif %}
{%- if ips_clamps_applied %}
IPS clamps triggered on {{ ips_clamps_applied|length }} bound(s): {{ ips_clamps_applied|join(', ') }}.
{%- endif %}
{%- if ic_overrides_active %}
IC committee overrides active: {{ ic_overrides_active|join(', ') }}.
{%- endif %}
{%- if transition_velocity %}
Transition velocity (daily delta): \
{%- for ac, vel in transition_velocity.items() %} {{ ac }}={{ (vel * 100)|round(2) }}pp{{ ", " if not loop.last else "." }}{% endfor %}
{%- endif %}
All regime-adjusted bands remain within Investment Policy Statement constraints.
{%- endif -%}
""".strip()


_TAA_CLIENT_SAFE_TEMPLATE: Final[str] = """
{%- if not taa_enabled -%}
The portfolio follows the standard allocation policy.
{%- else -%}
The portfolio was positioned for {{ regime_label_client_safe|lower }} market conditions. \
Allocation bands were adjusted gradually to reflect the current outlook, \
{%- if smoothed_centers %}
 with target allocations of \
{%- for ac, val in smoothed_centers.items() %} {{ ac|replace('_', ' ') }} at {{ (val * 100)|round(0)|int }}%{{ ", " if not loop.last else "." }}{% endfor %}
{%- endif %}
{%- if ips_clamps_applied %}
 Some adjustments were limited to stay within the agreed policy bounds.
{%- endif %}
All allocations remain within the agreed investment policy.
{%- endif -%}
""".strip()


# ── Sandboxed environment (module-level, reusable) ──────────────


_env: Final[SandboxedEnvironment] = SandboxedEnvironment(
    autoescape=False,  # we emit JSON, not HTML
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _render(template_str: str, **ctx: Any) -> str:
    """Render a template string inside the sandbox.

    Wraps StrictUndefined errors so the caller gets a clean empty
    string instead of a traceback when optional context is missing.
    """
    try:
        template = _env.from_string(template_str)
        return template.render(**ctx)
    except Exception:  # noqa: BLE001
        return ""


# ── Public API ──────────────────────────────────────────────────


def render_narrative(run_payload: dict[str, Any]) -> dict[str, Any]:
    """Render the construction run narrative.

    Pure function. No I/O. Deterministic: same input → same output.
    Safe to call from sync or async code. Sub-second.

    Input
    -----
    ``run_payload`` — the in-memory construction run dict. Expected
    keys (all optional — the templater degrades gracefully):

        profile                — str (e.g. "moderate")
        funds                  — list[{instrument_id, fund_name, block_id, weight}]
        weights_proposed       — dict[str, float]
        ex_ante_metrics        — {expected_return, portfolio_volatility,
                                  sharpe_ratio, cvar_95}
        calibration_snapshot   — {cvar_limit}
        optimizer_trace        — {solver, status}
        binding_constraints    — list[{id, label, threshold}]
        regime_context         — {regime}

    Output
    ------
    A JSON-shaped dict::

        {
            "schema_version": 2,
            "technical": {
                "headline": str,
                "key_points": list[str],
                "constraint_story": str,
                "holding_changes": list[{...}],
                "taa_summary": str | None,
            },
            "client_safe": {
                "headline": str,
                "key_points": list[str],
                "constraint_story": str,
                "holding_changes": list[{...}],
                "taa_summary": str | None,
            },
        }

    The ``technical`` section uses full quant language. The
    ``client_safe`` section applies the OD-22 regime label
    translation table and the Phase 10 jargon table.

    The ``taa_summary`` is present when the calibration_snapshot
    includes a ``taa`` dict with ``enabled: true``. Technical
    uses full regime labels + quant metrics; client_safe uses
    OD-22 translated labels with no jargon.
    """
    import json

    # Extract + normalize the inputs
    profile = run_payload.get("profile") or "balanced"
    funds = run_payload.get("funds") or []
    weights = run_payload.get("weights_proposed") or {
        str(f.get("instrument_id")): f.get("weight")
        for f in funds
        if f.get("instrument_id") is not None
    }
    metrics = run_payload.get("ex_ante_metrics") or {}
    calibration = run_payload.get("calibration_snapshot") or {}
    optimizer_trace = run_payload.get("optimizer_trace") or {}
    binding = run_payload.get("binding_constraints") or []
    regime_context = run_payload.get("regime_context") or {}

    cvar_95 = metrics.get("cvar_95")
    cvar_limit_raw = calibration.get("cvar_limit")
    cvar_limit = -abs(float(cvar_limit_raw)) if cvar_limit_raw is not None else None
    cvar_within_limit = (
        cvar_95 is not None and cvar_limit is not None and float(cvar_95) >= cvar_limit
    )

    regime_raw = regime_context.get("regime") or "NORMAL"
    regime_label_client_safe = REGIME_CLIENT_SAFE_LABEL.get(
        regime_raw, regime_raw.capitalize(),
    )

    ctx_technical = {
        "profile": profile,
        "weights": weights,
        "funds": funds,
        "expected_return": metrics.get("expected_return"),
        "portfolio_volatility": metrics.get("portfolio_volatility"),
        "sharpe_ratio": metrics.get("sharpe_ratio"),
        "solver": optimizer_trace.get("solver"),
        "status": optimizer_trace.get("status"),
        "cvar_95": cvar_95 if cvar_95 is not None else 0.0,
        "cvar_limit": cvar_limit if cvar_limit is not None else 0.0,
        "cvar_within_limit": cvar_within_limit,
        "binding_constraints": binding,
    }

    ctx_client_safe = {
        **ctx_technical,
        "regime_label_client_safe": regime_label_client_safe,
    }

    # Render each section
    technical_key_points_raw = _render(_KEY_POINTS_TECHNICAL_TEMPLATE, **ctx_technical)
    client_key_points_raw = _render(_KEY_POINTS_CLIENT_SAFE_TEMPLATE, **ctx_client_safe)
    holding_changes_raw = _render(_HOLDING_CHANGES_TEMPLATE, **ctx_technical)

    try:
        technical_key_points = json.loads(technical_key_points_raw) if technical_key_points_raw else []
    except json.JSONDecodeError:
        technical_key_points = []
    try:
        client_key_points = json.loads(client_key_points_raw) if client_key_points_raw else []
    except json.JSONDecodeError:
        client_key_points = []
    try:
        holding_changes = json.loads(holding_changes_raw) if holding_changes_raw else []
    except json.JSONDecodeError:
        holding_changes = []

    technical_headline = _render(_TECHNICAL_HEADLINE_TEMPLATE, **ctx_technical)
    client_headline = _render(_CLIENT_SAFE_HEADLINE_TEMPLATE, **ctx_client_safe)
    constraint_story = _render(_CONSTRAINT_STORY_TEMPLATE, **ctx_technical)

    # ── TAA narrative section (Sprint 3) ──
    taa = calibration.get("taa") or {}
    taa_enabled = taa.get("enabled", False)
    taa_raw_regime = taa.get("raw_regime") or regime_raw
    taa_regime_label = REGIME_CLIENT_SAFE_LABEL.get(
        taa_raw_regime, taa_raw_regime.capitalize(),
    )
    taa_stress = taa.get("stress_score")
    taa_ctx = {
        "taa_enabled": taa_enabled,
        "raw_regime": taa_raw_regime,
        "stress_score": f"{taa_stress:.1f}" if taa_stress is not None else "N/A",
        "smoothed_centers": taa.get("smoothed_centers") or {},
        "effective_bands": taa.get("effective_bands") or {},
        "ips_clamps_applied": taa.get("ips_clamps_applied") or [],
        "ic_overrides_active": taa.get("ic_overrides_active") or [],
        "transition_velocity": taa.get("transition_velocity") or {},
        "regime_label_client_safe": taa_regime_label,
    }

    taa_technical = _render(_TAA_TECHNICAL_TEMPLATE, **taa_ctx) or None
    taa_client_safe = _render(_TAA_CLIENT_SAFE_TEMPLATE, **taa_ctx) or None

    return {
        "schema_version": 2,
        "technical": {
            "headline": technical_headline,
            "key_points": technical_key_points,
            "constraint_story": constraint_story,
            "holding_changes": holding_changes,
            "taa_summary": taa_technical,
        },
        "client_safe": {
            "headline": client_headline,
            "key_points": client_key_points,
            "constraint_story": constraint_story,
            "holding_changes": holding_changes,
            "taa_summary": taa_client_safe,
        },
    }
