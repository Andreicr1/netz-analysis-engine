"""EDGAR service — fetch_edgar_data() + fetch_edgar_multi_entity().

Sync service — dispatched via asyncio.to_thread() from async callers.

Key invariants:
- NEVER raises — all errors captured in result warnings
- Multi-entity orchestration with deduplication by CIK
- Parallel entity processing with ThreadPoolExecutor(max_workers=3)
- Returns dict[str, Any] at API boundary (backward compatible)
"""
from __future__ import annotations

import dataclasses
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import structlog

from vertical_engines.credit.edgar.cik_resolver import resolve_cik
from vertical_engines.credit.edgar.financials import (
    calculate_ratios,
    extract_am_platform_metrics,
    extract_bdc_reit_metrics,
    extract_structured_financials,
)
from vertical_engines.credit.edgar.going_concern import check_going_concern
from vertical_engines.credit.edgar.models import EdgarEntityResult

logger = structlog.get_logger()

# SIC codes for metric type routing
_AM_PLATFORM_SIC_CODES = {"6282", "6726", "6199"}
_INVESTMENT_SIC_CODES = {"6726", "6798", "6199", "6770"}


def fetch_edgar_data(
    entity_name: str,
    *,
    instrument_type: str = "UNKNOWN",
    ticker: str | None = None,
    role: str = "unknown",
    is_direct_target: bool = False,
) -> dict[str, Any]:
    """Fetch EDGAR data for a single entity. Never raises.

    Returns dict with keys:
        status, cik, matched_name, entity_metadata, financial_metrics,
        metrics_type, going_concern, form_d, warnings, lookup_entity,
        resolution_method, resolution_confidence
    """
    result = EdgarEntityResult(
        entity_name=entity_name,
        role=role,
        ticker=ticker,
        is_direct_target=is_direct_target,
    )
    warnings: list[str] = []

    # ── CIK Resolution ──
    cik_result = resolve_cik(entity_name, ticker)
    result.cik = cik_result.cik
    result.company_name = cik_result.company_name
    result.resolution_method = cik_result.method
    result.resolution_confidence = cik_result.confidence

    if not cik_result.cik:
        # Try Form D search as last resort
        form_d = _search_form_d(entity_name)
        if form_d:
            return _to_dict(result, status="FORM_D_ONLY", warnings=warnings, form_d=form_d)
        return _to_dict(result, status="NOT_FOUND", warnings=warnings)

    if cik_result.confidence < 0.7:
        warnings.append(
            f"Low confidence CIK match ({cik_result.confidence:.0%}): "
            f"'{entity_name}' matched to '{cik_result.company_name}'"
        )

    # ── Company metadata + financial extraction ──
    try:
        from edgar import Company

        company = Company(int(cik_result.cik))
        if company.not_found:
            warnings.append(f"Company not found for CIK {cik_result.cik}")
            return _to_dict(result, status="NOT_FOUND", warnings=warnings)

        result.company_name = company.name
        result.sic = str(company.sic) if company.sic else None
        result.fiscal_year_end = getattr(company, "fiscal_year_end", None)

        # Determine metric type based on SIC
        sic = str(company.sic) if company.sic else ""
        is_am = sic in _AM_PLATFORM_SIC_CODES
        is_investment = sic in _INVESTMENT_SIC_CODES

        # Structured financials
        try:
            result.financials = extract_structured_financials(company)
            if result.financials and result.financials.balance_sheet:
                result.financials.ratios = calculate_ratios(result.financials)
        except Exception as exc:
            warnings.append(f"Structured financials extraction failed: {type(exc).__name__}")
            logger.warning("financials_failed", entity=entity_name, exc_info=True)

        # BDC/REIT or AM Platform metrics
        try:
            if is_am:
                result.am_platform_metrics = extract_am_platform_metrics(company)
            elif is_investment:
                result.bdc_reit_metrics = extract_bdc_reit_metrics(company)
        except Exception as exc:
            warnings.append(f"Metric extraction failed: {type(exc).__name__}")
            logger.warning("metrics_failed", entity=entity_name, exc_info=True)

        # Going concern
        try:
            result.going_concern = check_going_concern(company)
        except Exception as exc:
            warnings.append(f"Going concern scan failed: {type(exc).__name__}")
            logger.warning("going_concern_failed", entity=entity_name, exc_info=True)

    except ImportError:
        warnings.append("edgartools not installed")
    except Exception as exc:
        warnings.append(f"EDGAR lookup failed: {type(exc).__name__}")
        logger.warning(
            "edgar_lookup_failed",
            entity=entity_name,
            cik=cik_result.cik,
            exc_info=True,
        )

    return _to_dict(result, status="FOUND", warnings=warnings)


