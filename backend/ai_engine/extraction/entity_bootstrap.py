"""Entity Bootstrap — Auto-extract fund names, aliases, vehicle entities and roles
from OCR text before the main classification pipeline runs.

Stages:
  A — Mistral OCR (first 10 pages — entity declarations are always early)
  B — text-embedding-3-large filters lines by similarity to canonical phrases
  C — Regex extraction on filtered lines (zero cost, zero LLM)
  D — GPT-4.1-mini fallback only when regex yield < MIN_REGEX_ENTITIES
  E — Deterministic rules validate vehicle_type of top discovered aliases

Public API services:
  - Mistral OCR (public API, MISTRAL_API_KEY)
  - OpenAI GPT-4.1-mini (fallback extraction, OPENAI_API_KEY)
  - OpenAI text-embedding-3-large (line filter, OPENAI_API_KEY)

Usage:
    python entity_bootstrap.py --folder "C:/Deals/Garrington" --dry-run
    python entity_bootstrap.py --folder "C:/Deals/Garrington"
    python entity_bootstrap.py --folder "C:/Deals" --recursive
"""

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from ai_engine.model_config import get_model as _get_model
from ai_engine.openai_client import create_completion, create_embedding

logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

MISTRAL_OCR_URL   = "https://api.mistral.ai/v1/ocr"
MISTRAL_MODEL     = "mistral-ocr-latest"
MISTRAL_MAX_MB    = 250
BOOTSTRAP_PAGES_HEAD = 15   # First N pages — legal docs declare entities upfront (LPA, IM)
BOOTSTRAP_PAGES_TAIL = 10  # Last M pages  — marketing docs put entities at the back
BOOTSTRAP_MAX_PDFS   = 0   # 0 = no limit — process ALL PDFs in the deal folder

EMBEDDING_THRESHOLD      = 0.72
EMBEDDING_TOP_N          = 20

# Cohere Rerank removed — vehicle validation now uses hybrid classifier rules

GPT_MINI_MODEL     = _get_model("classification")
MIN_REGEX_ENTITIES = 3
GPT_MINI_CHARS     = 3000

# ============================================================
# VEHICLE TYPE CANDIDATES — expanded with structured products
# ============================================================

VEHICLE_TYPE_CANDIDATES: dict[str, str] = {
    "standalone_fund": (
        "A single closed-end limited partnership (LP), LLC, exempted company, or fund "
        "vehicle that directly invests in loans, real estate assets, private credit "
        "instruments, or portfolio companies. Standard structure for private credit, "
        "direct lending, real estate credit, or single-strategy funds. Has a commitment "
        "period and investment period. Investors are limited partners or shareholders. "
        "Typically has a General Partner (GP) entity and a Limited Partnership (LP) "
        "entity — the GP entity name often ends in 'GP LP' or 'General Partner LLC' "
        "and is NOT a separate vehicle, it is the governance entity of the same fund. "
        "Examples: 'Declaration Partners Real Estate Fund II LP' with its GP "
        "'Declaration Partners Real Estate Fund II GP LP' is a single standalone_fund. "
        "Blue Owl Real Estate Fund VI LP is a standalone_fund. "
        "Do NOT classify as direct_investment or other solely because a GP entity exists."
    ),
    "feeder_master": (
        "An offshore feeder fund, onshore feeder fund, or parallel vehicle that invests "
        "substantially all of its assets into a master fund. Common structure with a "
        "Cayman Islands offshore feeder and a Delaware onshore feeder both feeding into "
        "a single master partnership. Parallel fund or master-feeder structure."
    ),
    "fund_of_funds": (
        "A fund that allocates capital exclusively to other underlying investment funds "
        "or fund managers. Performs manager selection and portfolio construction across "
        "multiple external fund managers. Multi-manager or FoF structure."
    ),
    "direct_investment": (
        "A deal-level instrument or vehicle for a specific investment in a named company "
        "or asset: credit agreement, term loan, revolving credit facility, or investment "
        "vehicle created specifically for a single transaction. Not a pooled fund."
    ),
    "spv": (
        "Special purpose vehicle (SPV) or special purpose entity (SPE) created for a "
        "specific transaction: CLO, CDO, securitization vehicle, asset-backed securities "
        "issuer, or co-investment SPV. Has Issuer and Co-Issuer roles."
    ),
    "bdc": (
        "Business Development Company (BDC) — a US-registered closed-end investment "
        "company that invests in small and mid-sized businesses. Regulated under the "
        "Investment Company Act of 1940. Trades publicly or operates as a non-traded BDC. "
        "Must distribute at least 90% of taxable income. Examples: Ares Capital, "
        "Jefferies Credit Partners BDC, Blue Owl Capital Corporation."
    ),
    "structured_note": (
        "Structured note, structured product, linked note, or capital markets instrument. "
        "Includes: AMC (Actively Managed Certificate), tracker certificate, participation "
        "note, credit-linked note (CLN), equity-linked note (ELN), total return note, "
        "or other certificated structured product issued by a bank or financial institution. "
        "Traded on an exchange or issued over-the-counter. Has an ISIN or WKN identifier. "
        "Underlying exposure managed by an investment manager under a mandate."
    ),
    "dac": (
        "Dedicated Investment Company (DAC) or Designated Activity Company — an Irish "
        "special purpose vehicle used for structured finance, securitization, or asset "
        "holding. Regulated under Irish company law. Often used as issuer vehicle for "
        "European structured products, CLOs, or asset-backed securities."
    ),
    "amc": (
        "Actively Managed Certificate (AMC) — a structured product issued typically by "
        "a Swiss or European bank, referencing a dynamically managed portfolio. The "
        "investment manager adjusts the underlying portfolio within defined parameters. "
        "Certificated format, traded OTC or on exchange. Common in Swiss private banking "
        "as an alternative to fund structures for smaller AUM or faster launch timelines."
    ),
    "separately_managed_account": (
        "Separately managed account (SMA), managed account, or discretionary mandate "
        "for a single institutional investor. Not a pooled vehicle. Assets held directly "
        "by the investor with the manager acting under an investment management agreement."
    ),
    "other": (
        "Vehicle type cannot be determined from the document, or the document does not "
        "describe a specific investment vehicle."
    ),
}

# ============================================================
# CANONICAL ENTITY PHRASES — for embedding similarity filter
# ============================================================

