"""Shared SEC infrastructure — CIK resolution, rate limiting, entity sanitization.

Fully standalone: zero imports from ``app.*``.
All external library imports (redis, edgartools, rapidfuzz, httpx) are lazy.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

import structlog

from data_providers.sec.models import CikResolution, CusipTickerResult

logger = structlog.get_logger()

T = TypeVar("T")

# ── Constants ────────────────────────────────────────────────────

SEC_USER_AGENT = "Netz Analysis Engine tech@netzco.com"
SEC_EDGAR_RATE_LIMIT = 8   # req/s (conservative under SEC 10/s)
SEC_IAPD_RATE_LIMIT = 1    # req/s (IAPD aggressively blocks — 403 at >2 req/s)

_MAX_ENTITY_NAME_LENGTH = 200
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9\s.,'\-&()]+$")


# ── Rate Limiting ────────────────────────────────────────────────

# Local fallback token buckets (used when Redis is unavailable).
# Dict of {bucket_name: (tokens_remaining, last_refill_time)}.
_local_buckets: dict[str, tuple[float, float]] = {}
_fallback_warned: set[str] = set()


def _check_rate(key_prefix: str, max_per_second: int) -> None:
    """Redis sliding window rate limiter with local token bucket fallback.

    Redis strategy: key = ``{prefix}:rate:{current_second}``, TTL = 2s.
    If count > max_per_second, sleep 1s.

    Local fallback: in-process token bucket at ``max_per_second / 4`` req/s.
    """
    try:
        import redis as redis_lib

        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            _check_rate_local(key_prefix, max_per_second)
            return

        r = redis_lib.from_url(redis_url, decode_responses=True)
        key = f"{key_prefix}:rate:{int(time.time())}"
        count: int = r.incr(key)  # type: ignore[assignment]
        if count == 1:
            r.expire(key, 2)
        if count > max_per_second:
            time.sleep(1.0)
    except Exception:
        _check_rate_local(key_prefix, max_per_second)


def _check_rate_local(key_prefix: str, max_per_second: int) -> None:
    """In-process token bucket fallback at rate/4 req/s."""
    if key_prefix not in _fallback_warned:
        _fallback_warned.add(key_prefix)
        logger.warning(
            "rate_limiter_redis_unavailable",
            key_prefix=key_prefix,
            fallback="local_token_bucket",
        )

    now = time.monotonic()
    local_rate = max(max_per_second / 4, 1.0)

    tokens, last_refill = _local_buckets.get(key_prefix, (local_rate, now))
    elapsed = now - last_refill
    tokens = min(local_rate, tokens + elapsed * local_rate)
    last_refill = now

    if tokens < 1.0:
        sleep_time = (1.0 - tokens) / local_rate
        time.sleep(sleep_time)
        tokens = 0.0
    else:
        tokens -= 1.0

    _local_buckets[key_prefix] = (tokens, last_refill)


def check_edgar_rate() -> None:
    """Rate-limit EDGAR API requests (sliding window, 8 req/s)."""
    _check_rate("edgar", SEC_EDGAR_RATE_LIMIT)


def check_iapd_rate() -> None:
    """Rate-limit IAPD API requests (sliding window, 2 req/s)."""
    _check_rate("iapd", SEC_IAPD_RATE_LIMIT)


# ── Name Normalization ───────────────────────────────────────────


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


# ── Entity Name Sanitization ────────────────────────────────────


def sanitize_entity_name(name: str) -> str | None:
    """Sanitize entity name for SEC API queries.

    Returns None if the name is empty, too long, contains invalid characters,
    or is a known placeholder. Includes character allowlist to prevent EFTS
    query injection.
    """
    if not name or not name.strip():
        return None
    # Strip control characters
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = name.strip()
    if len(name) > _MAX_ENTITY_NAME_LENGTH:
        logger.warning("entity_name_too_long", length=len(name), truncated=name[:50])
        return None
    # Security hardening: strict character allowlist
    if not _SAFE_NAME_RE.match(name):
        logger.warning(
            "entity_name_rejected",
            reason="failed_character_allowlist",
            name_preview=name[:50],
        )
        return None
    return name


# ── CIK Resolution ──────────────────────────────────────────────


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


def _resolve_via_efts(entity_name: str) -> CikResolution:
    """Resolve CIK via SEC EFTS full-text search (last resort).

    Queries ``efts.sec.gov/LATEST/search-index`` for the entity name.
    """
    try:
        import httpx
    except ImportError:
        logger.debug("httpx_not_available_for_efts")
        return CikResolution(cik=None, company_name=None, method="not_found", confidence=0.0)

    check_edgar_rate()

    try:
        resp = httpx.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={
                "q": entity_name,
                "dateRange": "custom",
                "startdt": "2020-01-01",
            },
            headers={"User-Agent": SEC_USER_AGENT},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

        hits = data.get("hits", {}).get("hits", [])
        if hits:
            hit = hits[0]
            source = hit.get("_source", {})
            # EFTS uses "ciks" (list) not "cik" (scalar)
            ciks_list = source.get("ciks") or []
            cik_raw = ciks_list[0] if ciks_list else source.get("entity_id")
            # display_names includes CIK suffix — strip it
            raw_names = source.get("display_names") or []
            raw_name = raw_names[0] if raw_names else ""
            company = re.sub(r"\s*\(CIK \d+\)\s*$", "", raw_name).strip() or None
            if cik_raw:
                cik = str(cik_raw).zfill(10)
                logger.debug(
                    "cik_resolved",
                    method="efts",
                    entity=entity_name,
                    cik=cik,
                    matched_name=company,
                )
                return CikResolution(
                    cik=cik,
                    company_name=company,
                    method="efts",
                    confidence=0.7,
                )
    except Exception as exc:
        logger.debug("efts_search_failed", entity=entity_name, error=str(exc))

    return CikResolution(cik=None, company_name=None, method="not_found", confidence=0.0)


def resolve_cik(
    entity_name: str,
    ticker: str | None = None,
) -> CikResolution:
    """Resolve entity name to a zero-padded 10-digit CIK.

    3-tier cascade:
      1. edgartools Company(ticker) — confidence=1.0
      2. edgartools find(name) + rapidfuzz ≥0.85 — confidence=ratio/100
      3. EFTS full-text search — confidence=0.7

    Never raises — returns CikResolution with method="not_found" on failure.
    """
    name = sanitize_entity_name(entity_name)
    if not name:
        return CikResolution(cik=None, company_name=None, method="not_found", confidence=0.0)

    # Tier 1 + 2: edgartools
    result = _resolve_via_edgartools(name, ticker)
    if result.cik:
        return result

    # Tier 3: EFTS full-text search
    result = _resolve_via_efts(name)
    if result.cik:
        logger.info(
            "cik_resolved_via_efts",
            entity=name,
            cik=result.cik,
        )
        return result

    logger.info("cik_resolution_failed", entity=name)
    return CikResolution(cik=None, company_name=None, method="not_found", confidence=0.0)


# ── Sector Resolution ──────────────────────────────────────────────

# SIC code → GICS sector mapping (covers ~100 most common SIC codes).
# Unknown SIC codes fall back to range-based classification.
SIC_TO_GICS_SECTOR: dict[str, str] = {
    # Energy (SIC 10xx-14xx)
    "1000": "Energy", "1311": "Energy", "1381": "Energy", "1382": "Energy",
    "1389": "Energy", "1400": "Energy", "2911": "Energy", "2990": "Energy",
    "4922": "Energy", "4923": "Energy", "4924": "Energy", "5171": "Energy",
    "5172": "Energy", "1200": "Energy", "1220": "Energy", "1221": "Energy",
    # Materials (SIC 26xx-28xx, 32xx-33xx)
    "2611": "Materials", "2621": "Materials", "2631": "Materials",
    "2650": "Materials", "2670": "Materials", "2800": "Materials",
    "2810": "Materials", "2820": "Materials", "2821": "Materials",
    "2860": "Materials", "2870": "Materials", "2890": "Materials",
    "2891": "Materials", "3241": "Materials", "3310": "Materials",
    "3312": "Materials", "3317": "Materials", "3330": "Materials",
    "3334": "Materials", "3350": "Materials", "3360": "Materials",
    "3411": "Materials", "3412": "Materials",
    # Industrials (SIC 34xx-38xx, 42xx-45xx)
    "3440": "Industrials", "3460": "Industrials", "3490": "Industrials",
    "3510": "Industrials", "3523": "Industrials", "3530": "Industrials",
    "3540": "Industrials", "3550": "Industrials", "3559": "Industrials",
    "3560": "Industrials", "3561": "Industrials", "3562": "Industrials",
    "3569": "Industrials", "3580": "Industrials", "3585": "Industrials",
    "3589": "Industrials", "3590": "Industrials", "3600": "Industrials",
    "3610": "Industrials", "3620": "Industrials", "3690": "Industrials",
    "3711": "Industrials", "3713": "Industrials", "3714": "Industrials",
    "3720": "Industrials", "3721": "Industrials", "3724": "Industrials",
    "3728": "Industrials", "3730": "Industrials", "3743": "Industrials",
    "3760": "Industrials", "3812": "Industrials", "3825": "Industrials",
    "3829": "Industrials", "4011": "Industrials", "4210": "Industrials",
    "4213": "Industrials", "4400": "Industrials", "4412": "Industrials",
    "4512": "Industrials", "4522": "Industrials", "4581": "Industrials",
    "4731": "Industrials", "4953": "Industrials", "5080": "Industrials",
    "5084": "Industrials", "7363": "Industrials", "8711": "Industrials",
    "8712": "Industrials", "8713": "Industrials", "8741": "Industrials",
    "8742": "Industrials",
    # Consumer Discretionary (SIC 22xx-23xx, 25xx, 50xx-59xx, 70xx-79xx)
    "2300": "Consumer Discretionary", "2320": "Consumer Discretionary",
    "2330": "Consumer Discretionary", "2390": "Consumer Discretionary",
    "2510": "Consumer Discretionary", "2511": "Consumer Discretionary",
    "2520": "Consumer Discretionary", "2531": "Consumer Discretionary",
    "3021": "Consumer Discretionary", "3140": "Consumer Discretionary",
    "3630": "Consumer Discretionary", "3651": "Consumer Discretionary",
    "3652": "Consumer Discretionary", "3944": "Consumer Discretionary",
    "5311": "Consumer Discretionary", "5331": "Consumer Discretionary",
    "5411": "Consumer Discretionary", "5500": "Consumer Discretionary",
    "5531": "Consumer Discretionary", "5600": "Consumer Discretionary",
    "5621": "Consumer Discretionary", "5651": "Consumer Discretionary",
    "5700": "Consumer Discretionary", "5712": "Consumer Discretionary",
    "5731": "Consumer Discretionary", "5810": "Consumer Discretionary",
    "5812": "Consumer Discretionary", "5900": "Consumer Discretionary",
    "5940": "Consumer Discretionary", "5944": "Consumer Discretionary",
    "5945": "Consumer Discretionary", "5960": "Consumer Discretionary",
    "5990": "Consumer Discretionary", "7011": "Consumer Discretionary",
    "7200": "Consumer Discretionary",
    "7822": "Consumer Discretionary",
    "7841": "Consumer Discretionary", "7900": "Consumer Discretionary",
    "7941": "Consumer Discretionary", "7990": "Consumer Discretionary",
    # Consumer Staples (SIC 20xx-21xx, 54xx)
    "2000": "Consumer Staples", "2010": "Consumer Staples",
    "2011": "Consumer Staples", "2013": "Consumer Staples",
    "2015": "Consumer Staples", "2020": "Consumer Staples",
    "2024": "Consumer Staples", "2030": "Consumer Staples",
    "2033": "Consumer Staples", "2040": "Consumer Staples",
    "2050": "Consumer Staples", "2060": "Consumer Staples",
    "2070": "Consumer Staples", "2080": "Consumer Staples",
    "2082": "Consumer Staples", "2086": "Consumer Staples",
    "2090": "Consumer Staples", "2092": "Consumer Staples",
    "2100": "Consumer Staples", "2111": "Consumer Staples",
    "5141": "Consumer Staples", "5149": "Consumer Staples",
    "5160": "Consumer Staples", "5461": "Consumer Staples",
    # Health Care (SIC 28xx pharma, 38xx med devices, 80xx)
    "2830": "Health Care", "2833": "Health Care", "2834": "Health Care",
    "2835": "Health Care", "2836": "Health Care",
    "3826": "Health Care", "3827": "Health Care", "3841": "Health Care",
    "3842": "Health Care", "3843": "Health Care", "3844": "Health Care",
    "3845": "Health Care", "3851": "Health Care",
    "5047": "Health Care", "5122": "Health Care",
    "8000": "Health Care", "8011": "Health Care", "8049": "Health Care",
    "8050": "Health Care", "8051": "Health Care", "8060": "Health Care",
    "8062": "Health Care", "8071": "Health Care", "8082": "Health Care",
    "8090": "Health Care", "8093": "Health Care", "8099": "Health Care",
    # Financials (SIC 60xx-67xx)
    "6010": "Financials", "6020": "Financials", "6021": "Financials",
    "6022": "Financials", "6029": "Financials", "6035": "Financials",
    "6036": "Financials", "6099": "Financials", "6111": "Financials",
    "6120": "Financials", "6141": "Financials", "6153": "Financials",
    "6159": "Financials", "6162": "Financials", "6163": "Financials",
    "6199": "Financials", "6200": "Financials", "6211": "Financials",
    "6282": "Financials", "6311": "Financials", "6321": "Financials",
    "6324": "Financials", "6331": "Financials", "6399": "Financials",
    "6411": "Financials", "6726": "Financials", "6770": "Financials",
    # Real Estate (SIC 65xx, 6798)
    "6500": "Real Estate", "6510": "Real Estate", "6512": "Real Estate",
    "6513": "Real Estate", "6531": "Real Estate", "6532": "Real Estate",
    "6552": "Real Estate", "6553": "Real Estate", "6798": "Real Estate",
    # Information Technology (SIC 357x, 366x-367x, 737x, 382x)
    "3571": "Information Technology", "3572": "Information Technology",
    "3575": "Information Technology", "3576": "Information Technology",
    "3577": "Information Technology", "3578": "Information Technology",
    "3579": "Information Technology",
    "3661": "Information Technology", "3663": "Information Technology",
    "3669": "Information Technology", "3672": "Information Technology",
    "3674": "Information Technology", "3675": "Information Technology",
    "3677": "Information Technology", "3678": "Information Technology",
    "3679": "Information Technology",
    "3695": "Information Technology", "3699": "Information Technology",
    "5045": "Information Technology", "5065": "Information Technology",
    "5734": "Information Technology",
    "7371": "Information Technology", "7372": "Information Technology",
    "7373": "Information Technology", "7374": "Information Technology",
    "7377": "Information Technology", "7378": "Information Technology",
    "7379": "Information Technology",
    # Communication Services (SIC 27xx, 48xx, 78xx)
    "2710": "Communication Services", "2711": "Communication Services",
    "2720": "Communication Services", "2731": "Communication Services",
    "2741": "Communication Services", "2750": "Communication Services",
    "2761": "Communication Services",
    "4800": "Communication Services", "4812": "Communication Services",
    "4813": "Communication Services", "4822": "Communication Services",
    "4832": "Communication Services", "4833": "Communication Services",
    "4841": "Communication Services", "4899": "Communication Services",
    "4810": "Communication Services",
    "7812": "Communication Services", "7819": "Communication Services",
    # Utilities (SIC 49xx)
    "4900": "Utilities", "4911": "Utilities", "4931": "Utilities",
    "4932": "Utilities", "4939": "Utilities", "4941": "Utilities",
    "4950": "Utilities", "4952": "Utilities",
    "4955": "Utilities", "4961": "Utilities", "4991": "Utilities",
}


def _sic_range_to_sector(sic: str) -> str | None:
    """Fallback: map SIC code to sector by range prefix."""
    if len(sic) < 2:
        return None
    prefix2 = sic[:2]
    if prefix2 in ("10", "12", "13", "14"):
        return "Energy"
    if prefix2 in ("20", "21"):
        return "Consumer Staples"
    if prefix2 in ("22", "23", "25", "31", "39"):
        return "Consumer Discretionary"
    if prefix2 in ("26",):
        return "Materials"
    if prefix2 in ("28",):
        # 283x = Health Care (pharma), other 28xx = Materials (chemicals)
        if len(sic) >= 3 and sic[:3] == "283":
            return "Health Care"
        return "Materials"
    if prefix2 in ("32", "33"):
        return "Materials"
    if prefix2 in ("34", "35", "36", "37", "38"):
        # 357x, 366x-367x = IT; 384x = Health Care; rest = Industrials
        if len(sic) >= 3:
            p3 = sic[:3]
            if p3 in ("357", "366", "367", "369"):
                return "Information Technology"
            if p3 in ("384", "382"):
                return "Health Care"
        return "Industrials"
    if prefix2 in ("27",):
        return "Communication Services"
    if prefix2 in ("40", "41", "42", "43", "44", "45", "46", "47"):
        return "Industrials"
    if prefix2 in ("48",):
        return "Communication Services"
    if prefix2 in ("49",):
        return "Utilities"
    if prefix2 in ("50", "51"):
        return "Industrials"
    if prefix2 in ("52", "53", "54", "55", "56", "57", "58", "59"):
        return "Consumer Discretionary"
    if prefix2 in ("60", "61", "62", "63", "64", "67"):
        return "Financials"
    if prefix2 in ("65",):
        return "Real Estate"
    if prefix2 in ("70", "72", "75", "76", "78", "79"):
        return "Consumer Discretionary"
    if prefix2 in ("73",):
        return "Information Technology"
    if prefix2 in ("80",):
        return "Health Care"
    if prefix2 in ("87",):
        return "Industrials"
    return None


# Canonical GICS sector labels — normalizes yfinance/alternative labels.
# yfinance uses slightly different names than GICS standard.
_SECTOR_CANONICAL: dict[str, str] = {
    # yfinance → GICS
    "Financial Services": "Financials",
    "Technology": "Information Technology",
    "Basic Materials": "Materials",
    "Healthcare": "Health Care",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Communication": "Communication Services",
    # Pass-through (already GICS)
    "Financials": "Financials",
    "Information Technology": "Information Technology",
    "Materials": "Materials",
    "Health Care": "Health Care",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Staples": "Consumer Staples",
    "Communication Services": "Communication Services",
    "Energy": "Energy",
    "Industrials": "Industrials",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
}


def _canonicalize_sector(sector: str | None) -> str | None:
    """Normalize sector label to GICS standard."""
    if not sector:
        return None
    return _SECTOR_CANONICAL.get(sector, sector)


# Issuer name keyword heuristic — last resort.
_ISSUER_SECTOR_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(REIT|REALTY|PROPERTIES|PROPERTY|REAL ESTATE)\b", re.I), "Real Estate"),
    (re.compile(r"\b(PHARMA|BIOTECH|THERAPEUTICS|BIOSCIENCE|MEDICAL|HEALTH)\b", re.I), "Health Care"),
    (re.compile(r"\b(SEMICONDUCTOR|SOFTWARE|TECHNOLOGY|TECH|CYBER|CLOUD|DATA)\b", re.I), "Information Technology"),
    (re.compile(r"\b(ENERGY|PETROLEUM|OIL|GAS|SOLAR|WIND|PIPELINE)\b", re.I), "Energy"),
    (re.compile(r"\b(BANCORP|BANK|FINANCIAL|INSURANCE|ASSET MGMT)\b", re.I), "Financials"),
    (re.compile(r"\b(UTILITY|UTILITIES|ELECTRIC|POWER|WATER)\b", re.I), "Utilities"),
    (re.compile(r"\b(TELECOM|COMMUNICATIONS|MEDIA|BROADCAST)\b", re.I), "Communication Services"),
    (re.compile(r"\b(MINING|CHEMICAL|STEEL|METALS|MATERIALS)\b", re.I), "Materials"),
    (re.compile(r"\b(FOOD|BEVERAGE|CONSUMER|GROCERY|TOBACCO)\b", re.I), "Consumer Staples"),
    (re.compile(r"\b(AIRLINE|AEROSPACE|DEFENSE|TRANSPORT|LOGISTICS)\b", re.I), "Industrials"),
    (re.compile(r"\b(RETAIL|RESTAURANT|HOTEL|LEISURE|GAMING|AUTO)\b", re.I), "Consumer Discretionary"),
]

# In-process sector cache (bounded, no Redis dependency).
_sector_cache: dict[str, str | None] = {}
_SECTOR_CACHE_MAX = 10_000


def _get_cached_sector(cusip: str) -> tuple[bool, str | None]:
    """Check sector cache (Redis → local). Returns (hit, sector)."""
    # Try Redis first
    try:
        import redis as redis_lib

        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            r = redis_lib.from_url(redis_url, decode_responses=True)
            val = r.get(f"sector:{cusip}")
            if val is not None:
                return (True, val if val != "__NONE__" else None)
    except Exception:
        pass

    # Local fallback
    if cusip in _sector_cache:
        return (True, _sector_cache[cusip])

    return (False, None)


def _set_cached_sector(cusip: str, sector: str | None) -> None:
    """Cache sector (Redis + local)."""
    # Redis
    try:
        import redis as redis_lib

        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            r = redis_lib.from_url(redis_url, decode_responses=True)
            r.setex(f"sector:{cusip}", 2_592_000, sector or "__NONE__")  # 30 days
    except Exception:
        pass

    # Local (bounded)
    if len(_sector_cache) < _SECTOR_CACHE_MAX:
        _sector_cache[cusip] = sector


def _resolve_sector_via_sic(issuer_name: str) -> str | None:
    """Tier 1: Resolve issuer CIK → SIC code → GICS sector."""
    try:
        from edgar import Company
    except ImportError:
        return None

    # Resolve issuer's CIK from name
    resolution = resolve_cik(issuer_name)
    if not resolution.cik:
        return None

    check_edgar_rate()

    try:
        company = Company(resolution.cik)
        if hasattr(company, "not_found") and company.not_found:
            return None
        sic = getattr(company, "sic", None)
        if not sic:
            return None
        sic_str = str(sic).strip()
        sector = SIC_TO_GICS_SECTOR.get(sic_str) or _sic_range_to_sector(sic_str)
        if sector:
            logger.debug(
                "sector_resolved_via_sic",
                issuer=issuer_name,
                sic=sic_str,
                sector=sector,
            )
        return sector
    except Exception as exc:
        logger.debug("sector_sic_resolution_failed", issuer=issuer_name, error=str(exc))
        return None


def _resolve_sector_via_openfigi(cusip: str) -> str | None:
    """Tier 2: CUSIP → ticker (OpenFIGI) → sector (yfinance)."""
    try:
        import httpx
    except ImportError:
        return None

    # OpenFIGI mapping (free, no auth, 250 req/min)
    try:
        resp = httpx.post(
            "https://api.openfigi.com/v3/mapping",
            json=[{"idType": "ID_CUSIP", "idValue": cusip}],
            headers={"Content-Type": "application/json"},
            timeout=10.0,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data or not data[0].get("data"):
            return None
        ticker = data[0]["data"][0].get("ticker")
        if not ticker:
            return None
    except Exception as exc:
        logger.debug("openfigi_lookup_failed", cusip=cusip, error=str(exc))
        return None

    # yfinance sector lookup
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).info
        sector = info.get("sector")
        if sector:
            logger.debug(
                "sector_resolved_via_yfinance",
                cusip=cusip,
                ticker=ticker,
                sector=sector,
            )
            return sector
    except Exception as exc:
        logger.debug("yfinance_sector_failed", cusip=cusip, ticker=ticker, error=str(exc))

    return None


def _resolve_sector_via_keyword(issuer_name: str) -> str | None:
    """Tier 3: Keyword heuristic on issuer name."""
    for pattern, sector in _ISSUER_SECTOR_KEYWORDS:
        if pattern.search(issuer_name):
            logger.debug(
                "sector_resolved_via_keyword",
                issuer=issuer_name,
                sector=sector,
            )
            return sector
    return None


def resolve_sector(
    cusip: str,
    issuer_name: str,
) -> str | None:
    """Resolve industry sector for a CUSIP via 3-tier cascade.

    1. EDGAR SIC code mapping (resolve_cik → Company.sic → GICS)
    2. OpenFIGI CUSIP→ticker → yfinance sector
    3. issuer_name keyword heuristic

    Results are cached in Redis (30d TTL) and in-process.
    Never raises.
    """
    # Check cache first
    hit, cached = _get_cached_sector(cusip)
    if hit:
        return cached

    sector: str | None = None
    try:
        # Tier 1: SIC mapping
        sector = _resolve_sector_via_sic(issuer_name)

        # Tier 2: OpenFIGI + yfinance
        if not sector:
            sector = _resolve_sector_via_openfigi(cusip)

        # Tier 3: Keyword heuristic
        if not sector:
            sector = _resolve_sector_via_keyword(issuer_name)
    except Exception as exc:
        logger.debug("sector_resolution_failed", cusip=cusip, error=str(exc))

    # Normalize to GICS standard labels
    sector = _canonicalize_sector(sector)

    _set_cached_sector(cusip, sector)
    return sector


# ── CUSIP → Ticker Resolution (OpenFIGI batch) ──────────────────

OPENFIGI_BATCH_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_BATCH_SIZE = 100  # max per request (OpenFIGI limit)

# Major exchanges where tickers are YFinance-compatible.
TRADEABLE_EXCHANGES = frozenset({
    "US", "UN", "UW", "UA",  # NYSE, NYSE ARCA, NASDAQ, NYSE American
    "UR", "UT",               # NYSE MKT, OTC
})


def _make_unresolved(cusip: str) -> CusipTickerResult:
    return CusipTickerResult(
        cusip=cusip, ticker=None, issuer_name=None, exchange=None,
        security_type=None, figi=None, composite_figi=None,
        resolved_via="unresolved", is_tradeable=False,
    )


async def resolve_cusip_to_ticker_batch(
    cusips: list[str],
    *,
    http_client: Any,
    api_key: str | None = None,
) -> list[CusipTickerResult]:
    """Resolve up to 100 CUSIPs to tickers via OpenFIGI batch API.

    Returns one CusipTickerResult per input CUSIP (same order).
    Never raises — failed/unresolved CUSIPs return resolved_via='unresolved'.

    OpenFIGI response format per CUSIP:
    - Success: {"data": [{"ticker": "AAPL", "exchCode": "US", ...}]}
    - Not found: {"warning": "No identifier found."}
    """
    if len(cusips) > OPENFIGI_BATCH_SIZE:
        raise ValueError(f"Batch size {len(cusips)} exceeds limit {OPENFIGI_BATCH_SIZE}")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key

    payload = [{"idType": "ID_CUSIP", "idValue": cusip} for cusip in cusips]

    try:
        response = await http_client.post(
            OPENFIGI_BATCH_URL,
            json=payload,
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()
        results = response.json()
    except Exception as exc:
        logger.warning("openfigi.batch_failed", error=str(exc), count=len(cusips))
        return [_make_unresolved(c) for c in cusips]

    if not isinstance(results, list) or len(results) != len(cusips):
        logger.warning(
            "openfigi.unexpected_response_length",
            expected=len(cusips),
            got=len(results) if isinstance(results, list) else type(results).__name__,
        )
        return [_make_unresolved(c) for c in cusips]

    output: list[CusipTickerResult] = []
    for cusip, result in zip(cusips, results, strict=True):
        if "data" not in result or not result["data"]:
            output.append(_make_unresolved(cusip))
            continue

        best = result["data"][0]
        ticker = best.get("ticker")
        exchange = best.get("exchCode")
        output.append(CusipTickerResult(
            cusip=cusip,
            ticker=ticker,
            issuer_name=best.get("name"),
            exchange=exchange,
            security_type=best.get("securityType"),
            figi=best.get("figi"),
            composite_figi=best.get("compositeFIGI"),
            resolved_via="openfigi",
            is_tradeable=bool(ticker and exchange in TRADEABLE_EXCHANGES),
        ))

    return output


async def get_current_price_for_cusip(
    cusip: str,
    *,
    db_session_factory: Callable[..., Any],
) -> float | None:
    """Get current market price for a CUSIP via YFinance.

    Resolves CUSIP → ticker from sec_cusip_ticker_map.
    Returns None if CUSIP is not tradeable or YFinance fails.
    Never raises.
    """
    try:
        from sqlalchemy import text as sa_text

        async with db_session_factory() as session:
            result = await session.execute(
                sa_text(
                    "SELECT ticker FROM sec_cusip_ticker_map "
                    "WHERE cusip = :c AND is_tradeable = true"
                ),
                {"c": cusip},
            )
            row = result.fetchone()

        if not row or not row[0]:
            return None

        ticker = row[0]

        def _fetch_price() -> float | None:
            import yfinance as yf
            info = yf.Ticker(ticker).fast_info
            return float(info.get("last_price") or info.get("regularMarketPrice", 0))

        return await asyncio.to_thread(_fetch_price)
    except Exception as exc:
        logger.debug("price_lookup.failed", cusip=cusip, error=str(exc))
        return None


# ── Dedicated SEC Thread Pool ────────────────────────────────────

_sec_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sec-data")


async def run_in_sec_thread(fn: Callable[..., T], *args: Any) -> T:
    """Run a sync function in the dedicated SEC thread pool.

    Gets the event loop at call time to avoid "attached to different loop" errors.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_sec_executor, fn, *args)
