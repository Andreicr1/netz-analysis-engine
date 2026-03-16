"""Policy Loader — extracts concentration thresholds and governance rules
from Azure AI Search indices (risk-policy-internal, fund-constitution-governance).

Design principles:
  - No hardcoded thresholds. All limits come from indexed fund documents.
  - LLM extraction via AzureOpenAI for structured parsing of policy text.
  - Explicit fallback chain: Search → LLM extraction → auditable defaults.
  - Every threshold carries a `source` trace (document + chunk) for audit.
  - Cached per process startup; call `invalidate_cache()` to force reload.

Consumed by: concentration_engine.py
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ai_engine.model_config import get_model as _get_model
from ai_engine.openai_client import create_completion

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
#  Configuration (from environment — search credentials only)
# ─────────────────────────────────────────────────────────────────────
SEARCH_ENDPOINT   = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
SEARCH_API_KEY    = os.environ.get("AZURE_SEARCH_API_KEY", "")
SEARCH_API_VER    = "2024-07-01"

RISK_POLICY_INDEX       = "risk-policy-index"
FUND_CONSTITUTION_INDEX = "fund-constitution-index"

# ─────────────────────────────────────────────────────────────────────
#  Auditable defaults — reflect actual Investment Policy hard limits
#  (Investment Policy s.4 + Credit Policy s.7).
#  Used ONLY when document search/extraction fails for a given field.
#  Every default carries a rationale string referencing the policy section.
# ─────────────────────────────────────────────────────────────────────
_DEFAULTS: dict[str, dict] = {
    # Hard limits — Investment Policy s.4
    "single_manager_pct": {
        "value": 35.0,
        "rationale": "Hard limit: max 35% to same investment manager (Investment Policy s.4)",
        "source": "DEFAULT",
    },
    "single_investment_pct": {
        "value": 35.0,
        "rationale": "Hard limit: max 35% to a single investment (Investment Policy s.4)",
        "source": "DEFAULT",
    },
    "non_usd_unhedged_pct": {
        "value": 20.0,
        "rationale": "Hard limit: max 20% in non-USD unhedged investments (Investment Policy s.4)",
        "source": "DEFAULT",
    },
    "min_commingled_pct": {
        "value": 35.0,
        "rationale": "Hard limit: at least 35% in funds/commingled vehicles (Investment Policy s.4)",
        "source": "DEFAULT",
    },
    "max_hard_lockup_pct": {
        "value": 10.0,
        "rationale": "Hard limit: max 10% in hard lock-ups >2 years (Investment Policy s.4)",
        "source": "DEFAULT",
    },
    "max_lockup_years": {
        "value": 2.0,
        "rationale": "Hard limit: investor lock-up must not exceed 2 years (Investment Policy s.4)",
        "source": "DEFAULT",
    },
    "min_quarterly_liquidity_pct": {
        "value": 20.0,
        "rationale": "Hard limit: at least 20% in assets with quarterly liquidity (Investment Policy s.4)",
        "source": "DEFAULT",
    },
    # Concentration limits — sector/geo not explicitly stated in Investment Policy
    # Using single_manager hard limit as reference for sector
    "single_sector_pct": {
        "value": 35.0,
        "rationale": "Aligned to single-manager hard limit; sector limit not explicitly stated in Investment Policy",
        "source": "DEFAULT",
    },
    "single_geography_pct": {
        "value": 40.0,
        "rationale": "Policy requires majority USD/US exposure; explicit geography limit not stated",
        "source": "DEFAULT",
    },
    "top3_names_pct": {
        "value": 75.0,
        "rationale": "Derived: 3 x 35% single-investment hard limit; not explicitly stated in policy",
        "source": "DEFAULT",
    },
    # Governance — Investment Policy s.2, s.9 + Credit Policy s.7
    "board_override_triggers": {
        "value": ["single_manager", "single_investment", "hard_lockup", "non_usd_unhedged"],
        "rationale": "Board retains authority over hard limit breaches (Investment Policy s.9)",
        "source": "DEFAULT",
    },
    "watchlist_triggers": {
        "value": [
            "covenant_breach",
            "payment_delay",
            "cashflow_deterioration",
            "valuation_markdown",
            "legal_regulatory_event",
            "structural_change_underlying",
        ],
        "rationale": "Watchlist triggers per Credit Policy s.7 and Investment Policy s.8",
        "source": "DEFAULT",
    },
    "ic_approval_required_above_pct": {
        "value": 35.0,
        "rationale": "Hard limit: single investment cannot exceed 35% without IC approval (Investment Policy s.4)",
        "source": "DEFAULT",
    },
    "review_frequency_days": {
        "value": 90,
        "rationale": "Quarterly review required (Investment Policy s.8)",
        "source": "DEFAULT",
    },
    # Soft limits — Investment Policy s.5
    "max_leverage_underlying_pct": {
        "value": 300.0,
        "rationale": "Soft limit: underlying leverage should not exceed 300% (Investment Policy s.5)",
        "source": "DEFAULT",
    },
    "min_manager_track_record_years": {
        "value": 2.0,
        "rationale": "Soft guideline: minimum 2-year track record (Investment Policy s.5)",
        "source": "DEFAULT",
    },
    "min_manager_aum_usd": {
        "value": 100_000_000.0,
        "rationale": "Soft guideline: minimum USD 100M AUM (Investment Policy s.5)",
        "source": "DEFAULT",
    },
    "max_manager_default_rate_pct": {
        "value": 10.0,
        "rationale": "Soft guideline: avoid managers with >10% defaulted AUM (Investment Policy s.5)",
        "source": "DEFAULT",
    },
}


# ─────────────────────────────────────────────────────────────────────
#  Data model
# ─────────────────────────────────────────────────────────────────────
class ThresholdEntry(BaseModel):
    """A single policy threshold with full audit trail."""
    value: float | list[str]   # numeric limit or list of trigger names
    source: str = "DEFAULT"
    document: str = ""
    chunk_id: str = ""
    rationale: str = ""
    extracted_by: str = "DEFAULT"


# Known field names — derived from _DEFAULTS (single source of truth)
_KNOWN_THRESHOLD_FIELDS: list[str] = list(_DEFAULTS.keys())


class PolicyThresholds(BaseModel):
    """Full set of thresholds and governance rules for the concentration engine."""
    model_config = ConfigDict(extra="ignore")

    # Concentration limits (% of total portfolio exposure) — hard limits
    single_manager_pct:    ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["single_manager_pct"]))
    single_investment_pct: ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["single_investment_pct"]))
    single_sector_pct:     ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["single_sector_pct"]))
    single_geography_pct:  ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["single_geography_pct"]))
    top3_names_pct:        ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["top3_names_pct"]))

    # Allocation constraints — hard limits
    non_usd_unhedged_pct:       ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["non_usd_unhedged_pct"]))
    min_commingled_pct:         ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["min_commingled_pct"]))
    max_hard_lockup_pct:        ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["max_hard_lockup_pct"]))
    max_lockup_years:            ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["max_lockup_years"]))
    min_quarterly_liquidity_pct: ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["min_quarterly_liquidity_pct"]))

    # Soft limits
    max_leverage_underlying_pct:   ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["max_leverage_underlying_pct"]))
    min_manager_track_record_years: ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["min_manager_track_record_years"]))
    min_manager_aum_usd:            ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["min_manager_aum_usd"]))
    max_manager_default_rate_pct:   ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["max_manager_default_rate_pct"]))

    # Governance rules
    board_override_triggers:       ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["board_override_triggers"]))
    watchlist_triggers:            ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["watchlist_triggers"]))
    ic_approval_required_above_pct: ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["ic_approval_required_above_pct"]))
    review_frequency_days:         ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["review_frequency_days"]))

    # Metadata
    raw_policy: dict[str, Any] = Field(default_factory=dict)
    loaded_at: float = Field(default_factory=time.time)
    load_errors: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()

    def summary(self) -> dict:
        """Compact summary for logging and memo injection."""
        fields = [
            "single_manager_pct", "single_investment_pct",
            "single_sector_pct", "single_geography_pct", "top3_names_pct",
            "non_usd_unhedged_pct", "max_hard_lockup_pct", "max_lockup_years",
            "min_quarterly_liquidity_pct", "board_override_triggers",
            "review_frequency_days",
        ]
        result: dict = {}
        for f in fields:
            if hasattr(self, f):
                entry = getattr(self, f)
                result[f] = {"limit": entry.value, "source": entry.source}
        return result

    def hard_limits_dict(self) -> dict[str, float]:
        """Flat {field: value} for breach checking in concentration engine."""
        return {
            "single_manager_pct":    self.single_manager_pct.value,
            "single_investment_pct": self.single_investment_pct.value,
            "single_sector_pct":     self.single_sector_pct.value,
            "single_geography_pct":  self.single_geography_pct.value,
            "top3_names_pct":        self.top3_names_pct.value,
            "non_usd_unhedged_pct":  self.non_usd_unhedged_pct.value,
            "max_hard_lockup_pct":   self.max_hard_lockup_pct.value,
            "max_lockup_years":      self.max_lockup_years.value,
        }


# ─────────────────────────────────────────────────────────────────────
#  ConfigService resolver
# ─────────────────────────────────────────────────────────────────────
def resolve_governance_policy(config: dict[str, Any] | None = None) -> PolicyThresholds:
    """Build PolicyThresholds from ConfigService JSONB or _DEFAULTS."""
    if config is None:
        return PolicyThresholds()

    overrides: dict[str, Any] = {"raw_policy": config}

    for field_name, default in _DEFAULTS.items():
        val = config.get(field_name)
        if val is None:
            continue
        try:
            if isinstance(val, bool):
                raise TypeError(f"boolean not accepted for {field_name}")
            if isinstance(val, list):
                coerced = [x for x in val if isinstance(x, str)]
                if len(coerced) != len(val):
                    logger.warning("POLICY_RESOLVE_LIST_FILTERED",
                                   extra={"field": field_name, "original_len": len(val),
                                          "filtered_len": len(coerced)})
            else:
                coerced = float(val)
            overrides[field_name] = ThresholdEntry(
                value=coerced,
                source="ConfigService",
                rationale=default["rationale"],
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.error("POLICY_RESOLVE_BAD_VALUE",
                         extra={"field": field_name, "value": val, "error": str(e)})

    return PolicyThresholds(**overrides)


# ─────────────────────────────────────────────────────────────────────
#  Module-level cache
# ─────────────────────────────────────────────────────────────────────
_cache: PolicyThresholds | None = None
_CACHE_TTL_SECONDS = 3600

def invalidate_cache() -> None:
    global _cache
    _cache = None


# ─────────────────────────────────────────────────────────────────────
#  Azure Search helpers
# ─────────────────────────────────────────────────────────────────────
def _search(
    index: str, query: str, top: int = 5,
    odata_filter: str | None = None,
    organization_id: str | None = None,
) -> list[dict]:
    if not SEARCH_ENDPOINT or not SEARCH_API_KEY:
        logger.warning("POLICY_LOADER_NO_SEARCH_CONFIG")
        return []

    semantic_cfg = index.replace("-index", "-semantic")
    url = f"{SEARCH_ENDPOINT}/indexes/{index}/docs/search?api-version={SEARCH_API_VER}"

    # Build filter with tenant isolation (Security F2)
    filter_parts: list[str] = []
    if organization_id is not None:
        from ai_engine.extraction.search_upsert_service import validate_uuid
        safe_org = validate_uuid(organization_id, "organization_id")
        filter_parts.append(f"organization_id eq '{safe_org}'")
    if odata_filter:
        filter_parts.append(odata_filter)
    combined_filter = " and ".join(filter_parts) if filter_parts else None

    body: dict = {
        "search": query,
        "queryType": "semantic",
        "semanticConfiguration": semantic_cfg,
        "top": top,
        "select": "id,title,content,doc_type",
    }
    if combined_filter:
        body["filter"] = combined_filter
    try:
        resp = httpx.post(
            url,
            headers={"Content-Type": "application/json", "api-key": SEARCH_API_KEY},
            json=body,
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json().get("value", [])
    except Exception as e:
        logger.warning("POLICY_LOADER_SEARCH_ERROR", extra={"index": index, "error": str(e)})
        return []


def _dedup_chunks(chunks: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for c in chunks:
        cid = c.get("id", "")
        if cid not in seen:
            seen.add(cid)
            out.append(c)
    return out


def _build_context(chunks: list[dict]) -> str:
    return "\n\n---\n\n".join(
        f"[SOURCE: {c.get('title', 'unknown')}]\n{c.get('content', '')}"
        for c in chunks
    )


def _first_source(chunks: list[dict]) -> tuple[str, str]:
    if not chunks:
        return "", ""
    return chunks[0].get("title", ""), chunks[0].get("id", "")


# ─────────────────────────────────────────────────────────────────────
#  LLM extraction
# ─────────────────────────────────────────────────────────────────────

def _extract_with_llm(context: str) -> dict:
    from ai_engine.prompts import prompt_registry
    try:
        user_prompt = prompt_registry.render(
            "services/policy_extraction.j2",
            context=context,
        )
        result = create_completion(
            system_prompt="Extract concentration thresholds from policy documents. Return valid JSON only.",
            user_prompt=user_prompt,
            model=_get_model("policy"),
            max_tokens=600,
            temperature=0,
            response_format={"type": "json_object"},
        )
        return json.loads(result.text.strip()) if result.text else {}
    except Exception as e:
        logger.warning("POLICY_LOADER_LLM_ERROR", extra={"error": str(e)})
        return {}


def _apply_extracted(
    thresholds: PolicyThresholds,
    extracted: dict,
    source_index: str,
    chunks: list[dict],
) -> None:
    doc, chunk_id = _first_source(chunks)

    scalar_fields = [
        "single_manager_pct", "single_investment_pct", "single_sector_pct",
        "single_geography_pct", "top3_names_pct", "non_usd_unhedged_pct",
        "min_commingled_pct", "max_hard_lockup_pct", "max_lockup_years",
        "min_quarterly_liquidity_pct",
        "max_leverage_underlying_pct", "min_manager_track_record_years",
        "min_manager_aum_usd", "max_manager_default_rate_pct",
        "ic_approval_required_above_pct", "review_frequency_days",
    ]
    list_fields = ["board_override_triggers", "watchlist_triggers"]

    for attr in scalar_fields:
        # Only overwrite if still at DEFAULT (constitution > risk-policy)
        current = getattr(thresholds, attr, None)
        if current and current.source != "DEFAULT":
            continue
        val = extracted.get(attr)
        if val is not None:
            try:
                setattr(thresholds, attr, ThresholdEntry(
                    value=float(val),
                    source=source_index,
                    document=doc,
                    chunk_id=chunk_id,
                    rationale=f"Extracted from {doc}",
                    extracted_by="llm",
                ))
                logger.info("POLICY_LOADER_SET", extra={"field": attr, "value": val, "source": source_index})
            except (TypeError, ValueError):
                pass

    for attr in list_fields:
        current = getattr(thresholds, attr, None)
        if current and current.source != "DEFAULT":
            continue
        val = extracted.get(attr)
        if val and isinstance(val, list):
            setattr(thresholds, attr, ThresholdEntry(
                value=val,
                source=source_index,
                document=doc,
                chunk_id=chunk_id,
                rationale=f"Extracted from {doc}",
                extracted_by="llm",
            ))


# ─────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────
def load_policy_thresholds(
    *,
    force_reload: bool = False,
    config: dict[str, Any] | None = None,
) -> PolicyThresholds:
    """Load policy thresholds from Azure Search indices.

    Lookup order per threshold:
      1. fund-constitution-index — IMA, M&A (legally binding)
      2. risk-policy-index        (Investment Policy, Credit Policy)
      3. Auditable defaults       (only if documents don't specify the value)

    If ``config`` is provided, uses ConfigService resolver directly
    (no caching — resolve is a pure function, ~100µs).

    Cached for CACHE_TTL_SECONDS. Use force_reload=True to bypass cache.
    """
    global _cache

    # ConfigService path: pure computation, no cache needed
    if config is not None:
        return resolve_governance_policy(config)

    if not force_reload and _cache is not None:
        if time.time() - _cache.loaded_at < _CACHE_TTL_SECONDS:
            return _cache

    thresholds = PolicyThresholds()
    logger.info("POLICY_LOADER_START")

    # ── 1. fund-constitution-index — IMA / M&A (legally binding) ────────────────
    constitution_queries = [
        "concentration limit single manager sector geography percentage hard limit",
        "investment restriction maximum allocation board override approval required",
        "lock-up illiquidity quarterly liquidity minimum allocation commingled",
        "non-USD hedging foreign currency limit",
    ]
    c_chunks = _dedup_chunks([
        c for q in constitution_queries
        for c in _search(FUND_CONSTITUTION_INDEX, q, top=4)
    ])[:10]

    if c_chunks:
        extracted = _extract_with_llm(_build_context(c_chunks))
        if extracted:
            _apply_extracted(thresholds, extracted, FUND_CONSTITUTION_INDEX, c_chunks)
        else:
            thresholds.load_errors.append("LLM extraction empty for fund-constitution-index")
    else:
        thresholds.load_errors.append("No chunks from fund-constitution-index")

    # ── 2. risk-policy-index — fill gaps ─────────────────────────
    missing = [
        f for f in _DEFAULTS
        if hasattr(thresholds, f) and getattr(thresholds, f).source == "DEFAULT"
    ]

    if missing:
        risk_queries = [
            "concentration limit percentage manager sector geography single name hard limit",
            "board override escalation approval conditions",
            "watchlist trigger covenant breach payment delay monitoring",
            "investment size threshold approval lock-up liquidity",
            "leverage underlying manager track record AUM default rate",
        ]
        r_chunks = _dedup_chunks([
            c for q in risk_queries
            for c in _search(RISK_POLICY_INDEX, q, top=4)
        ])[:10]

        if r_chunks:
            extracted2 = _extract_with_llm(_build_context(r_chunks))
            if extracted2:
                _apply_extracted(thresholds, extracted2, RISK_POLICY_INDEX, r_chunks)
            else:
                thresholds.load_errors.append("LLM extraction empty for risk-policy-index")
        else:
            thresholds.load_errors.append("No chunks from risk-policy-index")

    # ── Log result ────────────────────────────────────────────────
    defaults_remaining = [
        f for f in _DEFAULTS
        if hasattr(thresholds, f) and getattr(thresholds, f).source == "DEFAULT"
    ]
    logger.info(
        "POLICY_LOADER_COMPLETE",
        extra={
            "summary": thresholds.summary(),
            "errors": thresholds.load_errors,
            "defaults_remaining": defaults_remaining,
        },
    )

    _cache = thresholds
    return thresholds