_CANONICAL_ENTITY_PHRASES = [
    # ── Entity declarations ──
    "Investment Manager of the Fund",
    "Fund Administrator of the Fund",
    "as its General Partner",
    "formerly known as",
    "hereinafter referred to as",
    "a Cayman Islands exempted company",
    "a Delaware limited partnership",
    "a Cayman Islands exempted limited partnership",
    "registered office of the Fund",
    "the Sponsor of the Fund",
    "appointed as Investment Manager",
    "acting as Fund Administrator",
    "legal counsel to the Fund",
    "auditors of the Fund",
    "custodian of the Fund",
    # ── Fund structure ──
    "feeder fund investing into",
    "invests substantially all of its assets",
    "offshore feeder fund",
    "onshore feeder fund",
    "US Blocker",
    "parallel fund vehicle",
    "investment advisory agreement",
    "management agreement between",
    "organized under the laws of",
    "incorporated in the Cayman Islands",
    # ── Structured products ──
    "Business Development Company",
    "Actively Managed Certificate",
    "Dedicated Investment Company",
    "Designated Activity Company",
    "structured note issued by",
    "certificate issued under",
    "ISIN",
    "the Issuer",
    "the Co-Issuer",
    "asset-backed securities",
    "credit-linked note",
    # ── Strategy & sector ──
    "private credit strategy",
    "direct lending fund",
    "bridge lending program",
    "senior secured loans",
    "real estate credit fund",
    "net lease strategy",
    "credit opportunities fund",
    "tactical credit fund",
    # ── Key financial terms ──
    "management fee of the Fund",
    "incentive fee or performance allocation",
    "hurdle rate or preferred return",
    "carried interest of twenty percent",
    "minimum investment commitment",
    "lock-up period of the Fund",
    "redemption notice period",
]

# ============================================================
# FILENAME HINTS — vehicle_type signals from filename
# ============================================================

_FILENAME_VEHICLE_HINTS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\bBDC\b", re.IGNORECASE),
     "bdc", "Filename contains 'BDC' — likely Business Development Company"),
    (re.compile(r"\bAMC\b", re.IGNORECASE),
     "amc", "Filename contains 'AMC' — likely Actively Managed Certificate"),
    (re.compile(r"\bDAC\b", re.IGNORECASE),
     "dac", "Filename contains 'DAC' — likely Dedicated Activity Company"),
    (re.compile(r"structured.note|linked.note|credit.linked|CLN|ELN", re.IGNORECASE),
     "structured_note", "Filename suggests structured note product"),
    (re.compile(r"certificate|certificat", re.IGNORECASE),
     "structured_note", "Filename contains 'certificate' — likely structured product"),
    (re.compile(r"feeder|offshore.fund|onshore.fund", re.IGNORECASE),
     "feeder_master", "Filename suggests feeder/master structure"),
    (re.compile(r"\bSPV\b|\bSPE\b|\bCLO\b|\bCDO\b", re.IGNORECASE),
     "spv", "Filename contains SPV/CLO/CDO — likely special purpose vehicle"),
    (re.compile(r"\bLPA\b|limited.partnership.agreement", re.IGNORECASE),
     "standalone_fund", "Filename contains LPA — constitutional document of standalone fund"),
    (re.compile(r"master.fund|master.partnership", re.IGNORECASE),
     "feeder_master", "Filename contains 'master fund' — feeder/master structure"),
    (re.compile(r"separately.managed|SMA\b", re.IGNORECASE),
     "separately_managed_account", "Filename suggests separately managed account"),
]


def filename_vehicle_hint(filename: str) -> tuple[str | None, str | None]:
    for pattern, vehicle, reason in _FILENAME_VEHICLE_HINTS:
        if pattern.search(filename):
            return vehicle, reason
    return None, None


# ============================================================
# REGEX PATTERNS — extract aliases from OCR text
# ============================================================

_P_ALIAS_QUOTED = re.compile(
    r'([A-Z][A-Za-z0-9\s\-&\.]{5,80}?)\s*\((?:the\s+)?["\u2018\u2019\u201c\u201d]'
    r'([A-Z][A-Za-z0-9\s\-]{2,40})["\u2018\u2019\u201c\u201d]\s*\)',
)

# Pattern 1b — parenthesized acronym WITHOUT quotes:  "Trust (ORENT)", "Fund VI (BOREP)"
_P_ALIAS_PAREN = re.compile(
    r"([A-Z][A-Za-z0-9\s\-&\.]{8,80}?)"
    r"\s*\(\s*([A-Z][A-Z0-9]{2,10})\s*\)",
)

_P_ACRONYM_ENTITY = re.compile(
    r"\b([A-Z]{2,8}(?:\s+[IVX]{1,4})?)\b"
    r"(?:\s*,)?\s+(?:is\s+)?a(?:n)?\s+"
    r"(?:Cayman|Delaware|Irish|Luxembourg|limited|exempted|offshore|onshore|registered)",
    re.IGNORECASE,
)

_P_FORMERLY = re.compile(
    r'formerly\s+known\s+as\s+["\u201c]?([A-Z][A-Za-z0-9\s\-&\.]{3,80}?)["\u201d]?'
    r'(?:\s*\.|,|\band\b|$)',
    re.IGNORECASE,
)

_P_TITLE_HEADER = re.compile(
    r"^#{1,3}\s+([A-Z][A-Za-z0-9\s\-&\.]{5,80}?)(?:\s+[—\-–]|\s+Fund\b|\s+LP\b"
    r"|\s+LLC\b|\s+BDC\b|\s+AMC\b|\s+DAC\b|\s+Certificate\b)",
    re.MULTILINE,
)

_P_ROLE_DECL = re.compile(
    r"([A-Z][A-Za-z0-9\s\-&\.\(\)]{3,60}?)\s+as\s+(?:its\s+)?"
    r"(Investment Manager|Fund Administrator|Administrator|Auditor|"
    r"Legal Counsel|Custodian|Sponsor|General Partner|GP|Manager|"
    r"Issuer|Co-Issuer|Arranger|Calculation Agent|Collateral Manager)",
    re.IGNORECASE,
)

# Pattern 5b — key persons: "Name, Title" or "Name — Title" or "Title: Name"
_P_KEY_PERSON = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]{2,})"  # "John D. Smith"
    r"\s*[,\u2014\u2013\-|]\s*"
    r"(Chief\s+\w+\s*\w*|C[EFIOST]O|President|Vice\s+President|"
    r"Managing\s+(?:Partner|Director|Member|Principal)|"
    r"Senior\s+(?:Partner|Director|Vice\s+President|Managing\s+Director)|"
    r"Portfolio\s+Manager|Fund\s+Manager|Head\s+of\s+\w+|"
    r"General\s+Counsel|Partner|Director|Principal|Founder|"
    r"Co-Founder|Chairman|Chairwoman|Treasurer|Secretary)",
    re.IGNORECASE,
)

_P_ISIN = re.compile(r"\bISIN\s*:?\s*([A-Z]{2}[A-Z0-9]{10})\b")
_P_WKN  = re.compile(r"\bWKN\s*:?\s*([A-Z0-9]{6})\b")

_SKIP_ENTITIES = re.compile(
    r"^(the Fund|the Manager|the Company|the Partnership|the Trust|"
    r"the General Partner|the Limited Partner|the Investor|"
    r"the Administrator|this Agreement|the Agreement|"
    r"Class A|Class B|Series [A-Z])$",
    re.IGNORECASE,
)

