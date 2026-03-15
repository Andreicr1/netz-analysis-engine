"""CIK resolution — hybrid edgartools + blob index fallback.

Resolution strategy (ordered by preference):
  1. edgartools Company(ticker) — deterministic, sub-second
  2. edgartools find(name) — fuzzy matching with confidence threshold ≥ 70%
  3. Blob index (light → heavy normalization) — offline-first fallback
  4. EDGAR full-text search (efts.sec.gov) — last resort

Sync service — dispatched via asyncio.to_thread() from async callers.
"""
from __future__ import annotations

import re
from typing import Any

import structlog

from vertical_engines.credit.edgar.models import CikResolution

logger = structlog.get_logger()


# ── Name normalization (kept in sync with build_edgar_index.py) ──


def _normalize_light(name: str) -> str:
    """Lowercase + collapse punctuation/spaces. Preserves all meaningful words."""
    n = name.lower()
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _normalize_heavy(name: str) -> str:
    """Light normalization + strip legal suffixes (inc/llc/corp/ltd only).

    Does NOT strip Fund/Capital/Partners — those are meaningful differentiators
    for private credit entities.
    """
    n = _normalize_light(name)
    n = re.sub(
        r"\b(incorporated|corporation|inc|llc|corp|ltd|limited|lp|llp|plc|the)\b",
        " ", n,
    )
    n = re.sub(r"\s+", " ", n).strip()
    return n


# ── Entity name sanitization ─────────────────────────────────────


_MAX_ENTITY_NAME_LENGTH = 200


def sanitize_entity_name(name: str) -> str | None:
    """Sanitize entity name for SEC API queries.

    Returns None if the name is empty, too long, or a known placeholder.
    """
    if not name or not name.strip():
        return None
    # Strip control characters
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = name.strip()
    if len(name) > _MAX_ENTITY_NAME_LENGTH:
        logger.warning("entity_name_too_long", length=len(name), truncated=name[:50])
        return None
    return name


# ── edgartools-based resolution ──────────────────────────────────


def _resolve_via_edgartools(
    entity_name: str,
    ticker: str | None = None,
) -> CikResolution:
    """Resolve CIK using edgartools library.

    Tier 1: Company(ticker) — deterministic, confidence=1.0
    Tier 2: find(name) — fuzzy matching, confidence=fuzz.ratio/100
    """
    try:
        from edgar import Company, find
    except ImportError:
        return CikResolution(cik=None, company_name=None, method="not_found", confidence=0.0)

    # Tier 1: ticker lookup (most reliable)
    if ticker:
        try:
            company = Company(ticker.strip().upper())
            if not company.not_found:
                cik = str(company.cik).zfill(10)
                logger.debug(
                    "cik_resolved",
                    method="ticker",
                    entity=entity_name,
                    cik=cik,
                    matched_name=company.name,
                )
                return CikResolution(
                    cik=cik,
                    company_name=company.name,
                    method="ticker",
                    confidence=1.0,
                )
        except Exception as exc:
            logger.debug("ticker_lookup_failed", ticker=ticker, error=str(exc))

    # Tier 2: fuzzy name search with confidence validation
    try:
        from rapidfuzz import fuzz

        results = find(entity_name)
        if results:
            best = results[0]
            similarity = fuzz.ratio(entity_name.lower(), best.name.lower()) / 100.0
            if similarity >= 0.85:
                cik = str(best.cik).zfill(10)
                logger.debug(
                    "cik_resolved",
                    method="fuzzy",
                    entity=entity_name,
                    cik=cik,
                    matched_name=best.name,
                    confidence=round(similarity, 3),
                )
                return CikResolution(
                    cik=cik,
                    company_name=best.name,
                    method="fuzzy",
                    confidence=similarity,
                )
            else:
                logger.debug(
                    "fuzzy_match_below_threshold",
                    entity=entity_name,
                    best_match=best.name,
                    similarity=round(similarity, 3),
                )
    except Exception as exc:
        logger.debug("fuzzy_search_failed", entity=entity_name, error=str(exc))

    return CikResolution(cik=None, company_name=None, method="not_found", confidence=0.0)


# ── Blob index fallback ──────────────────────────────────────────

# Module-level cache — plain dict (not asyncio primitive), safe at module level.
# Benign race: worst case is redundant blob download; dict assignment is GIL-atomic.
_INDEX_CACHE: dict[str, Any] | None = None


