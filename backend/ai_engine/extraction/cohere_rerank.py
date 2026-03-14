"""Cohere Rerank — zero-shot document classification.

Extracted from legacy ``prepare_pdfs_full.py`` into a standalone async-first
module. Uses ``Cohere-rerank-v4.0-pro`` via Azure AI Foundry to classify
documents into 31 doc_types and 10 vehicle_types.

The reranker compares a query (OCR text window) against rich candidate
descriptions — each description acts as a "document" that the model scores
for relevance against the query.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────
COHERE_MODEL = "Cohere-rerank-v4.0-pro"
_TIMEOUT = 60
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 2.0

# OCR window for query: head + tail of the document
RERANK_OCR_HEAD_CHARS = 5000
RERANK_OCR_TAIL_CHARS = 2000
RERANK_QUERY_CHARS = 8500  # safety cap for total query


# ── Result types ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class DocTypeResult:
    doc_type: str
    score: float
    top3: list[tuple[str, float]] = field(default_factory=list)


@dataclass(frozen=True)
class VehicleTypeResult:
    vehicle_type: str
    score: float
    top3: list[tuple[str, float]] = field(default_factory=list)


# ── Candidate descriptions ───────────────────────────────────────────
# Ported from legacy prepare_pdfs_full.py DOC_TYPE_CANDIDATES / VEHICLE_TYPE_CANDIDATES

DOC_TYPE_CANDIDATES: dict[str, str] = {
    "legal_lpa": (
        "Limited Partnership Agreement (LPA), Amended and Restated Limited Partnership "
        "Agreement (A&R LPA), fund constitution, offering memorandum, private placement "
        "memorandum (PPM), confidential information memorandum (CIM). "
        "Governs the fund's structure, rights of limited partners, GP obligations, "
        "investment objectives, capital commitments, distributions, and fund termination. "
        "Contains legal boilerplate: WHEREAS, NOW THEREFORE, capital accounts, clawback "
        "provisions, distribution waterfall, management fee, carried interest allocation. "
        "Typically 30-100+ pages of dense legal text with numbered articles and sections. "
        "NOT a quarterly update deck. NOT a pitch book. NOT a fund profile."
    ),
    "legal_side_letter": (
        "Side letter agreement between a fund and a specific investor granting "
        "preferential terms: MFN clauses, fee rebates, reporting rights, co-investment "
        "rights, withdrawal rights, or capacity reservations. Supplemental to the LPA."
    ),
    "legal_subscription": (
        "Subscription agreement or subscription booklet completed by an investor to "
        "subscribe for interests or shares in a fund. Includes investor representations, "
        "ERISA status, AML/KYC information, wire instructions, and signature pages."
    ),
    "legal_agreement": (
        "Administrative agreement, service agreement, engagement letter, management "
        "agreement, advisory agreement, placement agent agreement, custodian agreement, "
        "administration agreement, master participation agreement, participation agreement, "
        "ISDA master agreement, prime brokerage agreement, or any bilateral "
        "agreement between two parties for services or commercial terms. "
        "NOT an LPA (which governs the fund structure). NOT a credit agreement "
        "(which involves a borrower and lenders)."
    ),
    "legal_amendment": (
        "Amendment, restatement, or supplement to an existing legal agreement, "
        "LPA, or contract. References the original agreement and modifies specific "
        "provisions, terms, or conditions."
    ),
    "legal_poa": (
        "Power of attorney document authorizing a named person or entity to act on "
        "behalf of another party for signing, executing, or managing documents "
        "related to fund transactions or operations."
    ),
    "legal_term_sheet": (
        "Term sheet, letter of intent (LOI), or indicative terms for a proposed "
        "investment, financing, or fund transaction. SHORT (typically 1-5 pages) "
        "non-binding summary of key economic and governance terms in bullet/table form."
    ),
    "legal_credit_agreement": (
        "Credit agreement, facility agreement, loan agreement, term loan agreement, "
        "revolving credit facility agreement. Executed between a borrower (company) and "
        "lenders. Contains borrower covenants, representations, conditions precedent, "
        "interest provisions, and repayment schedule."
    ),
    "legal_security": (
        "Security agreement, pledge agreement, guarantee, debenture, mortgage, "
        "collateral assignment, security interest document. Creates or perfects a "
        "security interest over assets as collateral for a loan."
    ),
    "legal_intercreditor": (
        "Intercreditor agreement, subordination agreement, or inter-lender agreement. "
        "Governs the relative rights and priorities of different classes of creditors "
        "or lenders in a financing transaction."
    ),
    "financial_statements": (
        "Audited or unaudited financial statements: balance sheet, income statement, "
        "statement of cash flows, statement of changes in net assets, "
        "notes to financial statements, schedule of investments, auditor's report."
    ),
    "financial_nav": (
        "Net Asset Value (NAV) report, NAV statement, or capital account statement. "
        "Shows the fund's NAV per share/unit, total NAV, portfolio fair value."
    ),
    "financial_projections": (
        "Forward-looking financial MODEL, pro forma projections, business plan "
        "financials, projected cash flows, revenue forecasts, budget, or sensitivity "
        "analysis. Contains future-period ESTIMATES with explicit assumptions."
    ),
    "regulatory_cima": (
        "CIMA (Cayman Islands Monetary Authority) regulatory filing, license application, "
        "registration document, annual return to CIMA."
    ),
    "regulatory_compliance": (
        "FATCA self-certification, CRS self-certification, W-8BEN, W-8BEN-E, W-9 tax "
        "form, beneficial ownership form, or tax compliance questionnaire."
    ),
    "regulatory_qdd": (
        "Qualified Derivatives Dealer (QDD) certification or ANBIMA due diligence "
        "questionnaire (DDQ) for Brazilian fund distribution."
    ),
    "fund_structure": (
        "A STANDALONE diagram showing feeder funds, master fund, SPVs, holding entities. "
        "Typically 1-3 pages with minimal prose."
    ),
    "fund_profile": (
        "Fund profile, fund factsheet, fact card, fund overview, or fund summary. "
        "Static marketing/reference document describing fund strategy, team, terms."
    ),
    "fund_presentation": (
        "Quarterly investor update, annual report, investor letter, pitch book, "
        "portfolio update presentation, fund overview presentation, brochure."
    ),
    "fund_policy": (
        "Fund investment policy, investment guidelines, risk management policy, "
        "valuation policy, ESG policy, compliance manual, compliance program."
    ),
    "strategy_profile": (
        "Market commentary, macroeconomic analysis, sector outlook, investment theme "
        "white paper, thought leadership piece, podcast/interview transcript."
    ),
    "capital_raising": (
        "Capital raising materials, fundraising presentation, roadshow deck, "
        "investor targeting document, placement memorandum."
    ),
    "credit_policy": (
        "Credit policy, underwriting guidelines, credit approval framework, risk "
        "rating methodology, loan grading system."
    ),
    "operational_service": (
        "Service level agreement, operations manual, fund administration agreement, "
        "IT policy, disaster recovery plan, employee handbook, code of ethics."
    ),
    "operational_insurance": (
        "Insurance policy, certificate of insurance, D&O insurance, E&O insurance, "
        "cyber insurance."
    ),
    "operational_monitoring": (
        "Portfolio monitoring report or borrower covenant compliance certificate "
        "for a SPECIFIC named portfolio company or borrower."
    ),
    "investment_memo": (
        "Investment memorandum, credit memo, deal memo, IC memo, "
        "or due diligence report on a SPECIFIC named company or asset."
    ),
    "risk_assessment": (
        "Risk assessment report, risk register, stress test analysis, scenario "
        "analysis, or portfolio risk report."
    ),
    "org_chart": (
        "Organizational chart showing management team, reporting lines, "
        "key personnel. Visual diagram of people hierarchy."
    ),
    "attachment": (
        "Exhibit, schedule, appendix, or attachment referenced by a primary "
        "legal or operational document."
    ),
    "other": (
        "Document that does not fit any of the defined categories."
    ),
}

VEHICLE_TYPE_CANDIDATES: dict[str, str] = {
    "standalone_fund": (
        "A named investment fund that pools capital from institutional investors "
        "and deploys it directly into loans, real estate, private credit, or portfolio "
        "companies. Standard closed-end LP structure."
    ),
    "fund_of_funds": (
        "A fund that allocates capital exclusively to other underlying investment funds "
        "or fund managers. Multi-manager or FoF structure."
    ),
    "feeder_master": (
        "An offshore feeder fund, onshore feeder fund, or parallel vehicle that invests "
        "substantially all of its assets into a master fund."
    ),
    "direct_investment": (
        "A SINGLE-ASSET or SINGLE-DEAL investment — not a pooled fund. Bilateral "
        "credit instrument or property-level real estate deal."
    ),
    "spv": (
        "Special purpose vehicle (SPV) or SPE that issues securities: CLO, CDO, "
        "asset-backed securities issuer, or co-investment SPV."
    ),
    "other": (
        "Vehicle type cannot be determined from the document."
    ),
}

# ── Filename hint table ──────────────────────────────────────────────
# Hard overrides where filename alone is unambiguous — skip Cohere entirely

_FILENAME_HINT_TABLE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bLPA\b|\bLimited\s+Partnership\s+Agreement\b", re.I), "legal_lpa"),
    (re.compile(r"\bSide\s+Letter\b", re.I), "legal_side_letter"),
    (re.compile(r"\bSubscription\s+(?:Booklet|Agreement|Doc)\b", re.I), "legal_subscription"),
    (re.compile(r"\bCredit\s+Agreement\b|\bLoan\s+Agreement\b|\bFacility\s+Agreement\b", re.I), "legal_credit_agreement"),
    (re.compile(r"\bMaster\s+Participation\b|\bParticipation\s+Agreement\b", re.I), "legal_agreement"),
    (re.compile(r"\bFinancial\s+Statements?\b|\bAudit(?:ed)?\s+(?:Financial|Report)\b", re.I), "financial_statements"),
    (re.compile(r"\bFact[\s_\-]?Card\b|\bFact[\s_\-]?Sheet\b", re.I), "fund_profile"),
    (re.compile(r"\bFund\s+Profile\b|\bFund\s+Overview\b", re.I), "fund_profile"),
    (re.compile(r"\bStructure\s+(?:Chart|Diagram)\b|\bEntity\s+Chart\b", re.I), "fund_structure"),
    (re.compile(r"\bCredit\s+Policy\b|\bUnderwriting\s+(?:Guide|Policy|Manual)\b", re.I), "credit_policy"),
    (re.compile(r"\bCompliance\s+(?:Manual|Program)\b", re.I), "fund_policy"),
    (re.compile(r"\bEmployee\s+Handbook\b|\bHR\s+(?:Policy|Manual|Handbook)\b", re.I), "operational_service"),
    (re.compile(r"\bOrg(?:anization(?:al)?)?[\s_\-]?Chart\b", re.I), "org_chart"),
    (re.compile(r"\bRisk\s+Assessment\b", re.I), "risk_assessment"),
]

# doc_types where vehicle_type is not applicable
_NO_VEHICLE_DOC_TYPES = frozenset({
    "strategy_profile", "org_chart", "attachment",
    "credit_policy", "operational_service", "operational_insurance",
    "risk_assessment", "regulatory_cima", "regulatory_compliance",
    "regulatory_qdd", "other", "legal_side_letter", "capital_raising",
    "fund_structure", "fund_profile", "fund_policy", "legal_agreement",
})


# ── OCR window ───────────────────────────────────────────────────────


def _rerank_ocr_window(ocr_text: str) -> str:
    """Extract head+tail window from OCR text for reranker query."""
    total = RERANK_OCR_HEAD_CHARS + RERANK_OCR_TAIL_CHARS
    if len(ocr_text) <= total:
        return ocr_text
    head = ocr_text[:RERANK_OCR_HEAD_CHARS]
    tail = ocr_text[-RERANK_OCR_TAIL_CHARS:]
    return head + "\n\n[...]\n\n" + tail


def _filename_hint(filename: str) -> str | None:
    """Return hard-override doc_type from filename, or None."""
    for pattern, doc_type in _FILENAME_HINT_TABLE:
        if pattern.search(filename):
            return doc_type
    return None


# ── Core rerank call ─────────────────────────────────────────────────


async def _async_rerank(
    query: str,
    candidates: dict[str, str],
    *,
    endpoint: str,
    api_key: str,
    top_n: int = 3,
) -> list[tuple[str, float]]:
    """Call Cohere Rerank API and return sorted (label, score) pairs."""
    labels = list(candidates.keys())
    docs = list(candidates.values())

    payload: dict = {
        "model": COHERE_MODEL,
        "query": query[:RERANK_QUERY_CHARS],
        "documents": docs,
        "max_tokens_per_doc": 512,
        "top_n": top_n,
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for attempt in range(_MAX_RETRIES):
            resp = await client.post(
                endpoint,
                headers={
                    "Content-Type": "application/json",
                    "api-key": api_key,
                },
                json=payload,
            )

            if resp.status_code == 200:
                break

            if resp.status_code in (429, 500, 502, 503, 504) and attempt < _MAX_RETRIES - 1:
                wait = _RETRY_BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    "Cohere Rerank HTTP %d, retry %d/%d in %.1fs",
                    resp.status_code, attempt + 1, _MAX_RETRIES, wait,
                )
                await asyncio.sleep(wait)
                continue

            logger.debug("Cohere Rerank error response: %s", resp.text[:500])
            raise RuntimeError(f"Cohere Rerank failed with HTTP {resp.status_code}")

    results = resp.json().get("results", [])
    ranked = sorted(results, key=lambda r: r["relevance_score"], reverse=True)
    return [(labels[r["index"]], round(r["relevance_score"], 4)) for r in ranked]


# ── Public async API ─────────────────────────────────────────────────


async def async_classify_doc_type(
    ocr_text: str,
    filename: str,
    *,
    endpoint: str | None = None,
    api_key: str | None = None,
) -> DocTypeResult:
    """Classify document type via Cohere Rerank (async).

    Returns DocTypeResult with doc_type, score, and top3.
    Uses filename hard-override when unambiguous (score=1.0).
    """
    if endpoint is None or api_key is None:
        from app.core.config.settings import settings
        endpoint = endpoint or settings.COHERE_RERANK_ENDPOINT
        api_key = api_key or settings.COHERE_RERANK_KEY
    if not api_key:
        raise ValueError("COHERE_RERANK_KEY not configured")

    # Filename hard override
    hint = _filename_hint(filename)
    if hint:
        logger.info("doc_type filename override: %s → %s", filename, hint)
        return DocTypeResult(doc_type=hint, score=1.0, top3=[(hint, 1.0)])

    query = f"Filename: {filename}\n\n{_rerank_ocr_window(ocr_text)}"
    ranked = await _async_rerank(
        query, DOC_TYPE_CANDIDATES, endpoint=endpoint, api_key=api_key, top_n=3,
    )

    return DocTypeResult(
        doc_type=ranked[0][0],
        score=ranked[0][1],
        top3=ranked,
    )


async def async_classify_vehicle_type(
    ocr_text: str,
    filename: str,
    doc_type: str,
    *,
    endpoint: str | None = None,
    api_key: str | None = None,
) -> VehicleTypeResult:
    """Classify vehicle type via Cohere Rerank (async).

    Skips classification for doc_types where vehicle_type is not applicable.
    """
    if doc_type in _NO_VEHICLE_DOC_TYPES:
        return VehicleTypeResult(vehicle_type="other", score=1.0, top3=[("other", 1.0)])

    if endpoint is None or api_key is None:
        from app.core.config.settings import settings
        endpoint = endpoint or settings.COHERE_RERANK_ENDPOINT
        api_key = api_key or settings.COHERE_RERANK_KEY
    if not api_key:
        raise ValueError("COHERE_RERANK_KEY not configured")

    query = f"Filename: {filename}\n\n{_rerank_ocr_window(ocr_text)}"
    ranked = await _async_rerank(
        query, VEHICLE_TYPE_CANDIDATES, endpoint=endpoint, api_key=api_key, top_n=3,
    )

    return VehicleTypeResult(
        vehicle_type=ranked[0][0],
        score=ranked[0][1],
        top3=ranked,
    )