# Filter alias VALUES that are clearly not entity names.
# Catches: form field labels, multi-line strings, generic financial terms.
_SKIP_ALIAS_VALUES = re.compile(
    r"\n"                                              # multi-line = form field or fragment
    r"|Beneficiary|Bank\s+Name|Bank\s+Account"        # wire instruction fields
    r"|will\s+apply|net\s+asset\s+value"              # sentence fragments
    r"|hereinafter|pursuant\s+to"                     # legal boilerplate fragments
    # Values that start with articles, pronouns, or verbs — not entity names
    r"|^(This\s+material|This\s+document|This\s+fund"
    r"|The\s+Fund|The\s+Manager|The\s+Company"
    r"|We\s+have|We\s+are|It\s+is|There\s+is"
    r"|U\.S\.\s+tax|Internal\s+Revenue|Cayman\s+Special"
    r"|Canadian\s+generally|International\s+Financial"
    r"|Combating\s+the|Focused\s+on|Subject\s+to"
    r"|August|January|February|March|April|May|June"
    r"|July|September|October|November|December)"
    # Generic standalone terms
    r"|^\s*(Company|Fund|Manager|Partner|Investor"
    r"|Units|Shares|Class|Series|Notes|Certificates"
    r"|Distribution|Distributions|Participant"
    r"|Agreement|Instrument|Schedule|Annex)\s*$",
    re.IGNORECASE,
)

# Filter alias KEYS that are generic financial abbreviations with no entity meaning.
_SKIP_ALIAS_KEYS = re.compile(
    r"^(NAV|IRR|MOIC|AUM|LP|GP|LLC|LPA|SPV|NDA|MFN|PPM|SMA"
    r"|DRIP|DTC|AML|KYC|FATCA|CRS|ERISA|QPAM|FINRA|SEC|CIMA"
    r"|USD|EUR|GBP|BRL|CHF|JPY|YTD|QTD|MTD"
    r"|Q1|Q2|Q3|Q4|H1|H2|FY"
    r"|CEO|CFO|CIO|COO|MD|VP|SVP|EVP"
    # Regulatory / compliance / accounting standards — not entity names
    r"|IFRS|GAAP|GAAS|PCAOB|FASB|IASB|CPA|CFA|CAIA|IMC|ACCA"
    r"|CFT|AMLCO|MLRO|DMLRO|FATF|GDPR|LGPD|OFAC|FinCEN"
    r"|IRC|IRS|HMRC|CRA|OECD|BASEL|SOLVENCY"
    # Legal / structural terms — not entity names
    r"|SPE|CLO|CDO|CDX|CDS|MBS|ABS|RMBS|CMBS"
    r"|PLC|AG|BV|NV|GmbH|SARL|SAS|SRL"
    # Generic document labels
    r"|DRAFT|FINAL|APPENDIX|SCHEDULE|EXHIBIT|ANNEX|ADDENDUM)$"
    r"|^[A-Z]{10,}$",  # concatenated names without spaces e.g. CHICAGOATLANTIC
    re.IGNORECASE,
)

# ============================================================
# REGEX EXTRACTION
# ============================================================

def extract_entities_regex(text: str, filename: str = "") -> dict:
    discovered = {
        "aliases":             {},
        "formerly":            [],
        "roles":               {},
        "titles":              [],
        "isins":               [],
        "vehicle_hint":        None,
        "vehicle_hint_reason": None,
    }

    # Filename hints
    vh, vr = filename_vehicle_hint(filename)
    if vh:
        discovered["vehicle_hint"] = vh
        discovered["vehicle_hint_reason"] = vr

    # Pattern 1 — quoted aliases
    for m in _P_ALIAS_QUOTED.finditer(text):
        full  = m.group(1).strip()
        alias = m.group(2).strip()
        if (not _SKIP_ENTITIES.match(alias)
                and not _SKIP_ENTITIES.match(full)
                and not _SKIP_ALIAS_KEYS.match(alias)
                and not _SKIP_ALIAS_VALUES.search(full)
                and len(full) >= 8):
            discovered["aliases"][alias] = full

    # Pattern 1b — parenthesized acronym without quotes
    for m in _P_ALIAS_PAREN.finditer(text):
        full  = m.group(1).strip()
        alias = m.group(2).strip()
        if (not _SKIP_ENTITIES.match(alias)
                and not _SKIP_ENTITIES.match(full)
                and not _SKIP_ALIAS_KEYS.match(alias)
                and not _SKIP_ALIAS_VALUES.search(full)
                and len(full) >= 10):
            discovered["aliases"][alias] = full

    # Pattern 2 — acronym + entity type
    for m in _P_ACRONYM_ENTITY.finditer(text):
        acronym = m.group(1).strip()
        if (not _SKIP_ENTITIES.match(acronym)
                and not _SKIP_ALIAS_KEYS.match(acronym)
                and len(acronym) >= 2):
            pos   = m.start()
            ctx   = text[max(0, pos - 200):pos].strip()
            names = re.findall(
                r"[A-Z][A-Za-z0-9\s\-&\.]{5,60}"
                r"(?:Fund|LP|LLC|SA|Ltd\.?|BDC|AMC|DAC|Certificate)",
                ctx,
            )
            full = names[-1].strip() if names else acronym
            discovered["aliases"][acronym] = full

    # Pattern 3 — formerly known as
    for m in _P_FORMERLY.finditer(text):
        name = m.group(1).strip()
        if not _SKIP_ENTITIES.match(name):
            discovered["formerly"].append(name)

    # Pattern 4 — title headers
    for m in _P_TITLE_HEADER.finditer(text):
        name = m.group(1).strip()
        if not _SKIP_ENTITIES.match(name) and len(name) > 8:
            discovered["titles"].append(name)

    # Pattern 5 — role declarations (entity as Role)
    for m in _P_ROLE_DECL.finditer(text):
        entity = m.group(1).strip()
        role   = m.group(2).strip()
        if not _SKIP_ENTITIES.match(entity):
            discovered["roles"][entity] = role

    # Pattern 5b — key persons (Name, Title)
    for m in _P_KEY_PERSON.finditer(text):
        person = m.group(1).strip()
        title  = m.group(2).strip()
        if len(person) >= 5 and person not in discovered["roles"]:
            discovered["roles"][person] = title

    # Pattern 6 — ISIN / WKN (structured products)
    for m in _P_ISIN.finditer(text):
        discovered["isins"].append({"type": "ISIN", "value": m.group(1)})
    for m in _P_WKN.finditer(text):
        discovered["isins"].append({"type": "WKN",  "value": m.group(1)})

    return discovered


# ============================================================
# FUND METADATA EXTRACTION — strategy, jurisdiction, key terms
# Zero API cost — regex on full OCR text already collected.
# These fields enrich fund_context.json and flow into chunk
# metadata, improving downstream search quality.
# ============================================================

