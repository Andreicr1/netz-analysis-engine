"""IAPD XML Feed parser — extracts Form ADV Part 1A structured data.

Parses IA_FIRM_SEC_Feed and IA_FIRM_STATE_Feed XML files into dicts
keyed by CRD number for bulk UPDATE into sec_managers.

Uses iterparse to stream — clears elements after processing to avoid
holding the full DOM in memory (files are ~70 MB).
"""

from __future__ import annotations

import re
from typing import Any
from xml.etree.ElementTree import iterparse

# Fee type mapping: Item 5E attribute → stable key
_FEE_MAP: list[tuple[str, str]] = [
    ("Q5E1", "pct_of_aum"),
    ("Q5E2", "hourly"),
    ("Q5E3", "subscription"),
    ("Q5E4", "fixed"),
    ("Q5E5", "commissions"),
    ("Q5E6", "performance"),
    ("Q5E7", "other"),
]

# Client type mapping: Item 5D code → stable key
_CLIENT_MAP: dict[str, str] = {
    "A": "individuals",
    "B": "hnw_individuals",
    "C": "banks",
    "D": "insurance",
    "E": "investment_companies",
    "F": "pooled_vehicles",
    "G": "pension_plans",
    "H": "charities",
    "I": "state_municipal",
    "J": "other_advisers",
    "K": "corporations",
    "L": "sovereign",
    "M": "other_1",
    "N": "other_2",
}

# Strip common URL prefixes for normalization
_URL_PREFIX_RE = re.compile(r"^https?://", re.IGNORECASE)


def _parse_int_attr(elem: Any, attr: str) -> int | None:
    """Parse an integer from an XML element attribute, returning None on failure."""
    val = elem.get(attr)
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _parse_fee_types(item5e: Any) -> list[str]:
    """Extract fee types from Item5E element attributes."""
    if item5e is None:
        return []
    fees = []
    for attr, label in _FEE_MAP:
        if (item5e.get(attr) or "").upper() == "Y":
            fees.append(label)
    return fees


def _parse_client_types(item5d: Any) -> dict[str, dict[str, int]]:
    """Extract client types from Item5D element attributes."""
    if item5d is None:
        return {}
    clients: dict[str, dict[str, int]] = {}
    for code, name in _CLIENT_MAP.items():
        count_attr = f"Q5D{code}1"
        aum_attr = f"Q5D{code}3"
        count_val = item5d.get(count_attr)
        if count_val is None or count_val == "":
            continue
        try:
            count = int(count_val)
        except (ValueError, TypeError):
            continue
        if count > 0:
            aum_val = item5d.get(aum_attr)
            try:
                aum = int(aum_val) if aum_val else 0
            except (ValueError, TypeError):
                aum = 0
            clients[name] = {"count": count, "aum": aum}
    return clients


def _count_compliance_disclosures(part1a: Any) -> int | None:
    """Count "Y" answers across all Item 11 sub-elements."""
    count = 0
    found_any = False
    for child in part1a:
        tag = child.tag
        if not tag.startswith("Item11"):
            continue
        found_any = True
        for attr_val in child.attrib.values():
            if attr_val.upper() == "Y":
                count += 1
    return count if found_any else None


def _normalize_website(url: str | None) -> str | None:
    """Normalize website URL — lowercase scheme, strip trailing slash."""
    if not url or not url.strip():
        return None
    url = url.strip()
    # Normalize to lowercase for comparison but preserve domain casing
    if url.upper().startswith("HTTP://"):
        url = "http://" + url[7:]
    elif url.upper().startswith("HTTPS://"):
        url = "https://" + url[8:]
    elif not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url.rstrip("/") or None


def _parse_firm(firm_elem: Any) -> dict[str, Any] | None:
    """Parse a single <Firm> element into an enrichment dict."""
    info = firm_elem.find("Info")
    if info is None:
        return None

    crd = (info.get("FirmCrdNb") or "").strip()
    if not crd:
        return None

    # Filing date
    filing = firm_elem.find("Filing")
    filing_date: str | None = None
    if filing is not None:
        filing_date = filing.get("Dt")

    # Form ADV Part 1A
    form_info = firm_elem.find("FormInfo")
    if form_info is None:
        return None
    part1a = form_info.find("Part1A")
    if part1a is None:
        return None

    # Item 1: Website
    website: str | None = None
    item1 = part1a.find("Item1")
    if item1 is not None:
        web_addrs = item1.find("WebAddrs")
        if web_addrs is not None:
            first_addr = web_addrs.find("WebAddr")
            if first_addr is not None and first_addr.text:
                website = _normalize_website(first_addr.text)

    # Item 5D: Client types
    item5d = part1a.find("Item5D")
    client_types = _parse_client_types(item5d)

    # Item 5E: Fee types
    item5e = part1a.find("Item5E")
    fee_types = _parse_fee_types(item5e)

    # Item 5F: AUM breakdown
    item5f = part1a.find("Item5F")
    aum_total: int | None = None
    aum_discretionary: int | None = None
    aum_non_discretionary: int | None = None
    total_accounts: int | None = None
    if item5f is not None:
        aum_total = _parse_int_attr(item5f, "Q5F2C")
        aum_discretionary = _parse_int_attr(item5f, "Q5F2A")
        aum_non_discretionary = _parse_int_attr(item5f, "Q5F2B")
        total_accounts = _parse_int_attr(item5f, "Q5F2F")

    # Item 11: Compliance disclosures
    compliance_disclosures = _count_compliance_disclosures(part1a)

    # Only return if we have at least one non-empty enrichment field
    has_data = any([
        aum_total is not None and aum_total > 0,
        aum_discretionary is not None and aum_discretionary > 0,
        aum_non_discretionary is not None and aum_non_discretionary > 0,
        total_accounts is not None and total_accounts > 0,
        len(fee_types) > 0,
        len(client_types) > 0,
        website is not None,
        compliance_disclosures is not None,
        filing_date is not None,
    ])

    if not has_data:
        return None

    return {
        "crd_number": crd,
        "aum_total": aum_total if aum_total and aum_total > 0 else None,
        "aum_discretionary": aum_discretionary if aum_discretionary and aum_discretionary > 0 else None,
        "aum_non_discretionary": aum_non_discretionary if aum_non_discretionary and aum_non_discretionary > 0 else None,
        "total_accounts": total_accounts if total_accounts and total_accounts > 0 else None,
        "fee_types": fee_types,
        "client_types": client_types,
        "website": website,
        "compliance_disclosures": compliance_disclosures,
        "last_adv_filed_at": filing_date,
    }


def parse_iapd_xml(xml_path: str) -> list[dict[str, Any]]:
    """Parse IAPD XML feed, return list of enrichment dicts.

    Each dict has: crd_number + all mappable fields.
    Only returns firms that have at least one non-empty field to update.
    Uses iterparse to stream — clears elements after processing to avoid
    holding the full DOM in memory.
    """
    results: list[dict[str, Any]] = []

    # iterparse with "end" events — process each <Firm> when fully parsed
    context = iterparse(xml_path, events=("end",))
    for event, elem in context:
        if elem.tag != "Firm":
            continue

        parsed = _parse_firm(elem)
        if parsed is not None:
            results.append(parsed)

        # Free memory — clear the processed element and its children
        elem.clear()

    return results
