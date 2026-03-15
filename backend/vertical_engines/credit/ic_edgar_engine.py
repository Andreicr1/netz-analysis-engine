"""SEC EDGAR Engine — deterministic public filing retrieval for Deep Review v4.

CIK resolution strategy (offline-first):
  1. Load edgar_index.json.gz from blob storage (built by build_edgar_index.py).
     The index is cached at module level — one blob fetch per process lifetime.
  2. Lookup by normalized name (two-level: light → heavy fallback).
  3. If not found in index (e.g. entity name differs from EDGAR records):
     fall back to EDGAR full-text search via efts.sec.gov.

Once CIK is resolved, all EDGAR API calls go to data.sec.gov:
  Submissions: https://data.sec.gov/submissions/CIK{cik10}.json
  XBRL facts:  https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json

API reference: https://www.sec.gov/search-filings/edgar-application-programming-interfaces

Design invariants:
  • No authentication required — data.sec.gov is fully public.
  • fetch_edgar_data() never raises — all errors captured in result["warnings"].
  • Rate-limit compliant — EDGAR policy: ≤10 req/s → 0.12s delay per request.
  • User-Agent mandatory — SEC policy requires app identification.
  • Blob access via project pattern: blob_uri() + download_bytes() only.
    Never imports Azure SDK directly.

XBRL deduplication:
  Raw EDGAR XBRL returns duplicates (same value in multiple filings due to
  restated periods, comparative tables, multi-quarter summaries).
  Fix: filter observations that contain the "frame" key — EDGAR's canonical
  deduplicated marker for a given calendar period (e.g. "CY2023Q4I").
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import threading
import time
from collections import defaultdict
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
#  Configuration
# ──────────────────────────────────────────────────────────────────────

# MANDATORY: SEC policy requires identifying your application.
_USER_AGENT = "Netz Analysis Engine tech@netzco.com"

_HEADERS_DATA = {                      # data.sec.gov requires explicit Host
    "User-Agent": _USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov",
}
_HEADERS_SEC = {                       # www.sec.gov / efts.sec.gov
    "User-Agent": _USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
}

_REQUEST_DELAY_S = 0.12               # EDGAR fair-use: ≤10 req/s

# Global rate-limiter — serialises all EDGAR HTTP calls across threads
# so that concurrent deep-review workers never exceed 10 req/s combined.
_RATE_LOCK = threading.Lock()
_LAST_REQUEST_TS: float = 0.0


def _rate_limit() -> None:
    """Block until enough time has elapsed since the last EDGAR request.

    Thread-safe: uses a module-level lock so multiple workers sharing the
    same process respect the SEC fair-use policy (≤10 req/s).
    """
    global _LAST_REQUEST_TS
    with _RATE_LOCK:
        now = time.monotonic()
        elapsed = now - _LAST_REQUEST_TS
        if elapsed < _REQUEST_DELAY_S:
            time.sleep(_REQUEST_DELAY_S - elapsed)
        _LAST_REQUEST_TS = time.monotonic()

# Blob coordinates for the pre-built index (built by build_edgar_index.py)
_EDGAR_INDEX_CONTAINER = "edgar-index-blob"
_EDGAR_INDEX_BLOB = "edgar_index.json.gz"

# Module-level cache — populated once per process lifetime
_INDEX_CACHE: dict | None = None      # {"by_light": {...}, "by_heavy": {...}}

# XBRL concept fallback lists — tried in order
_CONCEPTS_NAV_PER_SHARE         = ["NetAssetValuePerShare"]
_CONCEPTS_TOTAL_ASSETS          = ["Assets"]
_CONCEPTS_TOTAL_DEBT            = ["LongTermDebtAndCapitalLeaseObligations",
                                    "LongTermDebt", "DebtAndCapitalLeaseObligations"]
_CONCEPTS_NET_INVESTMENT_INCOME = ["InvestmentIncomeNet", "NetInvestmentIncome",
                                    "InvestmentIncome"]
_CONCEPTS_DIVIDENDS_PAID        = ["PaymentsOfDividendsCommonStock",
                                    "DividendsPaid", "PaymentsOfDividends"]

# Sponsor / Asset Manager concepts (listed AM platforms: Ares, Blue Owl, Apollo, KKR, etc.)
_CONCEPTS_AUM = [
    "AssetsUnderManagement",
    "FundsUnderManagement",
]
_CONCEPTS_MANAGEMENT_FEE_REVENUE = [
    "ManagementFeeRevenue",
    "ManagementFees",
    "BaseManagementFeeRevenue",
    "ManagementAndAdvisoryFeesRevenue",
]
_CONCEPTS_FEE_RELATED_EARNINGS = [
    "FeeRelatedEarnings",
    "FeeRelatedEarningsAfterTax",
]
_CONCEPTS_DISTRIBUTABLE_EARNINGS = [
    "DistributableEarnings",
    "DistributableEarningsLoss",
]
_CONCEPTS_TOTAL_REVENUES = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "TotalRevenues",
]

# SIC codes for AM platforms (investment advice / holding companies)
_AM_PLATFORM_SIC_CODES = {"6282", "6726", "6199"}

# SIC codes that trigger XBRL extraction overall (investment vehicles)
_INVESTMENT_SIC_CODES = {"6726", "6798", "6199", "6770"}

_GOING_CONCERN_KEYWORDS = [
    "going concern",
    "substantial doubt",
    "ability to continue as a going concern",
    "doubt about the company's ability to continue",
    "conditions raise substantial doubt",
]


# ──────────────────────────────────────────────────────────────────────
#  Name normalization (must stay in sync with build_edgar_index.py)
# ──────────────────────────────────────────────────────────────────────

def _normalize_light(name: str) -> str:
    """Lowercase + collapse punctuation/spaces. Preserves all meaningful words."""
    n = name.lower()
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _normalize_heavy(name: str) -> str:
    """Light normalization + strip legal suffixes (inc/llc/corp/ltd/limited only).

    Does NOT strip Fund/Capital/Partners — those are meaningful differentiators
    for private funds.
    """
    n = _normalize_light(name)
    n = re.sub(
        r"\b(incorporated|corporation|inc|llc|corp|ltd|limited|lp|llp|plc|the)\b",
        " ", n,
    )
    n = re.sub(r"\s+", " ", n).strip()
    return n


# ──────────────────────────────────────────────────────────────────────
#  Index loading from blob
# ──────────────────────────────────────────────────────────────────────

def _entry_priority(entry: dict) -> int:
    """Score for collision resolution: prefer registered filers over Form D-only."""
    forms = set(entry.get("form_types", []))
    score = 0
    if forms & {"10-K", "10-K/A"}:
        score += 10
    if forms & {"N-2", "N-CEN"}:
        score += 8
    if forms & {"10-Q"}:
        score += 5
    if forms & {"D", "D/A"}:
        score += 1
    return score


def _load_edgar_index() -> dict:
    """Load and cache the EDGAR entity index from blob storage.

    Returns dict with:
        by_light: {name_light → best entry}   — primary lookup
        by_heavy: {name_heavy → [entries]}    — fallback (collision list)

    Cached at module level — one blob fetch per process lifetime (~50ms).
    """
    global _INDEX_CACHE
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE

    from app.services.blob_storage import blob_uri, download_bytes

    uri = blob_uri(_EDGAR_INDEX_CONTAINER, _EDGAR_INDEX_BLOB)
    logger.info("EDGAR_INDEX_LOADING blob=%s", uri)

    compressed = download_bytes(blob_uri=uri)
    raw_json = gzip.decompress(compressed)
    entries: list[dict] = json.loads(raw_json)

    by_light: dict[str, dict] = {}
    by_heavy: dict[str, list] = defaultdict(list)

    for entry in entries:
        lkey = entry.get("name_light") or _normalize_light(entry.get("name", ""))
        hkey = entry.get("name_heavy") or _normalize_heavy(entry.get("name", ""))

        # Keep highest-priority entry on light-key collision
        if lkey not in by_light or _entry_priority(entry) > _entry_priority(by_light[lkey]):
            by_light[lkey] = entry

        by_heavy[hkey].append(entry)

    _INDEX_CACHE = {"by_light": by_light, "by_heavy": dict(by_heavy)}

    logger.info(
        "EDGAR_INDEX_LOADED entries=%d by_light=%d by_heavy=%d",
        len(entries), len(by_light), len(by_heavy),
    )
    return _INDEX_CACHE


# ──────────────────────────────────────────────────────────────────────
#  CIK resolution
# ──────────────────────────────────────────────────────────────────────

def resolve_cik(
    entity_name: str,
    ticker: str | None = None,
) -> tuple[str | None, str | None]:
    """Resolve entity name to a zero-padded 10-digit CIK.

    Resolution order:
      1. Blob index by ticker (if provided).
      2. Blob index by light-normalized name (case/punct insensitive).
      3. Blob index by heavy-normalized name (strips inc/llc/corp).
         On collision, prefers registered filers over Form D-only.
      4. EDGAR full-text search fallback (efts.sec.gov).

    Returns (cik_10digit, matched_canonical_name) or (None, None).
    """
    # Steps 1-3: blob index
    try:
        index = _load_edgar_index()
        by_light = index["by_light"]
        by_heavy = index["by_heavy"]

        # 1. Ticker
        if ticker:
            ticker_upper = ticker.strip().upper()
            for entry in by_light.values():
                if ticker_upper in (entry.get("tickers") or []):
                    return entry["cik"], entry["name"]

        # 2. Light normalization
        hit = by_light.get(_normalize_light(entity_name))
        if hit:
            logger.debug("EDGAR_CIK_RESOLVED method=light entity=%s cik=%s", entity_name, hit["cik"])
            return hit["cik"], hit["name"]

        # 3. Heavy normalization
        candidates = by_heavy.get(_normalize_heavy(entity_name), [])
        if candidates:
            best = max(candidates, key=_entry_priority)
            logger.debug("EDGAR_CIK_RESOLVED method=heavy entity=%s cik=%s", entity_name, best["cik"])
            return best["cik"], best["name"]

    except Exception as exc:
        logger.warning("EDGAR_INDEX_LOOKUP_FAILED entity=%s: %s", entity_name, exc)

    # Step 4: EDGAR full-text search fallback
    return _resolve_cik_via_efts(entity_name)


def _resolve_cik_via_efts(entity_name: str) -> tuple[str | None, str | None]:
    """Fallback CIK resolution via EDGAR full-text search."""
    for query in [f'"{entity_name}"', entity_name]:
        try:
            _rate_limit()
            resp = httpx.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={"q": query, "forms": "10-K,N-2,N-CEN,D"},
                headers=_HEADERS_SEC,
                timeout=20.0,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", {}).get("hits", [])
            if hits:
                src = hits[0].get("_source", {})
                entity_id = src.get("entity_id", "")
                matched = (src.get("display_names") or [entity_name])[0]
                if entity_id:
                    cik = str(entity_id).zfill(10)
                    logger.debug("EDGAR_CIK_RESOLVED method=efts entity=%s cik=%s", entity_name, cik)
                    return cik, matched
        except Exception as exc:
            logger.debug("EDGAR_EFTS_FAILED query=%s: %s", query, exc)

    return None, None


# ──────────────────────────────────────────────────────────────────────
#  HTTP helpers
# ──────────────────────────────────────────────────────────────────────

def _get_json(url: str, *, params: dict | None = None, timeout: float = 30.0) -> Any:
    _rate_limit()
    headers = _HEADERS_DATA if "data.sec.gov" in url else _HEADERS_SEC
    resp = httpx.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _get_text(url: str, *, timeout: float = 30.0) -> str:
    _rate_limit()
    resp = httpx.get(
        url,
        headers={**_HEADERS_SEC, "Accept": "text/html, text/plain"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.text


# ──────────────────────────────────────────────────────────────────────
#  Submissions metadata
# ──────────────────────────────────────────────────────────────────────

def fetch_submissions(cik10: str) -> dict[str, Any]:
    """Fetch entity submissions from data.sec.gov/submissions/CIK{cik10}.json.

    "filings.recent" contains parallel columnar arrays — index N across all
    arrays identifies the same unique filing, ordered descending by date.
    """
    return _get_json(f"https://data.sec.gov/submissions/CIK{cik10}.json")


def extract_entity_metadata(submissions: dict) -> dict[str, Any]:
    """Parse submissions JSON into structured entity metadata."""
    recent     = submissions.get("filings", {}).get("recent", {})
    forms      = recent.get("form", [])
    dates      = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    prim_docs  = recent.get("primaryDocument", [])

    filing_index: dict[str, dict] = {}
    for form, date, acc, doc in zip(forms, dates, accessions, prim_docs, strict=False):
        if form not in filing_index:
            filing_index[form] = {
                "date": date,
                "accession_raw": acc,
                "accession_nodash": acc.replace("-", ""),
                "primary_doc": doc,
            }

    def latest(form_type: str) -> dict | None:
        return filing_index.get(form_type)

    cik_raw = submissions.get("cik", "")
    return {
        "cik": str(cik_raw).zfill(10) if cik_raw else None,
        "cik_int": cik_raw,
        "name": submissions.get("name"),
        "tickers": submissions.get("tickers", []),
        "exchanges": submissions.get("exchanges", []),
        "sic": submissions.get("sic"),
        "sic_description": submissions.get("sicDescription"),
        "state_of_incorporation": submissions.get("stateOfIncorporation"),
        "entity_type": submissions.get("entityType"),
        "fiscal_year_end": submissions.get("fiscalYearEnd"),
        "latest_10k":    latest("10-K"),
        "latest_10q":    latest("10-Q"),
        "latest_8k":     latest("8-K"),
        "latest_n2":     latest("N-2"),
        "latest_ncen":   latest("N-CEN"),
        "latest_form_d": latest("D"),
    }


# ──────────────────────────────────────────────────────────────────────
#  XBRL financial facts
# ──────────────────────────────────────────────────────────────────────

def fetch_company_facts(cik10: str) -> dict[str, Any]:
    """Fetch all XBRL company facts. Contains duplicates — filter on frame key."""
    return _get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json")


def _extract_concept_value(
    facts: dict,
    concept: str,
    *,
    unit: str = "USD",
    prefer_annual: bool = True,
) -> dict[str, Any] | None:
    """Extract most recent canonical value for a US-GAAP concept.

    Deduplication: filter on "frame" key presence (EDGAR canonical marker).
    Sort by "end" date descending. Prefer annual (10-K) over quarterly.

    Returns a dict with value AND full provenance, or None if not found.

    Return shape:
    {
      "val":        float,         # the numeric value
      "end":        str,           # period end date, e.g. "2023-12-31"
      "start":      str | None,    # period start date (flow items only)
      "filed":      str,           # SEC filing date, e.g. "2024-03-15"
      "form":       str,           # "10-K", "10-Q", etc.
      "accession":  str,           # accession number
      "concept":    str,           # the GAAP concept used (for audit trail)
      "unit":       str,           # "USD", "USD/shares", etc.
      "frame":      str | None,    # EDGAR canonical frame key if present
    }
    """
    try:
        observations: list[dict] = (
            facts.get("facts", {})
            .get("us-gaap", {})
            .get(concept, {})
            .get("units", {})
            .get(unit, [])
        )
    except (AttributeError, TypeError):
        return None

    if not observations:
        return None

    framed = [o for o in observations if "frame" in o]
    if not framed:
        framed = [o for o in observations if o.get("form") in
                  ("10-K", "10-K/A", "10-Q", "10-Q/A")]
    if not framed:
        framed = observations

    framed_sorted = sorted(framed, key=lambda o: o.get("end", ""), reverse=True)

    if prefer_annual:
        annual = [o for o in framed_sorted if o.get("form") in ("10-K", "10-K/A")]
        if annual:
            obs = annual[0]
            return {
                "val":       float(obs["val"]),
                "end":       obs.get("end"),
                "start":     obs.get("start"),
                "filed":     obs.get("filed"),
                "form":      obs.get("form"),
                "accession": obs.get("accn"),
                "concept":   concept,
                "unit":      unit,
                "frame":     obs.get("frame"),
            }

    if framed_sorted:
        obs = framed_sorted[0]
        return {
            "val":       float(obs["val"]),
            "end":       obs.get("end"),
            "start":     obs.get("start"),
            "filed":     obs.get("filed"),
            "form":      obs.get("form"),
            "accession": obs.get("accn"),
            "concept":   concept,
            "unit":      unit,
            "frame":     obs.get("frame"),
        }

    return None


def _extract_concept_multi_period(
    facts: dict,
    concept: str,
    *,
    unit: str = "USD",
    n_periods: int = 3,
) -> list[dict[str, Any]]:
    """Extract the last N annual observations for a concept, with full provenance.

    Returns list of dicts (same shape as _extract_concept_value return),
    sorted descending by end date. Empty list if concept not found.

    Useful for trend analysis: e.g. Total Assets for FY2021, FY2022, FY2023.
    """
    try:
        observations: list[dict] = (
            facts.get("facts", {})
            .get("us-gaap", {})
            .get(concept, {})
            .get("units", {})
            .get(unit, [])
        )
    except (AttributeError, TypeError):
        return []

    if not observations:
        return []

    # Annual 10-K filings only
    annual = [
        o for o in observations
        if o.get("form") in ("10-K", "10-K/A")
    ]
    if not annual:
        return []

    # Deduplicate by end date (keep highest-filed for each period)
    by_end: dict[str, dict] = {}
    for o in annual:
        end = o.get("end", "")
        if end not in by_end or o.get("filed", "") > by_end[end].get("filed", ""):
            by_end[end] = o

    sorted_obs = sorted(by_end.values(), key=lambda o: o.get("end", ""), reverse=True)

    result = []
    for obs in sorted_obs[:n_periods]:
        result.append({
            "val":       float(obs["val"]),
            "end":       obs.get("end"),
            "start":     obs.get("start"),
            "filed":     obs.get("filed"),
            "form":      obs.get("form"),
            "accession": obs.get("accn"),
            "concept":   concept,
            "unit":      unit,
            "frame":     obs.get("frame"),
        })

    return result


def extract_bdc_reit_metrics(facts: dict) -> dict[str, Any]:
    """Extract BDC/REIT financial metrics from XBRL facts with full provenance.

    Return shape:
    {
      "nav_per_share":             {"val": float, "as_of": str, "filed": str, "form": str, "concept": str},
      "total_assets_usd":          {"val": float, "as_of": str, "filed": str, "form": str, "concept": str},
      "total_debt_usd":            {"val": float, "as_of": str, "filed": str, "form": str, "concept": str},
      "net_investment_income_usd": {"val": float, "period_start": str, "period_end": str, ...},
      "dividends_paid_usd":        {"val": float, "period_start": str, "period_end": str, ...},
      "leverage_ratio":            {"val": float, "exceeds_1940_act_cap": bool, ...},
      "nii_dividend_coverage":     {"val": float, "below_1x": bool, ...},
      "total_assets_trend":        [{"val": float, "as_of": str, "form": str}, ...],  # 3 years
      "data_as_of":                str,
      "fiscal_year":               str,
    }
    """
    metrics: dict[str, Any] = {}

    # ── NAV per share ────────────────────────────────────────────────
    for concept in _CONCEPTS_NAV_PER_SHARE:
        obs = _extract_concept_value(facts, concept, unit="USD/shares")
        if obs:
            metrics["nav_per_share"] = {
                "val":     round(obs["val"], 4),
                "as_of":   obs["end"],
                "filed":   obs["filed"],
                "form":    obs["form"],
                "concept": obs["concept"],
            }
            break

    # ── Total assets ─────────────────────────────────────────────────
    for concept in _CONCEPTS_TOTAL_ASSETS:
        obs = _extract_concept_value(facts, concept)
        if obs:
            metrics["total_assets_usd"] = {
                "val":     obs["val"],
                "as_of":   obs["end"],
                "filed":   obs["filed"],
                "form":    obs["form"],
                "concept": obs["concept"],
            }
            break

    # ── Total debt ───────────────────────────────────────────────────
    for concept in _CONCEPTS_TOTAL_DEBT:
        obs = _extract_concept_value(facts, concept)
        if obs:
            metrics["total_debt_usd"] = {
                "val":     obs["val"],
                "as_of":   obs["end"],
                "filed":   obs["filed"],
                "form":    obs["form"],
                "concept": obs["concept"],
            }
            break

    # ── Net investment income ────────────────────────────────────────
    for concept in _CONCEPTS_NET_INVESTMENT_INCOME:
        obs = _extract_concept_value(facts, concept, prefer_annual=True)
        if obs:
            metrics["net_investment_income_usd"] = {
                "val":          obs["val"],
                "period_start": obs.get("start"),
                "period_end":   obs["end"],
                "filed":        obs["filed"],
                "form":         obs["form"],
                "concept":      obs["concept"],
            }
            break

    # ── Dividends paid ───────────────────────────────────────────────
    for concept in _CONCEPTS_DIVIDENDS_PAID:
        obs = _extract_concept_value(facts, concept, prefer_annual=True)
        if obs:
            metrics["dividends_paid_usd"] = {
                "val":          abs(obs["val"]),
                "period_start": obs.get("start"),
                "period_end":   obs["end"],
                "filed":        obs["filed"],
                "form":         obs["form"],
                "concept":      obs["concept"],
            }
            break

    # ── Total assets trend (3 years) ─────────────────────────────────
    for concept in _CONCEPTS_TOTAL_ASSETS:
        trend = _extract_concept_multi_period(facts, concept, n_periods=3)
        if trend:
            metrics["total_assets_trend"] = [
                {"val": t["val"], "as_of": t["end"], "form": t["form"]}
                for t in trend
            ]
            break

    # ── Derived: leverage ratio ───────────────────────────────────────
    ta_obs = metrics.get("total_assets_usd")
    td_obs = metrics.get("total_debt_usd")
    if ta_obs and td_obs:
        total_assets = ta_obs["val"]
        total_debt   = td_obs["val"]
        if total_assets > 0:
            equity = total_assets - total_debt
            if equity > 0:
                lev = round(total_debt / equity, 3)
                metrics["leverage_ratio"] = {
                    "val":                    lev,
                    "exceeds_1940_act_cap":   lev > 1.0,
                    "assets_as_of":           ta_obs["as_of"],
                    "debt_as_of":             td_obs["as_of"],
                    "period_mismatch_warning": ta_obs["as_of"] != td_obs["as_of"],
                }

    # ── Derived: NII dividend coverage ───────────────────────────────
    nii_obs  = metrics.get("net_investment_income_usd")
    divs_obs = metrics.get("dividends_paid_usd")
    if nii_obs and divs_obs and divs_obs["val"] > 0:
        cov = round(nii_obs["val"] / divs_obs["val"], 3)
        metrics["nii_dividend_coverage"] = {
            "val":                    cov,
            "below_1x":               cov < 1.0,
            "nii_period":             nii_obs.get("period_end"),
            "dividends_period":       divs_obs.get("period_end"),
            "period_mismatch_warning": nii_obs.get("period_end") != divs_obs.get("period_end"),
        }

    # ── Summary fields ────────────────────────────────────────────────
    balance_sheet_dates = [
        m["as_of"] for m in [
            metrics.get("total_assets_usd"),
            metrics.get("total_debt_usd"),
            metrics.get("nav_per_share"),
        ]
        if m and m.get("as_of")
    ]
    if balance_sheet_dates:
        metrics["data_as_of"] = max(balance_sheet_dates)
        try:
            metrics["fiscal_year"] = metrics["data_as_of"][:4]
        except Exception:
            metrics["fiscal_year"] = None

    return metrics


def extract_am_platform_metrics(facts: dict) -> dict[str, Any]:
    """Extract alternative asset manager financial metrics from XBRL facts.

    Used when the entity is an AM platform (sponsor/manager), not a BDC/REIT.
    Distinguishes from extract_bdc_reit_metrics() to avoid concept confusion.

    Return shape: same provenance structure as extract_bdc_reit_metrics().
    """
    metrics: dict[str, Any] = {}

    for concept in _CONCEPTS_TOTAL_ASSETS:
        obs = _extract_concept_value(facts, concept)
        if obs:
            metrics["total_assets_usd"] = {
                "val": obs["val"], "as_of": obs["end"],
                "filed": obs["filed"], "form": obs["form"], "concept": obs["concept"],
            }
            break

    for concept in _CONCEPTS_TOTAL_REVENUES:
        obs = _extract_concept_value(facts, concept, prefer_annual=True)
        if obs:
            metrics["total_revenues_usd"] = {
                "val": obs["val"], "period_end": obs["end"],
                "period_start": obs.get("start"), "filed": obs["filed"],
                "form": obs["form"], "concept": obs["concept"],
            }
            break

    for concept in _CONCEPTS_MANAGEMENT_FEE_REVENUE:
        obs = _extract_concept_value(facts, concept, prefer_annual=True)
        if obs:
            metrics["management_fee_revenue_usd"] = {
                "val": obs["val"], "period_end": obs["end"],
                "period_start": obs.get("start"), "filed": obs["filed"],
                "form": obs["form"], "concept": obs["concept"],
            }
            break

    for concept in _CONCEPTS_FEE_RELATED_EARNINGS:
        obs = _extract_concept_value(facts, concept, prefer_annual=True)
        if obs:
            metrics["fee_related_earnings_usd"] = {
                "val": obs["val"], "period_end": obs["end"],
                "period_start": obs.get("start"), "filed": obs["filed"],
                "form": obs["form"], "concept": obs["concept"],
            }
            break

    for concept in _CONCEPTS_DISTRIBUTABLE_EARNINGS:
        obs = _extract_concept_value(facts, concept, prefer_annual=True)
        if obs:
            metrics["distributable_earnings_usd"] = {
                "val": obs["val"], "period_end": obs["end"],
                "period_start": obs.get("start"), "filed": obs["filed"],
                "form": obs["form"], "concept": obs["concept"],
            }
            break

    # Summary
    balance_dates = [
        m.get("as_of") or m.get("period_end")
        for m in [metrics.get("total_assets_usd"), metrics.get("total_revenues_usd")]
        if m
    ]
    if balance_dates:
        metrics["data_as_of"] = max(d for d in balance_dates if d)
        metrics["fiscal_year"] = metrics["data_as_of"][:4] if metrics.get("data_as_of") else None

    return metrics


# ──────────────────────────────────────────────────────────────────────
#  Going concern scan
# ──────────────────────────────────────────────────────────────────────

def check_going_concern(cik_int: Any, latest_10k: dict | None) -> bool | None:
    """Scan primary doc of latest 10-K for going-concern language.

    URL: /Archives/edgar/data/{cik_bare}/{accession_nodash}/{primary_doc}

    Two-pass strategy:
      1. Targeted scan — locate the auditor report section and search within it.
         This catches going-concern opinions buried deep in multi-hundred-page 10-Ks.
      2. Broad scan — search first 200k chars as fallback (covers cover page,
         MD&A, and Notes where going-concern disclosures also appear).

    Returns True | False | None.
    """
    if not latest_10k or not cik_int:
        return None
    try:
        acc_nodash  = latest_10k.get("accession_nodash", "")
        primary_doc = latest_10k.get("primary_doc", "")
        if not acc_nodash or not primary_doc:
            return None
        cik_bare = str(int(cik_int))
        doc_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_bare}/{acc_nodash}/{primary_doc}"
        )
        raw_text = _get_text(doc_url)
        text_lower = raw_text[:200_000].lower()

        # Pass 1: targeted — find auditor report section and search within it.
        _AUDITOR_MARKERS = [
            "report of independent registered public accounting firm",
            "independent auditor",
            "report of independent auditor",
        ]
        for marker in _AUDITOR_MARKERS:
            idx = text_lower.find(marker)
            if idx >= 0:
                # Auditor reports are typically 3-8k chars
                section = text_lower[idx : idx + 15_000]
                if any(kw in section for kw in _GOING_CONCERN_KEYWORDS):
                    return True

        # Pass 2: broad scan — covers MD&A, Notes, and other disclosure areas.
        return any(kw in text_lower for kw in _GOING_CONCERN_KEYWORDS)
    except Exception as exc:
        logger.debug("EDGAR_GOING_CONCERN_FAILED: %s", exc)
        return None


# ──────────────────────────────────────────────────────────────────────
#  Form D search
# ──────────────────────────────────────────────────────────────────────

def search_form_d(entity_name: str) -> dict[str, Any] | None:
    """Search EDGAR full-text for Form D filings. Returns metadata or None."""
    try:
        _rate_limit()
        resp = httpx.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={"q": f'"{entity_name}"', "forms": "D"},
            headers=_HEADERS_SEC,
            timeout=20.0,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        if not hits:
            return None
        src = hits[0].get("_source", {})
        return {
            "filing_date": src.get("file_date"),
            "entity_name": (src.get("display_names") or [entity_name])[0],
            "accession": src.get("accession_no"),
            "form_type": src.get("form_type", "D"),
        }
    except Exception as exc:
        logger.debug("EDGAR_FORM_D_FAILED: %s", exc)
        return None


# ──────────────────────────────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────────────────────────────

def fetch_edgar_data(
    entity_name: str,
    *,
    instrument_type: str = "UNKNOWN",
    ticker: str | None = None,
) -> dict[str, Any]:
    """Fetch SEC EDGAR data for an entity. Entry point for Deep Review Stage 2.7.

    Never raises — all errors captured in result["warnings"].

    Returns dict with keys:
        status:            "FOUND" | "NOT_FOUND" | "FORM_D_ONLY" | "SKIPPED"
        cik:               Zero-padded 10-digit CIK or None
        matched_name:      EDGAR canonical name or None
        entity_metadata:   From extract_entity_metadata() or {}
        financial_metrics: From extract_bdc_reit_metrics() or {}
        going_concern:     True | False | None
        form_d:            Form D metadata dict or None
        instrument_type:   Passed through
        lookup_entity:     entity_name used
        warnings:          List[str] of non-fatal issues
    """
    result: dict[str, Any] = {
        "status": "NOT_FOUND",
        "cik": None,
        "matched_name": None,
        "entity_metadata": {},
        "financial_metrics": {},
        "metrics_type": "BDC_REIT",
        "going_concern": None,
        "form_d": None,
        "instrument_type": instrument_type,
        "lookup_entity": entity_name,
        "warnings": [],
    }

    if not entity_name or not entity_name.strip():
        result["status"] = "SKIPPED"
        result["warnings"].append("entity_name is empty — EDGAR lookup skipped")
        return result

    logger.info("EDGAR_LOOKUP_START entity=%s instrument_type=%s", entity_name, instrument_type)

    # ── Step 1: Resolve CIK ───────────────────────────────────────
    cik: str | None = None
    matched_name: str | None = None
    try:
        cik, matched_name = resolve_cik(entity_name, ticker=ticker)
    except Exception as exc:
        result["warnings"].append(f"CIK resolution failed: {exc}")

    if not cik:
        logger.info("EDGAR_CIK_NOT_FOUND entity=%s — trying Form D", entity_name)
        try:
            form_d = search_form_d(entity_name)
            result["form_d"] = form_d
            result["status"] = "FORM_D_ONLY" if form_d else "NOT_FOUND"
        except Exception as exc:
            result["warnings"].append(f"Form D search failed: {exc}")
        return result

    result["cik"] = cik
    result["matched_name"] = matched_name
    result["status"] = "FOUND"

    # ── Step 2: Submissions metadata ──────────────────────────────
    submissions: dict = {}
    entity_meta: dict = {}
    try:
        submissions = fetch_submissions(cik)
        entity_meta = extract_entity_metadata(submissions)
        result["entity_metadata"] = entity_meta
    except Exception as exc:
        result["warnings"].append(f"Submissions fetch failed: {exc}")
        logger.warning("EDGAR_SUBMISSIONS_FAILED entity=%s: %s", entity_name, exc)

    latest_10k = entity_meta.get("latest_10k")
    cik_int    = entity_meta.get("cik_int") or submissions.get("cik")

    # ── Step 3: XBRL financial metrics ───────────────────────────
    sic = str(entity_meta.get("sic") or "")
    should_extract_xbrl = (
        instrument_type in ("LISTED_SECURITY", "OPEN_ENDED_FUND", "CLOSED_END_FUND")
        or sic in _INVESTMENT_SIC_CODES
    )
    if should_extract_xbrl:
        try:
            facts = fetch_company_facts(cik)
            # Choose extractor: AM platform SICs use AM extractor
            if sic in _AM_PLATFORM_SIC_CODES or instrument_type == "LISTED_SECURITY":
                # Try AM extractor first; fall back to BDC if no AM-specific metrics found
                am_metrics = extract_am_platform_metrics(facts)
                if am_metrics.get("management_fee_revenue_usd") or am_metrics.get("fee_related_earnings_usd"):
                    result["financial_metrics"] = am_metrics
                    result["metrics_type"] = "AM_PLATFORM"
                else:
                    result["financial_metrics"] = extract_bdc_reit_metrics(facts)
                    result["metrics_type"] = "BDC_REIT"
            else:
                result["financial_metrics"] = extract_bdc_reit_metrics(facts)
                result["metrics_type"] = "BDC_REIT"
        except Exception as exc:
            result["warnings"].append(f"XBRL facts fetch failed: {exc}")
            logger.warning("EDGAR_XBRL_FAILED entity=%s: %s", entity_name, exc)

    # ── Step 4: Going concern scan ────────────────────────────────
    try:
        result["going_concern"] = check_going_concern(cik_int, latest_10k)
    except Exception as exc:
        result["warnings"].append(f"Going concern check failed: {exc}")

    # ── Step 5: Form D supplemental ──────────────────────────────
    if instrument_type in ("OPEN_ENDED_FUND", "CLOSED_END_FUND", "UNKNOWN"):
        try:
            result["form_d"] = search_form_d(entity_name)
        except Exception as exc:
            result["warnings"].append(f"Form D search failed: {exc}")

    logger.info(
        "EDGAR_LOOKUP_COMPLETE entity=%s cik=%s status=%s has_financials=%s "
        "going_concern=%s has_form_d=%s warnings=%d",
        entity_name, cik, result["status"],
        bool(result["financial_metrics"]), result["going_concern"],
        bool(result["form_d"]), len(result["warnings"]),
    )
    return result


# ──────────────────────────────────────────────────────────────────────
#  Context serializer for LLM injection
# ──────────────────────────────────────────────────────────────────────


def _fmt_metric(m: dict | None, fmt: str = "currency") -> str:
    """Format a provenance metric dict as 'value (as of DATE)'.

    Used by build_edgar_multi_entity_context().
    """
    if not m:
        return "n/a"
    val   = m.get("val")
    as_of = m.get("as_of") or m.get("period_end")
    date_str = f" (as of {as_of})" if as_of else ""
    warn     = " \u26a0 period mismatch" if m.get("period_mismatch_warning") else ""
    if val is None:
        return f"n/a{date_str}"
    if fmt == "currency":
        return f"${val:,.0f}{date_str}{warn}"
    elif fmt == "currency_4dp":
        return f"${val:.4f}{date_str}{warn}"
    elif fmt == "ratio":
        return f"{val:.2f}x{date_str}{warn}"
    elif fmt == "pct":
        return f"{val:.1f}%{date_str}{warn}"
    return f"{val}{date_str}{warn}"




# ──────────────────────────────────────────────────────────────────────
#  Multi-entity search (deal-level)
# ──────────────────────────────────────────────────────────────────────

_SKIP_ENTITY_NAMES: set[str] = {
    "", "n/a", "none", "unknown", "tbd", "pending", "pending diligence",
    "...", "various", "see docs", "portfolio companies tbd",
    "various borrowers", "various cannabis operator borrowers",
    "multiple borrowers", "to be determined", "not disclosed",
}


def _normalize_entity_for_dedup(name: str) -> str:
    """Lowercase, strip suffixes like LP/LLC/Inc/Ltd for dedup purposes."""
    import re
    s = name.strip().lower()
    s = re.sub(r",?\s*(inc\.?|llc|lp|ltd\.?|limited|corp\.?|plc|co\.?)$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_searchable_entities(
    deal_fields: dict[str, Any],
    analysis: dict[str, Any] | None = None,
    *,
    ticker: str | None = None,
    instrument_type: str = "UNKNOWN",
) -> list[dict[str, Any]]:
    """Build deduplicated list of entities to search in EDGAR.

    Sources checked (in priority order):
        1. deal_fields["deal_name"]         → role "fund/vehicle"
        2. deal_fields["sponsor_name"]      → role "sponsor/manager"
        3. deal_fields["borrower_name"]     → role "borrower"
        4. analysis.corporateStructure.borrower   → role "borrower"
        5. analysis.corporateStructure.guarantors → role "guarantor"
        6. analysis.corporateStructure.spvs       → role "spv"
        7. analysis.sponsorDetails.investmentManager → role "investment_manager"
        8. analysis.sponsorDetails.gpEntity        → role "gp"

    Returns list of dicts:  [{"name": str, "role": str, "ticker": str|None,
                               "is_direct_target": bool, "relationship_desc": str}]
    """
    _ROLE_RELATIONSHIP: dict[str, str] = {
        "fund/vehicle": (
            "This is the investment vehicle under analysis. "
            "EDGAR data for this entity pertains directly to the target."
        ),
        "sponsor/manager": (
            "Manager or sponsor of the target vehicle — a separate legal entity. "
            "Any public fund managed by this sponsor is a DIFFERENT vehicle from "
            "the private fund under review. Financial metrics belong to the "
            "PUBLIC entity, NOT the target vehicle."
        ),
        "borrower": (
            "Underlying borrower in the credit structure. "
            "EDGAR data reflects the borrower's own financials, not the fund's."
        ),
        "guarantor": (
            "Guarantor of obligations within the deal structure. "
            "EDGAR data reflects the guarantor's own financials."
        ),
        "spv": (
            "Special purpose vehicle in the transaction structure. "
            "May or may not be the direct target entity."
        ),
        "investment_manager": (
            "Investment manager / adviser — a separate legal entity. "
            "Any public fund managed by this adviser is a DIFFERENT vehicle. "
            "Financial metrics belong to that public entity, NOT the target."
        ),
        "gp": (
            "General partner of the target vehicle. "
            "EDGAR data reflects the GP entity's own filings."
        ),
    }

    seen_normalized: set[str] = set()
    entities: list[dict[str, Any]] = []

    def _add(
        name: str | None,
        role: str,
        entity_ticker: str | None = None,
        *,
        is_direct_target: bool = False,
    ) -> None:
        if not name or not isinstance(name, str):
            return
        name = name.strip()
        if name.lower() in _SKIP_ENTITY_NAMES:
            return
        # Skip generic placeholder patterns
        low = name.lower()
        if low.startswith(("various ", "multiple ", "portfolio companies", "see ")):
            return
        if low.endswith((" tbd", " pending")):
            return
        norm = _normalize_entity_for_dedup(name)
        if not norm or norm in seen_normalized:
            return
        seen_normalized.add(norm)
        entities.append({
            "name": name,
            "role": role,
            "ticker": entity_ticker,
            "is_direct_target": is_direct_target,
            "relationship_desc": _ROLE_RELATIONSHIP.get(role, ""),
        })

    def _is_valid_extracted(val: str | None) -> bool:
        """Check if an LLM-extracted string is a usable entity name."""
        if not val or not isinstance(val, str):
            return False
        low = val.strip().lower()
        return low not in ("", "pending diligence", "n/a", "not specified",
                           "pending", "unknown", "tbd")

    def _names_overlap(a: str, b: str) -> bool:
        """Check if two entity names are substantially the same."""
        na = _normalize_entity_for_dedup(a)
        nb = _normalize_entity_for_dedup(b)
        if not na or not nb:
            return False
        return na == nb or na in nb or nb in na

    # ── Smart target detection ───────────────────────────────────
    # The deal_name field may contain the sponsor/manager name rather
    # than the actual investment vehicle (e.g. "Garrington" instead of
    # "NELI US LP").  The structured analysis may contain a targetVehicle
    # field that identifies the correct entity.
    deal_name = deal_fields.get("deal_name", "")
    sponsor_name = deal_fields.get("sponsor_name", "")

    # 1) Extract explicit targetVehicle from analysis (if the LLM found one)
    target_vehicle_name: str | None = None
    if analysis:
        tv = analysis.get("targetVehicle")
        if _is_valid_extracted(tv):
            target_vehicle_name = tv.strip()  # type: ignore[union-attr]

    # 2) Detect if deal_name is actually the sponsor (common pattern:
    #    user names the deal after the sponsor firm)
    deal_is_sponsor = False
    if deal_name and sponsor_name:
        deal_is_sponsor = _names_overlap(deal_name, sponsor_name)
    if not deal_is_sponsor and deal_name and analysis:
        sponsor_det = analysis.get("sponsorDetails") or {}
        if isinstance(sponsor_det, dict):
            firm = sponsor_det.get("firmName")
            if isinstance(firm, str) and _is_valid_extracted(firm) and _names_overlap(deal_name, firm):
                deal_is_sponsor = True

    logger.info(
        "EDGAR_TARGET_DETECTION deal_name=%r target_vehicle=%r "
        "deal_is_sponsor=%s",
        deal_name, target_vehicle_name, deal_is_sponsor,
    )

    # ── Add entities in priority order ───────────────────────────
    if target_vehicle_name:
        # Explicit target vehicle identified by the LLM → DIRECT TARGET
        _add(target_vehicle_name, "fund/vehicle", ticker, is_direct_target=True)
        # deal_name: classify correctly (sponsor or secondary reference)
        if deal_is_sponsor:
            _add(deal_name, "sponsor/manager")
        else:
            # May be a different name for the same vehicle (dedup handles it)
            # or a holding entity — add as fund/vehicle but NOT direct target
            _add(deal_name, "fund/vehicle")
    else:
        # No targetVehicle from analysis — fall back to deal_name
        if deal_is_sponsor:
            # deal_name looks like the sponsor → do NOT mark as direct target
            _add(deal_name, "sponsor/manager")
        else:
            _add(deal_name, "fund/vehicle", ticker, is_direct_target=True)

    # Sponsor / GP / Investment Manager — very likely a US-registered entity
    _add(sponsor_name, "sponsor/manager")

    # Borrower from deal record
    _add(deal_fields.get("borrower_name"), "borrower")

    # LLM-extracted entities from structured analysis
    if analysis:
        corp = analysis.get("corporateStructure") or {}

        # Borrower from corporate structure — may be the target vehicle
        corp_borrower = corp.get("borrower")
        if isinstance(corp_borrower, str) and _is_valid_extracted(corp_borrower):
            borrower_is_target = (
                target_vehicle_name is not None
                and _names_overlap(corp_borrower, target_vehicle_name)
            )
            if borrower_is_target:
                _add(corp_borrower, "fund/vehicle", is_direct_target=True)
            else:
                _add(corp_borrower, "borrower")

        for g in (corp.get("guarantors") or []):
            if isinstance(g, str):
                _add(g, "guarantor")

        # SPVs — check if any SPV matches the target vehicle
        for spv in (corp.get("spvs") or []):
            if isinstance(spv, str) and _is_valid_extracted(spv):
                spv_is_target = (
                    target_vehicle_name is not None
                    and _names_overlap(spv, target_vehicle_name)
                )
                if spv_is_target:
                    _add(spv, "fund/vehicle", is_direct_target=True)
                else:
                    _add(spv, "spv")

        # Sponsor details block (populated by Stage 1 analysis)
        sponsor_det = analysis.get("sponsorDetails") or analysis.get("sponsor") or {}
        if isinstance(sponsor_det, dict):
            _add(sponsor_det.get("investmentManager"), "investment_manager")
            _add(sponsor_det.get("gpEntity"), "gp")
            _add(sponsor_det.get("name"), "sponsor/manager")
            _add(sponsor_det.get("firmName"), "sponsor/manager")

    logger.info(
        "EDGAR_ENTITIES_EXTRACTED count=%d names=%s",
        len(entities), [e["name"] for e in entities],
    )
    return entities


def fetch_edgar_multi_entity(
    entities: list[dict[str, Any]],
    *,
    instrument_type: str = "UNKNOWN",
) -> dict[str, Any]:
    """Run EDGAR lookup for multiple entities; deduplicate by CIK.

    Returns:
        {
            "results": [
                {
                    "role": str,          # entity role (fund/vehicle, sponsor, etc.)
                    "lookup_entity": str,  # name searched
                    **fetch_edgar_data_result
                },
                ...
            ],
            "unique_ciks":     int,
            "entities_tried":  int,
            "entities_found":  int,
            "combined_warnings": List[str],
        }

    """
    results: list[dict[str, Any]] = []
    seen_ciks: set[str] = set()
    combined_warnings: list[str] = []
    entities_found = 0

    for entity in entities:
        name = entity["name"]
        role = entity["role"]
        entity_ticker = entity.get("ticker")

        logger.info("EDGAR_MULTI_LOOKUP entity='%s' role=%s", name, role)

        edgar_data = fetch_edgar_data(
            entity_name=name,
            instrument_type=instrument_type,
            ticker=entity_ticker,
        )

        cik = edgar_data.get("cik")

        # Deduplicate: if same CIK already found, append role but skip full result
        if cik and cik in seen_ciks:
            logger.info(
                "EDGAR_MULTI_DEDUP cik=%s already found via earlier entity, skipping '%s'",
                cik, name,
            )
            # Find existing result and append role
            for existing in results:
                if existing.get("cik") == cik:
                    existing.setdefault("also_matched_as", []).append(
                        {"name": name, "role": role},
                    )
                    break
            continue

        if cik:
            seen_ciks.add(cik)

        entry = {
            **edgar_data,
            "role": role,
            "is_direct_target": entity.get("is_direct_target", False),
            "relationship_desc": entity.get("relationship_desc", ""),
        }
        results.append(entry)

        if edgar_data.get("status") in ("FOUND", "FORM_D_ONLY"):
            entities_found += 1

        for w in edgar_data.get("warnings", []):
            combined_warnings.append(f"[{name}] {w}")

    summary = {
        "results": results,
        "unique_ciks": len(seen_ciks),
        "entities_tried": len(entities),
        "entities_found": entities_found,
        "combined_warnings": combined_warnings,
    }

    logger.info(
        "EDGAR_MULTI_COMPLETE tried=%d found=%d unique_ciks=%d",
        len(entities), entities_found, len(seen_ciks),
    )
    return summary


def build_edgar_multi_entity_context(
    multi_result: dict[str, Any],
    *,
    deal_name: str = "",
    target_vehicle: str = "",
) -> str:
    """Build combined EDGAR context section from multi-entity results.

    Renders each entity result clearly separated, with role labels and
    **explicit attribution guardrails** that prevent the LLM from
    attributing financial metrics from a related entity (e.g. a publicly
    listed BDC/REIT managed by the same sponsor) to the target vehicle.

    ``target_vehicle`` is the specific legal entity identified by the
    structured analysis as the actual investment target.  When provided,
    it overrides ``deal_name`` for attribution labelling — fixing the
    common case where ``deal_name`` is actually the sponsor name.
    """
    results = multi_result.get("results", [])
    if not results:
        return ""

    target_label = target_vehicle or deal_name or "the target investment vehicle"

    # If ALL results are NOT_FOUND/SKIPPED, emit a single short message
    found_any = any(
        r.get("status") in ("FOUND", "FORM_D_ONLY") for r in results
    )
    if not found_any:
        entities_tried = [r.get("lookup_entity", "?") for r in results]
        return (
            "=== SEC EDGAR PUBLIC FILING DATA ===\n"
            f"Entities searched: {', '.join(entities_tried)}\n"
            "Status: No EDGAR filings found for any related entity.\n"
            "All entities may be private/foreign-registered. "
            "Absence of EDGAR data is not itself a flaw."
        )

    # Check if any entity is the direct target
    has_direct_target = any(
        r.get("is_direct_target", False) for r in results
    )

    # When no direct target was identified, ensure target_label doesn't
    # fall back to deal_name (which may be the sponsor itself — circular).
    if not has_direct_target:
        target_label = "the target investment vehicle (not yet identified in EDGAR)"

    # ── Attribution Framework (always at the top) ──────────────────────
    sections: list[str] = [
        "=== SEC EDGAR PUBLIC FILING DATA (Multi-Entity) ===",
        "",
        "╔══════════════════════════════════════════════════════════════════╗",
        "║       ⚠  EDGAR DATA ATTRIBUTION RULES — READ FIRST  ⚠        ║",
        "╠══════════════════════════════════════════════════════════════════╣",
        "║ Multiple entities related to this deal were searched in EDGAR. ║",
        "║ Each entity below is labeled DIRECT TARGET or RELATED ENTITY.  ║",
        "║                                                                ║",
        "║ CRITICAL RULES:                                                ║",
        "║ 1. Financial metrics (AUM, leverage, assets, debt, NAV) from   ║",
        "║    a RELATED ENTITY belong to THAT entity only — NEVER         ║",
        "║    attribute them to the target vehicle.                        ║",
        "║ 2. A publicly listed BDC/REIT managed by the same sponsor is   ║",
        "║    a DIFFERENT vehicle from the private fund under review.      ║",
        "║ 3. EDGAR data from related entities is useful ONLY for:         ║",
        "║    • Assessing the manager's platform scale & track record      ║",
        "║    • Verifying regulatory standing & compliance history         ║",
        "║    • Identifying going concern or material adverse events       ║",
        "║    • Understanding the sponsor's public market presence         ║",
        "║ 4. NEVER use a related entity's leverage ratio, total assets,  ║",
        "║    or AUM as the target fund's own metrics.                     ║",
        "║ 5. When citing EDGAR data, ALWAYS specify which entity it      ║",
        "║    belongs to and the relationship to the target.               ║",
        "╚══════════════════════════════════════════════════════════════════╝",
        "",
    ]

    # ── No Direct Target warning ─────────────────────────────────────
    if not has_direct_target:
        sections.extend([
            "╔══════════════════════════════════════════════════════════════════╗",
            "║  ⚠⚠  NO DIRECT TARGET VEHICLE IDENTIFIED IN EDGAR  ⚠⚠        ║",
            "╠══════════════════════════════════════════════════════════════════╣",
            "║ The target investment vehicle was NOT found among the EDGAR     ║",
            "║ entities below. ALL data below belongs to RELATED entities      ║",
            "║ (sponsors, managers, or affiliates) — NOT the target fund.      ║",
            "║                                                                ║",
            "║ YOU MUST NOT:                                                   ║",
            "║ • Use ANY financial metric below as a proxy for the target fund ║",
            "║ • Attribute AUM, leverage, assets, or NAV to the target vehicle ║",
            "║ • Treat sponsor-level data as fund-level underwriting inputs    ║",
            "║                                                                ║",
            "║ YOU MAY ONLY USE this data for:                                 ║",
            "║ • Manager/sponsor platform assessment and track record          ║",
            "║ • Regulatory standing and compliance history verification       ║",
            "║ • Going concern or material adverse event detection             ║",
            "╚══════════════════════════════════════════════════════════════════╝",
            "",
        ])
        sections.append(
            f"Deal name: {deal_name or 'N/A'} "
            f"(identified as sponsor/manager — not the investment vehicle)",
        )
    else:
        sections.append(f"Target vehicle under analysis: {target_label}")

    sections.extend([
        f"Searched {multi_result['entities_tried']} entities, "
        f"found {multi_result['entities_found']} in EDGAR "
        f"({multi_result['unique_ciks']} unique CIKs).",
        "",
    ])

    for r in results:
        status = r.get("status", "NOT_FOUND")
        role = r.get("role", "unknown")
        name = r.get("lookup_entity") or r.get("matched_name") or "?"
        is_direct = r.get("is_direct_target", False)
        rel_desc = r.get("relationship_desc", "")

        if status == "SKIPPED":
            continue

        # Entity header with target classification
        target_tag = "DIRECT TARGET" if is_direct else "RELATED ENTITY"
        sections.append(f"--- [{target_tag}] {role.upper()}: {name} ---")

        if not is_direct and rel_desc:
            sections.append(f"  Relationship: {rel_desc}")

        if status == "NOT_FOUND":
            sections.append("  Not found in EDGAR (entity may be private/offshore).")
            continue

        if status == "FORM_D_ONLY":
            sections.append("  Private entity — not in EDGAR index.")
            form_d = r.get("form_d")
            if form_d:
                sections.append(f"  Form D (Reg D): filed {form_d.get('filing_date', 'n/a')}")
                sections.append(f"    Entity: {form_d.get('entity_name', 'n/a')}")
            continue

        # FOUND — full render
        sections.append(f"  Entity: {r.get('matched_name') or name}")
        sections.append(f"  CIK: {r.get('cik')}")

        also = r.get("also_matched_as", [])
        if also:
            aliases = ", ".join(f"{a['name']} ({a['role']})" for a in also)
            sections.append(f"  Also matched: {aliases}")

        meta = r.get("entity_metadata", {})
        if meta:
            if meta.get("tickers"):
                sections.append(f"  Ticker(s): {', '.join(meta['tickers'])}")
            if meta.get("exchanges"):
                sections.append(f"  Exchange(s): {', '.join(meta['exchanges'])}")
            sections.append(f"  SIC: {meta.get('sic', 'n/a')} — {meta.get('sic_description', '')}")
            sections.append(f"  State: {meta.get('state_of_incorporation', 'n/a')}")
            sections.append(f"  Entity type: {meta.get('entity_type', 'n/a')}")
            for label, key in [
                ("10-K", "latest_10k"), ("10-Q", "latest_10q"),
                ("N-2", "latest_n2"), ("N-CEN", "latest_ncen"),
            ]:
                entry = meta.get(key)
                if entry:
                    sections.append(f"  Latest {label}: {entry.get('date', 'n/a')}")

        # Going concern — prominent (relevant regardless of entity type)
        gc = r.get("going_concern")
        if gc is True:
            if is_direct:
                sections.append("  ⚠ GOING CONCERN DETECTED ⚠ — escalate immediately")
            else:
                sections.append(
                    f"  ⚠ GOING CONCERN DETECTED in {name} ⚠ — "
                    f"this is a RELATED entity; assess contagion risk to {target_label}",
                )
        elif gc is False:
            sections.append("  Going concern: Not detected")

        # Financial metrics with attribution guardrails
        metrics      = r.get("financial_metrics", {})
        metrics_type = r.get("metrics_type", "BDC_REIT")
        if metrics:
            if is_direct:
                sections.append("  XBRL Metrics (DIRECT TARGET — may use for underwriting):")
            else:
                sections.append(
                    f"  XBRL Metrics (\u26a0 belong to {name}, NOT to {target_label}):",
                )
                sections.append(
                    f"  \u26a0 USE ONLY for manager platform assessment — do NOT treat "
                    f"as {target_label} metrics.",
                )
            if metrics_type == "BDC_REIT":
                if "total_assets_usd" in metrics:
                    sections.append(f"    Total assets: {_fmt_metric(metrics['total_assets_usd'])}")
                if "total_debt_usd" in metrics:
                    sections.append(f"    Total debt: {_fmt_metric(metrics['total_debt_usd'])}")
                if "leverage_ratio" in metrics:
                    lev = metrics["leverage_ratio"]
                    flag = " \u26a0 1940 Act cap exceeded" if lev.get("exceeds_1940_act_cap") else ""
                    sections.append(f"    Leverage: {_fmt_metric(lev, 'ratio')}{flag}")
                if "net_investment_income_usd" in metrics:
                    sections.append(f"    NII: {_fmt_metric(metrics['net_investment_income_usd'])}")
                if "nii_dividend_coverage" in metrics:
                    cov = metrics["nii_dividend_coverage"]
                    flag = " \u26a0 Below 1.0x" if cov.get("below_1x") else ""
                    sections.append(f"    NII coverage: {_fmt_metric(cov, 'ratio')}{flag}")
            elif metrics_type == "AM_PLATFORM":
                if "total_assets_usd" in metrics:
                    sections.append(f"    Total assets: {_fmt_metric(metrics['total_assets_usd'])}")
                if "management_fee_revenue_usd" in metrics:
                    sections.append(f"    Mgmt fee revenue: {_fmt_metric(metrics['management_fee_revenue_usd'])}")
                if "fee_related_earnings_usd" in metrics:
                    sections.append(f"    FRE: {_fmt_metric(metrics['fee_related_earnings_usd'])}")
                if "distributable_earnings_usd" in metrics:
                    sections.append(f"    DE: {_fmt_metric(metrics['distributable_earnings_usd'])}")

        form_d = r.get("form_d")
        if form_d:
            sections.append(
                f"  Form D: filed {form_d.get('filing_date', 'n/a')} "
                f"— {form_d.get('entity_name', 'n/a')}",
            )

        sections.append("")  # blank line between entities

    if multi_result.get("combined_warnings"):
        sections.append(f"Warnings: {'; '.join(multi_result['combined_warnings'][:5])}")

    return "\n".join(sections)