_P_STRATEGY = re.compile(
    r"\b(private\s+credit|direct\s+lending|bridge\s+lending|bridge\s+loans?"
    r"|senior\s+secured\s+(?:loans?|lending)|mezzanine\s+(?:lending|debt|finance)"
    r"|asset[- ]based\s+lending|real\s+estate\s+(?:credit|debt|equity|income)"
    r"|net\s+lease|triple\s+net\s+lease|credit\s+opportunities"
    r"|tactical\s+credit|opportunistic\s+credit|multi[- ]strategy"
    r"|transitional\s+(?:lending|loans?)|construction\s+(?:lending|loans?)"
    r"|commercial\s+real\s+estate|residential\s+mortgage"
    r"|distressed\s+(?:credit|debt)|special\s+situations"
    r"|structured\s+credit|venture\s+(?:lending|debt)"
    r"|cannabis\s+(?:lending|credit)|healthcare\s+(?:lending|credit)"
    r"|first\s+lien|second\s+lien|unitranche|revolving\s+credit"
    r"|private\s+lending|workforce\s+housing|affordable\s+housing"
    r"|multifamily|industrial|logistics|life\s+sciences|hospitality"
    r"|trade\s+finance|factoring|invoice\s+finance|equipment\s+(?:finance|leasing)"
    r"|infrastructure\s+(?:debt|lending)|project\s+finance"
    r"|corporate\s+(?:lending|credit)|leveraged\s+(?:lending|loans?|finance))\b",
    re.IGNORECASE,
)

_P_JURISDICTION = re.compile(
    r"(?:organized|incorporated|formed|established|registered|domiciled)"
    r"\s+(?:under\s+the\s+laws?\s+of\s+|in\s+)"
    r"(?:the\s+)?(Cayman\s+Islands?|Delaware|Ireland|Luxembourg|Jersey"
    r"|Guernsey|British\s+Virgin\s+Islands?|BVI|Bermuda|Netherlands"
    r"|Hong\s+Kong|Singapore|Switzerland|United\s+Kingdom"
    r"|England(?:\s+and\s+Wales)?|State\s+of\s+Delaware"
    r"|State\s+of\s+New\s+York|Marshall\s+Islands)",
    re.IGNORECASE,
)

_P_JURISDICTION_ENTITY = re.compile(
    r"a\s+(Cayman\s+Islands?|Delaware|Ireland|Luxembourg|Jersey"
    r"|Guernsey|British\s+Virgin\s+Islands?|BVI|Bermuda|Netherlands"
    r"|Hong\s+Kong|Singapore|Switzerland|United\s+Kingdom"
    r"|England(?:\s+and\s+Wales)?)\s+"
    r"(?:exempted\s+)?(?:limited\s+partnership|limited\s+liability\s+company"
    r"|company|LLC|corporation|exempted\s+company)",
    re.IGNORECASE,
)

_P_MGMT_FEE = re.compile(
    r"management\s+fee[^.]{0,50}?(\d+\.?\d*)\s*%",
    re.IGNORECASE,
)

_P_PERF_FEE = re.compile(
    r"(?:incentive|performance|carried\s+interest)\s+"
    r"(?:fee|allocation)[^.]{0,50}?(\d+\.?\d*)\s*%",
    re.IGNORECASE,
)

_P_HURDLE = re.compile(
    r"(?:hurdle\s+rate|preferred\s+return|pref(?:erred)?\s*\.?\s*ret)"
    r"[^.]{0,50}?(\d+\.?\d*)\s*%",
    re.IGNORECASE,
)

_P_LOCKUP = re.compile(
    r"(?:lock[- ]?up|minimum\s+hold(?:ing)?\s+period"
    r"|minimum\s+investment\s+period)[^.\n]{0,60}?"
    r"(\d+)\s*[- ]?\s*(year|month|quarter)",
    re.IGNORECASE,
)

_P_FUND_SIZE = re.compile(
    r"(?:target\s+(?:fund\s+)?size|fund\s+size)"
    r"[^.\n]{0,60}?\$?\s*(\d[\d,.]*)\s*(million|billion|mn|bn|MM|M\b|B\b)",
    re.IGNORECASE,
)

# Ranges for sanity-checking extracted percentages
_RANGE_MGMT_FEE  = (0.05, 5.0)   # 0.05% – 5%
_RANGE_PERF_FEE  = (1.0, 50.0)   # 1% – 50%
_RANGE_HURDLE    = (1.0, 20.0)   # 1% – 20%
_RANGE_FUND_SIZE_M = (1, 50_000)  # $1M – $50B expressed in millions
_RANGE_FUND_SIZE_B = (0.01, 50)   # $0.01B – $50B expressed in billions


def _first_pct_in_range(
    pattern: re.Pattern, text: str, lo: float, hi: float,
) -> str | None:
    """Iterate *all* regex matches; return first value within [lo, hi]."""
    for m in pattern.finditer(text):
        try:
            val = float(m.group(1))
        except ValueError:
            continue
        if lo <= val <= hi:
            return m.group(1)
    return None


def extract_fund_metadata(ocr_text: str) -> dict:
    """Extract structured fund metadata from full OCR text.
    Returns dict with: fund_strategy, fund_jurisdiction, key_terms.
    All regex-based, zero API cost.
    """
    meta: dict = {}

    # ── Strategy keywords (deduped, normalized) ──
    strategies: list[str] = []
    seen_lower: set[str] = set()
    for m in _P_STRATEGY.finditer(ocr_text):
        s = re.sub(r"\s+", " ", m.group(1).strip().lower())
        if s not in seen_lower:
            seen_lower.add(s)
            strategies.append(s)
    if strategies:
        meta["fund_strategy"] = strategies

    # ── Jurisdiction (first reliable match wins) ──
    for pat in (_P_JURISDICTION, _P_JURISDICTION_ENTITY):
        m = pat.search(ocr_text)
        if m:
            jur = re.sub(r"\s+", " ", m.group(1).strip())
            # Normalize common variants
            jur_map = {
                "State of Delaware": "Delaware",
                "State of New York": "New York",
                "BVI": "British Virgin Islands",
                "England and Wales": "United Kingdom",
                "England": "United Kingdom",
                "Cayman Island": "Cayman Islands",
            }
            meta["fund_jurisdiction"] = jur_map.get(jur, jur)
            break

    # ── Key financial terms (finditer + range validation) ──
    key_terms: dict[str, str] = {}

    v = _first_pct_in_range(_P_MGMT_FEE, ocr_text, *_RANGE_MGMT_FEE)
    if v:
        key_terms["management_fee"] = f"{v}%"

    v = _first_pct_in_range(_P_PERF_FEE, ocr_text, *_RANGE_PERF_FEE)
    if v:
        key_terms["performance_fee"] = f"{v}%"

    v = _first_pct_in_range(_P_HURDLE, ocr_text, *_RANGE_HURDLE)
    if v:
        key_terms["hurdle_rate"] = f"{v}%"

    m = _P_LOCKUP.search(ocr_text)
    if m:
        key_terms["lock_up"] = f"{m.group(1)} {m.group(2).lower()}s"

    # Fund size: iterate matches, validate by unit range
    unit_map = {"mn": "million", "mm": "million", "m": "million",
                "bn": "billion", "b": "billion"}
    for m in _P_FUND_SIZE.finditer(ocr_text):
        try:
            amount = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = m.group(2).lower()
        is_billion = unit in ("billion", "bn", "b")
        lo, hi = _RANGE_FUND_SIZE_B if is_billion else _RANGE_FUND_SIZE_M
        if lo <= amount <= hi:
            amt_str = m.group(1).replace(",", "")
            key_terms["fund_size"] = f"${amt_str} {unit_map.get(unit, unit)}"
            break

    if key_terms:
        meta["key_terms"] = key_terms

    return meta


# ============================================================
# EMBEDDING FILTER
# ============================================================