def fetch_edgar_multi_entity(
    entities: list[dict[str, Any]],
    *,
    instrument_type: str = "UNKNOWN",
) -> dict[str, Any]:
    """Run EDGAR lookup for multiple entities; deduplicate by CIK.

    Phase 1: Resolve all CIKs sequentially (for dedup).
    Phase 2: Fetch data in parallel with ThreadPoolExecutor(max_workers=3).

    Returns backward-compatible dict:
        results, unique_ciks, entities_tried, entities_found, combined_warnings
    """
    results: list[dict[str, Any]] = []
    seen_ciks: set[str] = set()
    combined_warnings: list[str] = []
    entities_found = 0

    # Phase 1: Resolve CIKs sequentially for dedup
    resolved: list[tuple[dict[str, Any], str | None]] = []
    for entity in entities:
        name = entity["name"]
        cik_result = resolve_cik(name, entity.get("ticker"))
        cik = cik_result.cik

        if cik and cik in seen_ciks:
            logger.info("edgar_multi_dedup", cik=cik, entity=name)
            for existing in results:
                if existing.get("cik") == cik:
                    existing.setdefault("also_matched_as", []).append(
                        {"name": name, "role": entity["role"]},
                    )
                    break
            continue

        if cik:
            seen_ciks.add(cik)
        resolved.append((entity, cik))

    # Phase 2: Fetch data in parallel
    def _fetch_one(entity: dict[str, Any]) -> dict[str, Any]:
        return fetch_edgar_data(
            entity_name=entity["name"],
            instrument_type=instrument_type,
            ticker=entity.get("ticker"),
            role=entity["role"],
            is_direct_target=entity.get("is_direct_target", False),
        )

    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="edgar") as pool:
        future_to_entity = {
            pool.submit(_fetch_one, entity): entity
            for entity, _ in resolved
        }
        for future in as_completed(future_to_entity):
            entity = future_to_entity[future]
            try:
                edgar_data = future.result()
            except Exception as exc:
                logger.warning("edgar_parallel_fetch_failed", entity=entity["name"], exc_info=True)
                edgar_data = {
                    "status": "NOT_FOUND",
                    "lookup_entity": entity["name"],
                    "warnings": [f"Fetch failed: {type(exc).__name__}"],
                }

            entry = {
                **edgar_data,
                "role": entity["role"],
                "is_direct_target": entity.get("is_direct_target", False),
                "relationship_desc": entity.get("relationship_desc", ""),
            }
            results.append(entry)

            if edgar_data.get("status") in ("FOUND", "FORM_D_ONLY"):
                entities_found += 1

            for w in edgar_data.get("warnings", []):
                combined_warnings.append(f"[{entity['name']}] {w}")

    summary = {
        "results": results,
        "unique_ciks": len(seen_ciks),
        "entities_tried": len(entities),
        "entities_found": entities_found,
        "combined_warnings": combined_warnings,
    }

    logger.info(
        "edgar_multi_complete",
        tried=len(entities),
        found=entities_found,
        unique_ciks=len(seen_ciks),
    )
    return summary


# ── Helpers ───────────────────────────────────────────────────────


def _to_dict(
    result: EdgarEntityResult,
    *,
    status: str,
    warnings: list[str],
    form_d: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert EdgarEntityResult to backward-compatible dict at API boundary."""
    d: dict[str, Any] = {
        "status": status,
        "cik": result.cik,
        "matched_name": result.company_name,
        "lookup_entity": result.entity_name,
        "resolution_method": result.resolution_method,
        "resolution_confidence": result.resolution_confidence,
        "warnings": warnings,
    }

    if result.company_name:
        d["entity_metadata"] = {
            "sic": result.sic,
            "sic_description": result.sic_description or "",
            "state_of_incorporation": result.state or "",
        }

    if result.bdc_reit_metrics:
        d["financial_metrics"] = result.bdc_reit_metrics
        d["metrics_type"] = "BDC_REIT"
    elif result.am_platform_metrics:
        d["financial_metrics"] = result.am_platform_metrics
        d["metrics_type"] = "AM_PLATFORM"

    if result.financials:
        d["structured_financials"] = dataclasses.asdict(result.financials)

    if result.going_concern:
        gc = result.going_concern
        d["going_concern"] = gc.get("verdict") == "confirmed"
        d["going_concern_detail"] = gc

    if result.insider_signals:
        d["insider_signals"] = [dataclasses.asdict(s) for s in result.insider_signals]

    if form_d:
        d["form_d"] = form_d

    return d


def _search_form_d(entity_name: str) -> dict[str, Any] | None:
    """Search for Form D filings via EDGAR full-text search.

    Preserved from ic_edgar_engine.py — uses EFTS directly.
    """
    import httpx

    try:
        url = "https://efts.sec.gov/LATEST/search-index"
        params = {
            "q": f'"{entity_name}"',
            "forms": "D",
            "dateRange": "custom",
            "startdt": "2020-01-01",
        }
        headers = {
            "User-Agent": "Netz Analysis Engine tech@netzco.com",
            "Accept-Encoding": "gzip, deflate",
        }
        resp = httpx.get(url, params=params, headers=headers, timeout=20.0)
        if resp.status_code == 200:
            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])
            if hits:
                hit = hits[0].get("_source", {})
                return {
                    "entity_name": hit.get("entity_name", entity_name),
                    "filing_date": hit.get("file_date", ""),
                    "form_type": "D",
                }
    except Exception as exc:
        logger.debug("form_d_search_failed", entity=entity_name, error=str(exc))

    return None