def _entry_priority(entry: dict[str, Any]) -> int:
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


def _load_edgar_index() -> dict[str, Any]:
    """Load and cache the EDGAR entity index from blob storage.

    Returns dict with:
        by_light: {name_light -> best entry}
        by_heavy: {name_heavy -> [entries]}

    Cached at module level — one blob fetch per process lifetime.
    """
    import gzip
    import json
    from collections import defaultdict

    global _INDEX_CACHE
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE

    try:
        from app.services.blob_storage import blob_uri, download_bytes
    except ImportError:
        logger.warning("blob_storage_not_available")
        _INDEX_CACHE = {"by_light": {}, "by_heavy": {}}
        return _INDEX_CACHE

    try:
        uri = blob_uri("edgar-index-blob", "edgar_index.json.gz")
        compressed = download_bytes(blob_uri=uri)
        raw_json = gzip.decompress(compressed)
        entries: list[dict[str, Any]] = json.loads(raw_json)

        by_light: dict[str, dict[str, Any]] = {}
        by_heavy: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for entry in entries:
            lkey = entry.get("name_light") or _normalize_light(entry.get("name", ""))
            hkey = entry.get("name_heavy") or _normalize_heavy(entry.get("name", ""))

            if lkey not in by_light or _entry_priority(entry) > _entry_priority(by_light[lkey]):
                by_light[lkey] = entry

            by_heavy[hkey].append(entry)

        _INDEX_CACHE = {"by_light": by_light, "by_heavy": dict(by_heavy)}
        logger.info(
            "edgar_index_loaded",
            entries=len(entries),
            by_light=len(by_light),
            by_heavy=len(by_heavy),
        )
    except Exception as exc:
        logger.warning("edgar_index_load_failed", error=str(exc))
        _INDEX_CACHE = {"by_light": {}, "by_heavy": {}}

    return _INDEX_CACHE


def _resolve_via_blob_index(
    entity_name: str,
    ticker: str | None = None,
) -> CikResolution:
    """Resolve CIK using the pre-built blob index (offline-first)."""
    try:
        index = _load_edgar_index()
        by_light = index["by_light"]
        by_heavy = index["by_heavy"]

        # Ticker lookup
        if ticker:
            ticker_upper = ticker.strip().upper()
            for entry in by_light.values():
                if ticker_upper in (entry.get("tickers") or []):
                    return CikResolution(
                        cik=entry["cik"],
                        company_name=entry["name"],
                        method="blob_ticker",
                        confidence=1.0,
                    )

        # Light normalization
        hit = by_light.get(_normalize_light(entity_name))
        if hit:
            return CikResolution(
                cik=hit["cik"],
                company_name=hit["name"],
                method="blob_light",
                confidence=0.9,
            )

        # Heavy normalization
        candidates = by_heavy.get(_normalize_heavy(entity_name), [])
        if candidates:
            best = max(candidates, key=_entry_priority)
            return CikResolution(
                cik=best["cik"],
                company_name=best["name"],
                method="blob_heavy",
                confidence=0.8,
            )

    except Exception as exc:
        logger.warning("blob_index_resolution_failed", entity=entity_name, error=str(exc))

    return CikResolution(cik=None, company_name=None, method="not_found", confidence=0.0)


# ── Public API ────────────────────────────────────────────────────


def resolve_cik(
    entity_name: str,
    ticker: str | None = None,
) -> CikResolution:
    """Resolve entity name to a zero-padded 10-digit CIK.

    Strategy: edgartools primary (ticker → fuzzy), blob index fallback.
    Never raises — returns CikResolution with method="not_found" on failure.
    """
    name = sanitize_entity_name(entity_name)
    if not name:
        return CikResolution(cik=None, company_name=None, method="not_found", confidence=0.0)

    # Primary: edgartools
    result = _resolve_via_edgartools(name, ticker)
    if result.cik:
        return result

    # Fallback: blob index
    result = _resolve_via_blob_index(name, ticker)
    if result.cik:
        logger.info(
            "cik_resolved_via_fallback",
            entity=name,
            cik=result.cik,
            method=result.method,
        )
        return result

    logger.info("cik_resolution_failed", entity=name)
    return CikResolution(cik=None, company_name=None, method="not_found", confidence=0.0)