def cosine_similarity(a: list[float], b: list[float]) -> float:
    import numpy as np  # lazy import - heavy optional dependency

    a_arr, b_arr = np.array(a), np.array(b)
    return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr) + 1e-9))


def filter_lines_by_embedding(ocr_text: str) -> str:
    """Embed each OCR line and return the top N lines most similar
    to canonical entity declaration phrases.
    Focuses regex and GPT extraction on entity-bearing content only.
    """
    lines = [line.strip() for line in ocr_text.split("\n") if len(line.strip()) >= 15]
    if not lines:
        return ocr_text[:GPT_MINI_CHARS]

    all_texts = lines + _CANONICAL_ENTITY_PHRASES
    try:
        result = create_embedding(inputs=all_texts)
    except Exception as e:
        logger.warning("embedding failed (%s), using raw text", e)
        return ocr_text[:GPT_MINI_CHARS]

    embeddings           = result.vectors
    line_embeddings      = embeddings[:len(lines)]
    canonical_embeddings = embeddings[len(lines):]

    scored = []
    for i, line_emb in enumerate(line_embeddings):
        max_sim = max(
            cosine_similarity(line_emb, ce)
            for ce in canonical_embeddings
        )
        scored.append((max_sim, lines[i]))

    filtered = [
        line for score, line in
        sorted(scored, reverse=True)[:EMBEDDING_TOP_N]
        if score >= EMBEDDING_THRESHOLD
    ]

    if not filtered:
        return ocr_text[:GPT_MINI_CHARS]

    logger.info("emb:%d->%d", len(lines), len(filtered))
    return "\n".join(filtered)


# ============================================================
# GPT-4.1-MINI FALLBACK
# ============================================================

def _get_entity_gpt_system() -> str:
    from ai_engine.prompts import prompt_registry
    return prompt_registry.render("extraction/entity_gpt.j2")


def extract_entities_gpt(text: str) -> dict:
    try:
        result = create_completion(
            system_prompt=_get_entity_gpt_system(),
            user_prompt=f"Document text:\n\n{text[:GPT_MINI_CHARS]}",
            model=_get_model("extraction"),
            temperature=0.0,
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        content = result.text
        if "<think>" in content:
            content = content.split("</think>")[-1].strip()
        return json.loads(content)
    except Exception as e:
        logger.warning("GPT mini failed (%s)", e)
        return {}


# ============================================================
# VEHICLE TYPE VALIDATION — deterministic (replaced Cohere Rerank)
# ============================================================

# Map entity_bootstrap expanded types → canonical 6 types
_VEHICLE_TYPE_CANONICAL_MAP: dict[str, str] = {
    "standalone_fund": "standalone_fund",
    "feeder_master": "feeder_master",
    "fund_of_funds": "fund_of_funds",
    "direct_investment": "direct_investment",
    "spv": "spv",
    "bdc": "standalone_fund",
    "structured_note": "spv",
    "dac": "spv",
    "amc": "spv",
    "separately_managed_account": "other",
    "other": "other",
}


def validate_vehicle_type(
    entity_name: str,
    context_text: str,
    filename: str = "",
) -> tuple[str, float]:
    """Validate vehicle_type of a discovered entity using deterministic rules.

    Replaces Cohere Rerank with the hybrid classifier's Layer 1 vehicle
    heuristics (regex rules ported from prepare_pdfs_full.py).
    No API calls — pure Python, zero cost.
    """
    from ai_engine.classification.hybrid_classifier import _classify_vehicle_rules

    # Use hybrid classifier's vehicle rules (Layer 1 heuristics)
    text = f"Entity: {entity_name}\n\n{context_text[:5000]}"
    vehicle = _classify_vehicle_rules(filename, text)

    if vehicle is not None:
        return vehicle, 0.85  # High confidence for deterministic match

    # Fallback: check against entity_bootstrap's expanded VEHICLE_TYPE_CANDIDATES
    # using simple keyword matching
    corpus = (entity_name + " " + context_text[:2000]).lower()
    for vtype in VEHICLE_TYPE_CANDIDATES:
        if vtype == "other":
            continue
        # Check if vehicle type name keywords appear in corpus
        keywords = vtype.replace("_", " ")
        if keywords in corpus:
            canonical = _VEHICLE_TYPE_CANONICAL_MAP.get(vtype, "other")
            return canonical, 0.70

    return "other", 0.0


# ============================================================
# MISTRAL OCR
# ============================================================

def ocr_pdf_bootstrap(pdf_path: str, mistral_key: str) -> str:
    """OCR the HEAD + TAIL pages of the PDF.

    HEAD (first BOOTSTRAP_PAGES_HEAD pages) captures entity declarations in
    legal documents (LPA, IM, subscription agreements).
    TAIL (last BOOTSTRAP_PAGES_TAIL pages) captures service provider credits,
    fund structure diagrams and legal disclaimers in marketing materials.

    For short documents (≤ HEAD+TAIL pages) the whole document is sent.
    Pages are deduped so overlap never causes double-billing.
    """
    import fitz  # lazy import - heavy optional dependency
    import requests  # lazy import - optional dependency

    doc   = fitz.open(pdf_path)
    total = len(doc)

    # Build deduped ordered page list: first HEAD + last TAIL (no overlap)
    head_end  = min(BOOTSTRAP_PAGES_HEAD, total)
    tail_start = max(head_end, total - BOOTSTRAP_PAGES_TAIL)
    page_indices = list(range(head_end)) + list(range(tail_start, total))
    # page_indices is already sorted and deduped by construction

    out = fitz.open()
    for i in page_indices:
        out.insert_pdf(doc, from_page=i, to_page=i)
    data = out.tobytes()
    out.close()
    doc.close()

    if len(data) / (1024 * 1024) > MISTRAL_MAX_MB:
        return ""

    b64     = base64.b64encode(data).decode()
    payload = {
        "model":    MISTRAL_MODEL,
        "document": {
            "type":         "document_url",
            "document_url": f"data:application/pdf;base64,{b64}",
        },
        "include_image_base64": False,
        "table_format":         "html",
    }

    resp = requests.post(
        MISTRAL_OCR_URL,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {mistral_key}",
        },
        json=payload,
        timeout=60,
    )

    if resp.status_code != 200:
        return ""

    data_r  = resp.json()
    pages_r = data_r.get("pages", [])
    if pages_r:
        parts: list[str] = []
        for p in pages_r:
            md = p.get("markdown", "") or ""
            # Replace [tbl-X.html](tbl-X.html) placeholders with real HTML content
            for tbl in p.get("tables", []):
                tbl_id  = tbl.get("id", "")
                content = tbl.get("content", "")
                if tbl_id and content:
                    md = md.replace(f"[{tbl_id}]({tbl_id})", content)
            parts.append(md)
        return "\n\n".join(parts)
    return data_r.get("text", "")


# ============================================================
# MERGE + DEDUP
# ============================================================

def merge_discoveries(results: list[dict]) -> dict:
    merged = {
        "aliases":       {},
        "formerly":      [],
        "roles":         {},
        "titles":        [],
        "isins":         [],
        "vehicle_hints": [],
    }
    alias_count: dict[str, int] = {}

    for r in results:
        for alias, full in r.get("aliases", {}).items():
            # Normalize key to uppercase for dedup
            alias_normalized = alias.strip().upper()
            # Skip generic keys
            if _SKIP_ALIAS_KEYS.match(alias_normalized):
                continue
            # Skip noise values
            if _SKIP_ALIAS_VALUES.search(str(full).strip()):
                continue
            # Skip if value is too short or same as key
            if len(str(full).strip()) < 8:
                continue
            if alias_normalized == str(full).strip().upper():
                continue
            # Keep BEST full_name: prefer names containing fund-like suffixes
            # over generic company names (e.g. prefer "Blue Owl RE Fund VI" over
            # "Blue Owl Capital Inc.") — when both map to same alias key.
            if alias_normalized in merged["aliases"]:
                existing = merged["aliases"][alias_normalized]
                _FUND_SUFFIX = re.compile(
                    r"Fund|Trust|Partners|LP\b|LLC\b|Capital Fund", re.IGNORECASE)
                new_is_fund = bool(_FUND_SUFFIX.search(str(full)))
                old_is_fund = bool(_FUND_SUFFIX.search(existing))
                # Prefer fund-like name; if both or neither, keep longest
                if (new_is_fund and not old_is_fund) or \
                   (new_is_fund == old_is_fund and len(str(full)) > len(existing)):
                    merged["aliases"][alias_normalized] = str(full).strip()
            else:
                merged["aliases"][alias_normalized] = str(full).strip()
            alias_count[alias_normalized] = alias_count.get(alias_normalized, 0) + 1

        for name in r.get("formerly", []) + r.get("formerly_known_as", []):
            if name not in merged["formerly"]:
                merged["formerly"].append(name)

        for entity, role in r.get("roles", {}).items():
            if entity not in merged["roles"]:
                merged["roles"][entity] = role

        for title in r.get("titles", []) + r.get("fund_names", []):
            if title not in merged["titles"]:
                merged["titles"].append(title)

        for isin in r.get("isins", []):
            if isin not in merged["isins"]:
                merged["isins"].append(isin)

        if r.get("vehicle_hint"):
            hint = {"vehicle": r["vehicle_hint"], "reason": r.get("vehicle_hint_reason", "")}
            if hint not in merged["vehicle_hints"]:
                merged["vehicle_hints"].append(hint)

        if r.get("vehicle_type_hint"):
            hint = {"vehicle": r["vehicle_type_hint"], "reason": "gpt_mini"}
            if hint not in merged["vehicle_hints"]:
                merged["vehicle_hints"].append(hint)

    # Promote GPT fund_names to aliases when a suitable alias key exists.
    # Example: fund_names=["Blue Owl Real Estate Fund VI"] + alias BLUE OWL
    # exists but maps to the manager -> promote the fund name as better value.
    _FUND_SUFFIX_PROMO = re.compile(
        r"Fund|Trust|Partners|LP\b|LLC\b|Capital Fund", re.IGNORECASE)
    for title in merged["titles"]:
        # Derive a candidate alias key from the title (first 2-3 uppercase words)
        words = title.split()
        candidate_keys = []
        if len(words) >= 2:
            candidate_keys.append(" ".join(words[:2]).upper())
        if len(words) >= 3:
            candidate_keys.append(" ".join(words[:3]).upper())
        # Also try single first word (>= 3 chars)
        if words and len(words[0]) >= 3:
            candidate_keys.append(words[0].upper())

        for ck in candidate_keys:
            if ck in merged["aliases"]:
                existing = merged["aliases"][ck]
                if (_FUND_SUFFIX_PROMO.search(title) and not _FUND_SUFFIX_PROMO.search(existing)) or (_FUND_SUFFIX_PROMO.search(title) and len(title) > len(existing)):
                    merged["aliases"][ck] = title
                    break

    # Sort aliases by frequency (most-seen first)
    merged["aliases"] = dict(
        sorted(merged["aliases"].items(),
               key=lambda x: alias_count.get(x[0], 0),
               reverse=True),
    )
    return merged


# ============================================================
# FUND_CONTEXT.JSON
# ============================================================

def load_seed(folder: Path) -> dict:
    ctx_path = folder / "fund_context.json"
    if ctx_path.exists():
        with open(ctx_path, encoding="utf-8") as f:
            return json.load(f)
    return {
        "fund_id":   folder.name.lower().replace(" ", "_"),
        "deal_name": folder.name,
        "fund_name": folder.name,
        "aliases":   [],
    }


def write_enriched(folder: Path, seed: dict, discovered: dict,
                   validated_vehicles: dict, fund_meta: dict,
                   dry_run: bool) -> None:
    # deal_name = folder name (always stable, user-controlled)
    seed["deal_name"]          = folder.name
    seed["discovered_aliases"] = discovered["aliases"]
    seed["validated_vehicles"] = validated_vehicles
    seed["bootstrap_version"]  = "3.0"

    # ── Fund metadata (strategy, jurisdiction, key terms) ──
    # Always overwrite to clear stale values from previous runs
    if fund_meta.get("fund_strategy"):
        seed["fund_strategy"] = fund_meta["fund_strategy"]
    elif "fund_strategy" in seed:
        del seed["fund_strategy"]
    if fund_meta.get("fund_jurisdiction"):
        seed["fund_jurisdiction"] = fund_meta["fund_jurisdiction"]
    elif "fund_jurisdiction" in seed:
        del seed["fund_jurisdiction"]
    if fund_meta.get("key_terms"):
        seed["key_terms"] = fund_meta["key_terms"]
    elif "key_terms" in seed:
        del seed["key_terms"]

    if discovered["formerly"]:
        seed["formerly_known_as"] = discovered["formerly"]

    if discovered["isins"]:
        seed["isins"] = discovered["isins"]

    if discovered["vehicle_hints"]:
        seed["vehicle_hints"] = discovered["vehicle_hints"]

    if discovered["roles"]:
        if "entities" not in seed:
            seed["entities"] = {}
        for entity, role in discovered["roles"].items():
            key = role.lower().replace(" ", "_")
            if key not in seed["entities"]:
                seed["entities"][key] = {
                    "name":   entity,
                    "role":   role,
                    "source": "bootstrap",
                }

    new_titles = [
        t for t in discovered["titles"]
        if t not in set(seed.get("aliases", []) + list(discovered["aliases"].values()))
    ]
    _NOISE_TITLE = re.compile(
        r"\n"                          # multi-line fragments
        r"|^(Historically|Currently|Executive\s+Summary"
        r"|Confidential|Proprietary|For\s+Institutional"
        r"|Advantages|Focused\s+on|Strategies\s+have"
        r"|Easy\s+to|This\s+material|August|September"
        r"|January|February|March|April|May|June|July"
        r"|October|November|December)",
        re.IGNORECASE,
    )
    clean_titles = [
        t for t in new_titles
        if not _NOISE_TITLE.search(t) and len(t) >= 10
    ]
    if clean_titles:
        seed["candidate_fund_names"] = clean_titles

    # ---- Fund name / fund_id alignment ----
    # fund_name and fund_id MUST match deal_name (= folder.name) so the
    # retrieval system can scope chunks correctly.  The entity-discovered
    # "fund" name (e.g. "Next Edge Capital Corp.") is often the parent
    # company or oversight entity, NOT the deal itself.  Promoting it to
    # fund_name caused a critical mapping gap: CU chunks got fund_id =
    # "next_edge_capital_corp." while retrieval queried fund_id =
    # "garrington", making all enriched evidence invisible.
    #
    # The entity info remains available in seed["entities"]["fund"] for
    # the LLM to use during memo generation.
    seed["fund_name"] = folder.name
    seed["fund_id"]   = folder.name.lower().replace(" ", "_")

    # Store the entity-discovered fund name separately for reference
    entity_fund = (seed.get("entities", {}).get("fund", {}).get("name") or "").strip()
    if entity_fund and entity_fund != folder.name:
        seed["fund_entity_name"] = entity_fund

    if dry_run:
        logger.info("DRY RUN fund_context.json preview: %s", json.dumps(seed, indent=2, ensure_ascii=False)[:1500])
        return

    ctx_path = folder / "fund_context.json"
    with open(ctx_path, "w", encoding="utf-8") as f:
        json.dump(seed, f, indent=2, ensure_ascii=False)
    logger.info("fund_context.json updated -> %s", ctx_path)


# ============================================================
# BOOTSTRAP A SINGLE DEAL FOLDER
# ============================================================

def bootstrap_folder(
    folder: Path,
    mistral_key: str,
    dry_run: bool = False,
) -> dict:
    logger.info("Bootstrap: %s", folder.name)

    pdfs = sorted(folder.rglob("*.pdf"))
    if BOOTSTRAP_MAX_PDFS > 0:
        pdfs = pdfs[:BOOTSTRAP_MAX_PDFS]
    if not pdfs:
        logger.info("No PDFs found — skipping")
        return {}

    logger.info("%d PDFs -> bootstrap", len(pdfs))

    all_discoveries: list[dict] = []
    ocr_full_text               = ""

    def _process_single_pdf(pdf: Path) -> tuple[str, dict | None]:
        """Process one PDF through OCR → embed filter → regex/GPT. Thread-safe."""
        logger.info("PDF: %s", pdf.name)
        t0 = time.time()

        text = ocr_pdf_bootstrap(str(pdf), mistral_key)
        if not text.strip():
            logger.info("OCR empty — skip %s", pdf.name)
            return "", None

        filtered = filter_lines_by_embedding(text)

        regex_result = extract_entities_regex(filtered, pdf.name)
        entity_count = (
            len(regex_result["aliases"]) +
            len(regex_result["roles"])   +
            len(regex_result["titles"])
        )
        logger.info("regex:%d (%s)", entity_count, pdf.name)

        if entity_count < MIN_REGEX_ENTITIES:
            logger.info("-> GPT mini fallback (%s)", pdf.name)
            discovery = extract_entities_gpt(filtered)
        else:
            discovery = regex_result

        logger.info("%.1fs (%s)", time.time() - t0, pdf.name)
        return text, discovery

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_process_single_pdf, pdf): pdf
            for pdf in pdfs
        }
        for future in as_completed(futures):
            ocr_text, discovery = future.result()
            if ocr_text:
                ocr_full_text += ocr_text + "\n\n"
            if discovery is not None:
                all_discoveries.append(discovery)

    if not all_discoveries:
        logger.info("No entities discovered")
        return {}

    # Stage C+ — filename-driven alias seeder (zero cost, runs on full OCR corpus)
    # The embedding filter in Stage B can drop lines that contain the canonical
    # "FullName (the "ABBREV")" declaration. This pass rescues those by running
    # _P_ALIAS_QUOTED directly on the full concatenated OCR, but only accepting
    # pairs where the alias key matches an uppercase token found in a PDF filename.
    filename_tokens: set[str] = set()
    for pdf in pdfs:
        for tok in re.findall(r"\b([A-Z]{2,8})\b", pdf.stem):
            if not _SKIP_ALIAS_KEYS.match(tok):
                filename_tokens.add(tok)

    if filename_tokens and ocr_full_text:
        filename_seeds: dict[str, str] = {}
        # Search with BOTH patterns: quoted and unquoted parenthesized
        alias_matches = list(_P_ALIAS_QUOTED.finditer(ocr_full_text)) + \
                        list(_P_ALIAS_PAREN.finditer(ocr_full_text))
        for m in alias_matches:
            full  = m.group(1).strip()
            alias = m.group(2).strip()
            alias_up = alias.upper()
            # Split conjunctions — "Entity A and Entity B" → keep only first
            if " and " in full.lower():
                full = full.split(" and ")[0].strip()
            if " or " in full.lower():
                full = full.split(" or ")[0].strip()
            if (alias_up in filename_tokens
                    and not _SKIP_ALIAS_VALUES.search(full)
                    and len(full) >= 8):
                # Keep longest full name seen for this alias
                if alias_up not in filename_seeds or len(full) > len(filename_seeds[alias_up]):
                    filename_seeds[alias_up] = full
        if filename_seeds:
            logger.info("C+ filename seeds: %s", list(filename_seeds.keys()))
            all_discoveries.append({"aliases": filename_seeds, "formerly": [],
                                     "roles": {}, "titles": [], "isins": []})

    # Merge all discoveries
    merged = merge_discoveries(all_discoveries)

    # Stage E — Deterministic vehicle_type validation (replaced Cohere Rerank)
    logger.info("Vehicle_type validation:")
    validated_vehicles: dict[str, dict] = {}
    for alias, full_name in list(merged["aliases"].items())[:5]:
        vehicle, score = validate_vehicle_type(
            full_name, ocr_full_text,
            filename=str(folder.name),
        )
        validated_vehicles[full_name] = {
            "alias":        alias,
            "vehicle_type": vehicle,
            "confidence":   score,
        }
        logger.info("%-50s -> %s (%.4f)", full_name[:50], vehicle, score)

    # Stage F — Fund metadata extraction (strategy, jurisdiction, key terms)
    fund_meta = extract_fund_metadata(ocr_full_text) if ocr_full_text else {}

    # Summary
    logger.info(
        "Summary — Aliases: %d | Roles: %d | Formerly: %s | ISINs: %s | Veh hints: %s",
        len(merged["aliases"]), len(merged["roles"]),
        merged["formerly"], [i["value"] for i in merged["isins"]],
        merged["vehicle_hints"],
    )
    if fund_meta.get("fund_strategy"):
        logger.info("Strategy: %s", fund_meta["fund_strategy"])
    if fund_meta.get("fund_jurisdiction"):
        logger.info("Jurisdiction: %s", fund_meta["fund_jurisdiction"])
    if fund_meta.get("key_terms"):
        logger.info("Key terms: %s", fund_meta["key_terms"])

    seed = load_seed(folder)
    write_enriched(folder, seed, merged, validated_vehicles, fund_meta, dry_run)
    return merged


# ============================================================
# ASYNC BOOTSTRAP — for backend-native pipeline (Stage 2.5)
# ============================================================


@dataclass(frozen=True)
class FundContext:
    """Immutable result of entity bootstrap for a deal.

    Returned in-memory by async_bootstrap_deal() — not written to disk.
    Propagated to Stage 4 (orchestrator) for enrichment context.
    """
    fund_name: str
    deal_name: str
    aliases: dict[str, str]          # alias_key -> full_name
    vehicles: dict[str, dict]        # full_name -> {alias, vehicle_type, confidence}
    roles: dict[str, str]            # entity -> role
    formerly: list[str]
    isins: list[str]
    fund_strategy: list[str]
    fund_jurisdiction: str | None
    key_terms: dict[str, str]
    bootstrap_version: str = "4.0"


async def async_bootstrap_deal(
    deal_name: str,
    blob_paths: list[tuple[str, str]],
    *,
    max_pdfs: int = 5,
) -> FundContext:
    """Async entity bootstrap for a deal — runs as Stage 2.5 in the pipeline.

    Parameters
    ----------
    deal_name : str
        Name of the deal (folder name equivalent).
    blob_paths : list[tuple[str, str]]
        List of (container_name, blob_path) for PDFs belonging to this deal.
    max_pdfs : int
        Maximum number of PDFs to process (default 5, largest first).

    Returns
    -------
    FundContext — immutable dataclass with discovered entities.

    Pipeline:
    A. Mistral OCR (head 15 + tail 10 pages) via async_extract_pdf_with_mistral
    B. Embedding filter (cosine >= 0.72 against canonical phrases)
    C. Regex extraction on filtered lines
    D. GPT-4.1-mini fallback when regex yield < MIN_REGEX_ENTITIES
    E. Merge all discoveries
    F. Deterministic vehicle_type validation (hybrid classifier rules)
    G. Fund metadata extraction (regex, zero cost)

    """
    import asyncio

    # Filter to PDFs only
    pdf_blobs = [(c, p) for c, p in blob_paths if p.lower().endswith(".pdf")]
    if max_pdfs > 0:
        pdf_blobs = pdf_blobs[:max_pdfs]

    if not pdf_blobs:
        logger.info("[bootstrap] No PDFs for deal %s — returning empty FundContext", deal_name)
        return FundContext(
            fund_name=deal_name, deal_name=deal_name,
            aliases={}, vehicles={}, roles={}, formerly=[],
            isins=[], fund_strategy=[], fund_jurisdiction=None, key_terms={},
        )

    logger.info("[bootstrap] Processing %d PDFs for deal %s", len(pdf_blobs), deal_name)

    # ── Stage A: Async text extraction (Mistral OCR with head+tail) ────
    async def _extract_one(container: str, blob_path: str) -> str:
        """Extract head+tail pages from a single PDF via async Mistral OCR."""
        try:
            from ai_engine.extraction.text_extraction import async_extract_text_from_blob

            pages = await async_extract_text_from_blob(container, blob_path)
            if not pages:
                return ""

            # Head + tail page selection (like ocr_pdf_bootstrap)
            total = len(pages)
            head_end = min(BOOTSTRAP_PAGES_HEAD, total)
            tail_start = max(head_end, total - BOOTSTRAP_PAGES_TAIL)
            selected = pages[:head_end] + pages[tail_start:]

            return "\n\n".join(p.get("text", "") for p in selected if p.get("text"))
        except Exception as exc:
            logger.warning("[bootstrap] OCR failed for %s: %s", blob_path, exc)
            return ""

    # Run extractions concurrently (bounded by Mistral rate limiter)
    ocr_tasks = [_extract_one(c, p) for c, p in pdf_blobs]
    ocr_results = await asyncio.gather(*ocr_tasks, return_exceptions=True)

    all_discoveries: list[dict] = []
    ocr_full_text = ""

    for i, ocr_result in enumerate(ocr_results):
        if isinstance(ocr_result, Exception):
            logger.warning("[bootstrap] OCR exception for blob %d: %s", i, ocr_result)
            continue
        if not ocr_result:
            continue

        ocr_full_text += ocr_result + "\n\n"

        # ── Stage B: Embedding filter (sync, runs in thread) ──
        try:
            filtered = await asyncio.to_thread(filter_lines_by_embedding, ocr_result)
        except Exception:
            filtered = ocr_result[:GPT_MINI_CHARS]

        # ── Stage C: Regex extraction ──
        filename = pdf_blobs[i][1].rsplit("/", 1)[-1] if "/" in pdf_blobs[i][1] else pdf_blobs[i][1]
        regex_result = extract_entities_regex(filtered, filename)
        entity_count = (
            len(regex_result.get("aliases", {})) +
            len(regex_result.get("roles", {})) +
            len(regex_result.get("titles", []))
        )

        # ── Stage D: GPT fallback if regex yield is low ──
        if entity_count < MIN_REGEX_ENTITIES:
            try:
                discovery = await asyncio.to_thread(extract_entities_gpt, filtered)
            except Exception:
                discovery = regex_result
        else:
            discovery = regex_result

        all_discoveries.append(discovery)

    if not all_discoveries:
        logger.info("[bootstrap] No entities discovered for deal %s", deal_name)
        return FundContext(
            fund_name=deal_name, deal_name=deal_name,
            aliases={}, vehicles={}, roles={}, formerly=[],
            isins=[], fund_strategy=[], fund_jurisdiction=None, key_terms={},
        )

    # ── Stage E: Merge all discoveries ──
    merged = merge_discoveries(all_discoveries)

    # ── Stage F: Deterministic vehicle validation (replaced Cohere Rerank) ──
    validated_vehicles: dict[str, dict] = {}
    if merged["aliases"]:
        for alias, full_name in list(merged["aliases"].items())[:5]:
            try:
                vehicle, score = await asyncio.to_thread(
                    validate_vehicle_type,
                    full_name, ocr_full_text, deal_name,
                )
                validated_vehicles[full_name] = {
                    "alias": alias,
                    "vehicle_type": vehicle,
                    "confidence": score,
                }
            except Exception as exc:
                logger.warning("[bootstrap] Rerank failed for %s: %s", full_name, exc)

    # ── Stage G: Fund metadata (regex, zero cost) ──
    fund_meta = extract_fund_metadata(ocr_full_text) if ocr_full_text else {}

    logger.info(
        "[bootstrap] Deal %s — aliases=%d, roles=%d, vehicles=%d, strategy=%s",
        deal_name, len(merged["aliases"]), len(merged["roles"]),
        len(validated_vehicles), fund_meta.get("fund_strategy", []),
    )

    return FundContext(
        fund_name=deal_name,
        deal_name=deal_name,
        aliases=merged["aliases"],
        vehicles=validated_vehicles,
        roles=merged["roles"],
        formerly=merged["formerly"],
        isins=[i.get("value", i) if isinstance(i, dict) else str(i) for i in merged.get("isins", [])],
        fund_strategy=fund_meta.get("fund_strategy", []),
        fund_jurisdiction=fund_meta.get("fund_jurisdiction"),
        key_terms=fund_meta.get("key_terms", {}),
    )


# (CLI entry point removed — use bootstrap_folder() directly)
