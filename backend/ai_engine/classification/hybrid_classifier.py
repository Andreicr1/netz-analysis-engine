"""Hybrid three-layer document classifier.

Replaces Cohere Rerank for doc_type and vehicle_type classification.

Layer 1 — Deterministic rules (filename + first-500-chars content).
Layer 2 — TF-IDF cosine similarity against synthetic exemplars.
Layer 3 — LLM fallback (gpt-4.1-mini) via ``document_intelligence``.

All layers return ``HybridClassificationResult`` with unified 0.0–1.0
confidence and layer indicator.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ai_engine.pipeline.models import (
    CANONICAL_DOC_TYPES,
    CANONICAL_VEHICLE_TYPES,
    NO_VEHICLE_DOC_TYPES,
    HybridClassificationResult,
)

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

# ── OCR window constants ─────────────────────────────────────────────
_OCR_HEAD_CHARS = 5000
_OCR_TAIL_CHARS = 2000

# ── Layer 2 thresholds ───────────────────────────────────────────────
_MIN_SIMILARITY = 0.05       # below this → no match at all → escalate
_MIN_RATIO = 1.3             # top-1/top-2 ratio below this → ambiguous → escalate


# =====================================================================
#  DOC_TYPE_CANDIDATES — synthetic exemplars for Layer 2
#  Ported from prepare_pdfs_full.py (richer descriptions with NOT
#  clauses intact — these are discriminative features for TF-IDF).
# =====================================================================

DOC_TYPE_DESCRIPTIONS: dict[str, str] = {
    "legal_lpa": (
        "Limited Partnership Agreement (LPA), Amended and Restated Limited Partnership "
        "Agreement (A&R LPA), fund constitution, offering memorandum, private placement "
        "memorandum (PPM), confidential information memorandum (CIM). "
        "Governs the fund's structure, rights of limited partners, GP obligations, "
        "investment objectives, capital commitments, distributions, and fund termination. "
        "Contains legal boilerplate: WHEREAS, NOW THEREFORE, capital accounts, clawback "
        "provisions, distribution waterfall, management fee, carried interest allocation. "
        "PPM and CIM sections include: risk factors, investor suitability requirements, "
        "offering terms, subscription procedures, regulatory disclosures, tax considerations, "
        "ERISA status, conflicts of interest, use of proceeds, investment restrictions, "
        "redemption provisions, eligible investor representations, placement agent fees, "
        "anti-money laundering, FATCA/CRS compliance, indemnification, and confidentiality. "
        "Typically 30-100+ pages of dense legal text with numbered articles and sections. "
        "NOT a quarterly update deck. NOT a pitch book. NOT a fund profile. "
        "NOT a subscription agreement or side letter (those are separate documents)."
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
        "non-binding summary of key economic and governance terms in bullet/table form. "
        "NOT a multi-page pitch book, investment memo, intro materials, or pipeline overview "
        "that analyses an opportunity with executive summary, highlights, and risk sections. "
        "NOT a document with 'Intro Materials', 'Pipeline', 'Condensed', or 'Presentation' "
        "in the filename — those are fund_presentation or investment_memo."
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
        "Audited or unaudited financial statements: balance sheet (statement of financial "
        "position), income statement (statement of operations), statement of cash flows, "
        "statement of changes in net assets, statement of changes in partners' capital, "
        "notes to financial statements, schedule of investments, "
        "auditor's report (PricewaterhouseCoopers, Deloitte, Ernst & Young, KPMG, BDO, RSM). "
        "Prepared in accordance with GAAP, IFRS, or similar accounting standards. "
        "Typically contains: total assets, total liabilities, net assets, revenue, expenses, "
        "net investment income, realized and unrealized gains/losses, accounting policies. "
        "The document title or header often includes 'Financial Statements' or the "
        "fund name followed by a fiscal year end date. "
        "NOT a NAV report (which is a shorter periodic statement). "
        "NOT a fund presentation or investor update. "
        "NOT a fund policy or credit policy."
    ),
    "financial_nav": (
        "Net Asset Value (NAV) report, NAV statement, or capital account statement. "
        "Shows the fund's NAV per share/unit, total NAV, portfolio fair value, "
        "accruals, and investor capital balances at a specific date."
    ),
    "financial_projections": (
        "Forward-looking financial MODEL, pro forma projections, business plan "
        "financials, projected cash flows, revenue forecasts, budget, or sensitivity "
        "analysis. Contains future-period ESTIMATES with explicit assumptions stated, "
        "not historical actuals. Must contain an actual numerical model with "
        "clearly labeled projected periods (Year 1, Year 2, Base Case, Upside Case). "
        "NOT a fund presentation or pitch deck that shows past performance plus targets. "
        "NOT an investor deck or quarterly update (use fund_presentation). "
        "NOT a capital raising roadshow (use capital_raising). "
        "NOT a fund overview or brochure (use fund_presentation or fund_profile). "
        "If the document primarily DESCRIBES a fund to investors — even with "
        "forward-looking targets — it is fund_presentation, NOT financial_projections."
    ),
    "regulatory_cima": (
        "CIMA (Cayman Islands Monetary Authority) regulatory filing, license application, "
        "registration document, annual return to CIMA, or correspondence with CIMA. "
        "Specific to Cayman Islands regulated fund vehicles."
    ),
    "regulatory_compliance": (
        "FATCA self-certification, CRS self-certification, W-8BEN, W-8BEN-E, W-9 tax "
        "form, beneficial ownership form, or tax compliance questionnaire. "
        "These are EXTERNAL regulatory FORMS that an investor or entity must complete "
        "to comply with tax or anti-money laundering regulations. "
        "NOT an internal compliance manual or compliance policy (use fund_policy instead). "
        "NOT an employee handbook (use operational_service instead)."
    ),
    "regulatory_qdd": (
        "Qualified Derivatives Dealer (QDD) certification or application ONLY, "
        "OR an ANBIMA due diligence questionnaire (DDQ) for Brazilian fund distribution. "
        "QDD: specific US withholding tax document under IRC Section 871(m). "
        "ANBIMA DDQ: standardized questionnaire with sections on organization, "
        "investment process, risk management, compliance, operations. "
        "Must explicitly reference QDD status, IRC 871(m), ANBIMA DDQ, or "
        "'questionario de due diligence'. "
        "NOT a rate sheet. NOT a fund overview or two-pager. NOT a loan document. "
        "NOT a legal memo. NOT a fund profile or fund presentation."
    ),
    "fund_structure": (
        "A STANDALONE, DEDICATED diagram page: a document whose PRIMARY content is a "
        "visual chart showing feeder funds, master fund, SPVs, holding entities, and "
        "capital flow arrows. Also called 'structure chart', 'structure diagram', "
        "'entity chart', or 'organizational structure diagram'. "
        "Typically 1-3 pages with minimal prose — mostly entity names, arrows, and labels. "
        "Filename often contains: 'Structure Chart', 'Structure Diagram', 'Entity Chart'. "
        "NOT a multi-page narrative document. NOT a quarterly investor update. "
        "NOT an org chart (which shows people/management hierarchy, not legal entities)."
    ),
    "fund_profile": (
        "Fund profile, fund factsheet, fact card, fund overview, or fund summary document: "
        "a static marketing/reference document describing a specific fund's strategy, team, "
        "terms, track record, and key statistics (AUM, vintage year, target return, fund size, "
        "management fee, performance fee, hurdle rate, GP commitment). "
        "Timeless reference document — NOT tied to a specific quarterly reporting period. "
        "Filename often contains: 'Fact Card', 'Fact Sheet', 'Fund Profile', "
        "'Fund Overview', 'Profile'. "
        "NOT fund_policy (which governs investment decisions internally). "
        "NOT fund_presentation (which is a periodic Q1/Q2/Q3/Q4 update with date-specific data). "
        "NOT strategy_profile (which is about market themes, not a specific fund)."
    ),
    "fund_presentation": (
        "Quarterly investor update (Q1, Q2, Q3, Q4), annual report, investor letter, "
        "investor deck, investor report, pitch book, portfolio update presentation, "
        "fund overview presentation, brochure, intro materials, or BDC presentation. "
        "A document that DESCRIBES a fund to investors — showing strategy, team, "
        "track record, portfolio highlights, fund performance metrics "
        "(Net IRR, Gross IRR, MOIC, DPI, TVPI), and financial data. "
        "May contain forward-looking targets alongside historical performance. "
        "Filename often contains: 'Presentation', 'Investor', 'Deck', 'Overview', "
        "'Intro', 'Brochure', 'BDC', or period labels like 'Q1', 'Q2'. "
        "PREFERRED over financial_projections when the document primarily describes "
        "a fund to investors rather than containing a standalone financial model. "
        "NOT a static fund profile (1-2 page factsheet). NOT a fund structure diagram. "
        "NOT a legal agreement."
    ),
    "fund_policy": (
        "Fund investment policy, investment guidelines, risk management policy, "
        "valuation policy, ESG policy, allocation policy, or internal compliance policy "
        "that governs how the fund operates and makes investment decisions. "
        "Also includes: compliance manual, compliance program, supervisory procedures. "
        "These are INTERNAL governance documents for the fund manager or GP. "
        "NOT a credit policy (which governs lending/underwriting criteria — use credit_policy). "
        "NOT an employee handbook or HR policy (use operational_service). "
        "NOT financial statements (use financial_statements). "
        "NOT regulatory forms like FATCA/CRS (use regulatory_compliance)."
    ),
    "strategy_profile": (
        "Market commentary, macroeconomic analysis, sector outlook, investment theme "
        "white paper, thought leadership piece, podcast transcript, interview transcript, "
        "webinar transcript about investment strategy, market conditions, or industry themes "
        "(e.g. private credit, real estate debt, cannabis lending, trade finance). "
        "Also: strategy profile document, strategy overview, strategy description, "
        "perfil da estratégia, perfil de crédito privado. "
        "May be in English, Portuguese, or other languages. "
        "Filename often contains: 'Strategy Profile', 'Podcast', 'Commentary', "
        "'Interview', 'Outlook', 'Webinar', 'Market Update', 'White Paper'. "
        "NOT specific to a single fund's periodic performance. NOT a fund structure diagram."
    ),
    "capital_raising": (
        "Capital raising materials, fundraising presentation, roadshow deck, "
        "investor targeting document, placement memorandum, or capital raise update. "
        "Designed to attract new investors to a fund. "
        "Filename often contains: 'Capital Raising', 'Fundraising', 'Roadshow'."
    ),
    "credit_policy": (
        "Credit policy, underwriting guidelines, credit approval framework, risk "
        "rating methodology, loan grading system, or investment criteria document. "
        "Specifies how credit decisions are made and what standards borrowers must meet. "
        "Typically contains: underwriting criteria, credit committee process, "
        "approval authority matrix, risk rating scale, portfolio concentration limits, "
        "collateral requirements, loan-to-value ratios, debt service coverage ratios, "
        "eligibility criteria, credit analysis procedures, watchlist management, "
        "problem loan management, covenant monitoring framework, workout procedures. "
        "May be a substantial multi-page manual (20-50+ pages). "
        "NOT fund_policy (which is about fund-level investment guidelines). "
        "NOT a credit agreement (which is a specific bilateral legal contract)."
    ),
    "operational_service": (
        "Service level agreement, operations manual, fund administration agreement, "
        "IT service agreement, IT policy, IT governance document, "
        "disaster recovery plan, business continuity plan, "
        "information security policy, data protection policy, "
        "employee handbook, staff handbook, staff manual, HR policy manual, "
        "code of ethics, code of conduct, workplace policy, "
        "or operational procedures documentation for fund "
        "day-to-day operations and service provider relationships. "
        "Includes any internal company handbook, workplace policies, "
        "employee conduct, benefits, leave policies, PTO, vacation, "
        "disciplinary procedures, grievance policy, onboarding, "
        "and administrative procedures. "
        "A document titled 'Employee Handbook' or 'Staff Manual' is ALWAYS "
        "operational_service even if it lists managers, titles, or reporting lines. "
        "NOT an org chart (which is a SHORT 1-2 page visual diagram ONLY)."
    ),
    "operational_insurance": (
        "Insurance policy, certificate of insurance, D&O insurance, E&O insurance, "
        "cyber insurance, or insurance-related documentation for the fund or GP."
    ),
    "operational_monitoring": (
        "Portfolio monitoring report or borrower covenant compliance certificate "
        "for a SPECIFIC named portfolio company or borrower. Contains borrower name, "
        "financial covenant tests (leverage ratio, interest coverage), compliance status "
        "pass/fail, and surveillance data for a specific loan or investment. "
        "NOT a fund-level quarterly update — this is company-level or loan-level monitoring. "
        "NOT a strategy profile or fund profile or fund overview."
    ),
    "investment_memo": (
        "Investment memorandum, credit memo, deal memo, investment committee (IC) memo, "
        "IC memorandum, or due diligence report on a SPECIFIC named company, property, "
        "or asset. Contains investment thesis, loan opportunity, deal structure, "
        "financial analysis, borrower profile, collateral description, risk factors, "
        "underwriting analysis, sponsor overview, exit strategy, and recommendation "
        "for a particular deal or potential investment. "
        "Filename often contains: 'Investment Memo', 'Credit Memo', 'IC Memo', "
        "'IC_Memorandum', 'Deal Memo', 'Due Diligence'. "
        "NOT a fund-level presentation or quarterly update. NOT a general PPM or LPA."
    ),
    "risk_assessment": (
        "Risk assessment report, risk register, stress test analysis, scenario "
        "analysis, or portfolio risk report identifying and quantifying specific "
        "risks in the fund or a particular investment. "
        "Short document (typically 1-5 pages) focused on risk identification."
    ),
    "org_chart": (
        "Organizational chart showing the management team, reporting lines, "
        "key personnel, GP structure, or fund management organization. "
        "A VISUAL diagram of people and reporting hierarchy with boxes and lines. "
        "Typically 1-2 pages. People-centric diagram rather than legal entity diagram. "
        "NEVER use org_chart for multi-page documents (10+ pages) — those are handbooks or manuals. "
        "NOT an employee handbook, staff manual, HR policy, or code of conduct "
        "(use operational_service even if they mention managers or titles). "
        "NOT a corporate structure chart (use fund_structure)."
    ),
    "attachment": (
        "Exhibit, schedule, appendix, or attachment referenced by a primary "
        "legal or operational document. Standalone exhibits, signature pages, "
        "or supporting materials with no independent classification. "
        "NOT a standalone policy, handbook, or manual — those have their own type."
    ),
    "other": (
        "Document that does not fit any of the defined categories. Generic forms, "
        "miscellaneous correspondence, or documents where classification is truly ambiguous."
    ),
}

# Verify at import time that descriptions cover exactly the canonical set.
if set(DOC_TYPE_DESCRIPTIONS.keys()) != CANONICAL_DOC_TYPES:
    raise RuntimeError(
        f"DOC_TYPE_DESCRIPTIONS keys mismatch: "
        f"extra={set(DOC_TYPE_DESCRIPTIONS.keys()) - CANONICAL_DOC_TYPES}, "
        f"missing={CANONICAL_DOC_TYPES - set(DOC_TYPE_DESCRIPTIONS.keys())}"
    )


VEHICLE_TYPE_DESCRIPTIONS: dict[str, str] = {
    "standalone_fund": (
        "A named investment fund (e.g. 'Fund VI', 'Fund II', 'Credit Fund III') that "
        "pools capital from institutional investors (limited partners) and deploys it "
        "directly into loans, real estate assets, private credit, or portfolio companies. "
        "Documents include: quarterly investor updates, annual reports, investor letters, "
        "pitch books showing fund NAV, net IRR, gross IRR, MOIC, capital raised, "
        "portfolio company highlights, and Commitment Period / Investment Period data. "
        "Also includes LPAs and subscription agreements for such funds. "
        "Standard closed-end structure. Investors do NOT invest into other funds — "
        "they invest into a single named fund vehicle that owns assets directly."
    ),
    "fund_of_funds": (
        "A fund that allocates capital exclusively to other underlying investment funds "
        "or fund managers — not directly to companies or assets. Performs manager "
        "selection, due diligence on underlying funds, and portfolio construction "
        "across multiple external fund managers. Multi-manager or FoF structure."
    ),
    "feeder_master": (
        "An offshore feeder fund, onshore feeder fund, or parallel vehicle that invests "
        "substantially all of its assets into a master fund. Common structure with a "
        "Cayman Islands (offshore) feeder and a Delaware (onshore) feeder both feeding "
        "into a single master partnership. Parallel fund structure."
    ),
    "direct_investment": (
        "A SINGLE-ASSET or SINGLE-DEAL investment — NOT a pooled fund. Two main flavours: "
        "(A) A BILATERAL CREDIT INSTRUMENT executed between a specific borrower and lenders: "
        "credit agreement, term loan agreement, revolving credit facility, promissory note, "
        "or a deal-level SPV for a SINGLE named transaction. "
        "Key identifying markers: 'Borrower:', 'Administrative Agent:', 'Facility Agent:', "
        "'Lenders:', 'Guarantor:', covenants, representations and warranties. "
        "(B) A PROPERTY-LEVEL real estate deal: acquisition memo, investment opportunity, "
        "or deal summary for a specific asset (e.g., a retail property, a building, "
        "a co-op, a warehouse). Key markers: purchase price, cap rate, rent roll, tenant, "
        "square footage, submarket, property overview, entry/exit yield. "
        "This is NOT a fund with diversified portfolio, NOT a quarterly fund update, "
        "NOT a pitch book describing the fund-level strategy. "
        "Does NOT contain fund-level NAV, MOIC, IRR across multiple deals."
    ),
    "spv": (
        "Special purpose vehicle (SPV) or special purpose entity (SPE) that ISSUES "
        "securities: CLO (Collateralized Loan Obligation), CDO, asset-backed securities "
        "issuer, or co-investment SPV for a specific transaction. "
        "Has Issuer and Co-Issuer roles. Contains Indenture, Note Purchase Agreement, "
        "Trustee, Collateral Manager. "
        "NOT a tax form, NOT a regulatory filing, NOT an investor subscription document. "
        "A financial securitization vehicle with tranches and rated notes."
    ),
    "other": (
        "Vehicle type cannot be determined from the document. The document does not "
        "contain sufficient information to classify the fund structure or vehicle type."
    ),
}

if set(VEHICLE_TYPE_DESCRIPTIONS.keys()) != CANONICAL_VEHICLE_TYPES:
    raise RuntimeError(
        f"VEHICLE_TYPE_DESCRIPTIONS keys mismatch: "
        f"extra={set(VEHICLE_TYPE_DESCRIPTIONS.keys()) - CANONICAL_VEHICLE_TYPES}, "
        f"missing={CANONICAL_VEHICLE_TYPES - set(VEHICLE_TYPE_DESCRIPTIONS.keys())}"
    )


# =====================================================================
#  Layer 1 — Deterministic filename + content rules
#  Ported from prepare_pdfs_full.py _FILENAME_HINT_TABLE (28 rules).
# =====================================================================

_FILENAME_RULES: list[tuple[re.Pattern[str], str]] = [
    # --- Legal documents (most specific) ---
    (re.compile(r"\bLPA\b|\bLimited\s+Partnership\s+Agreement\b", re.I), "legal_lpa"),
    (re.compile(r"\bSide\s+Letter\b", re.I), "legal_side_letter"),
    (re.compile(r"\bSubscription\s+(?:Booklet|Agreement|Doc(?:ument)?)\b", re.I), "legal_subscription"),
    (re.compile(r"\bCredit\s+Agreement\b|\bLoan\s+Agreement\b|\bFacility\s+Agreement\b", re.I), "legal_credit_agreement"),
    (re.compile(r"\bMaster\s+Participation\b|\bParticipation\s+Agreement\b", re.I), "legal_agreement"),

    # --- Financial ---
    (re.compile(r"\bFinancial\s+Statements?\b|\bAudit(?:ed)?\s+(?:Financial|Report)\b", re.I), "financial_statements"),

    # --- Fund documents (specific before generic) ---
    (re.compile(r"\bFact[\s_\-]?Card\b|\bFact[\s_\-]?Sheet\b", re.I), "fund_profile"),
    (re.compile(r"\bFund\s+Profile\b|\bFund\s+Overview\b", re.I), "fund_profile"),
    (re.compile(r"\bStructure\s+(?:Chart|Diagram)\b|\bEntity\s+Chart\b", re.I), "fund_structure"),
    (re.compile(r"\bStrategy\s+(?:Profile|Overview)\b", re.I), "strategy_profile"),
    (re.compile(r"\b(?:Podcast|Interview|Webinar|Commentary|Market[\s_\-]Update|White[\s_\-]Paper)\b", re.I), "strategy_profile"),
    (re.compile(r"\bCapital\s+Rais(?:ing|e)\b|\bFundraising\b|\bRoadshow\b", re.I), "capital_raising"),

    # --- Policy / Operational ---
    (re.compile(r"\bCredit\s+Policy\b|\bUnderwriting\s+(?:Guide|Policy|Manual)\b", re.I), "credit_policy"),
    (re.compile(r"\bCompliance\s+(?:Manual|Program)\b|\bSupervisory\s+Procedures?\b", re.I), "fund_policy"),
    (re.compile(r"\bEmployee\s+Handbook\b|\bHR\s+(?:Policy|Manual|Handbook)\b", re.I), "operational_service"),
    (re.compile(r"\bIT\s+(?:Policy|Disaster|Security)\b|\bBusiness\s+Continuity\b|\bDisaster\s+Recovery\b", re.I), "operational_service"),
    (re.compile(r"\bCode\s+of\s+(?:Ethics|Conduct)\b", re.I), "operational_service"),
    (re.compile(r"\bOrg(?:anization(?:al)?)?[\s_\-]?Chart\b", re.I), "org_chart"),
    (re.compile(r"\bRisk\s+Assessment\b", re.I), "risk_assessment"),
    (re.compile(r"\bQDD\b", re.I), "regulatory_qdd"),

    # --- Legal: PPM / Offering Memorandum (before generic presentation rules) ---
    (re.compile(r"\bPPM\b|\bPrivate\s+Placement\s+Memorandum\b|\bOffering\s+Memorandum\b|\bConfidential\s+(?:Information\s+)?Memorandum\b", re.I), "legal_lpa"),

    # --- Deal / investment-level memos ---
    (re.compile(r"\bIntro\s+Materials?\b", re.I), "investment_memo"),
    (re.compile(r"\b(?:Investment|Credit|IC|Deal)[\s\-]?Memo(?:randum)?\b", re.I), "investment_memo"),
    (re.compile(r"\bDue\s+Diligence\s+Report\b", re.I), "investment_memo"),

    # --- Investor letters (before generic presentation/quarterly rules) ---
    (re.compile(r"\b(?:Investor|Quarterly|Annual)\s+Letter\b", re.I), "fund_presentation"),
    (re.compile(r"\bShareholder\s+(?:Update|Letter|Report)\b", re.I), "fund_presentation"),
    (re.compile(r"\bQuarterly\s+(?:Investor\s+)?(?:Letter|Report|Update)\b", re.I), "fund_presentation"),

    # --- Fund pipeline / condensed presentations ---
    (re.compile(r"\bPipeline\b|\bSourcing\b", re.I), "fund_presentation"),
    (re.compile(r"\bCondensed\s+Version\b|\bBrochure\b|\bTeaser\b", re.I), "fund_presentation"),
    (re.compile(r"\bPresentation\b|\bInvestor\s+Deck\b|\bPitch\s*Book\b", re.I), "fund_presentation"),

    # --- Quarterly / periodic (WEAKEST — checked last) ---
    (re.compile(
        r"\b(?:1Q|2Q|3Q|4Q|Q1|Q2|Q3|Q4|YTD)[\s_\-]?\d{2,4}\b"
        r"|\b\d{2,4}[\s_\-]?(?:1Q|2Q|3Q|4Q|Q1|Q2|Q3|Q4)\b"
        r"|\b\d{4}[\s_\-]?(?:annual|year.end|semi.annual)\b",
        re.I,
    ), "fund_presentation"),
]

# Content rules: patterns in the first 500 chars of OCR text that are
# unambiguous enough to classify without any ML.
_CONTENT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"AUDITED\s+FINANCIAL\s+STATEMENTS", re.I), "financial_statements"),
    (re.compile(r"INDEPENDENT\s+AUDITOR.?S\s+REPORT", re.I), "financial_statements"),
    (re.compile(r"STATEMENT\s+OF\s+(?:FINANCIAL\s+POSITION|ASSETS\s+AND\s+LIABILITIES)", re.I), "financial_statements"),
    (re.compile(r"LIMITED\s+PARTNERSHIP\s+AGREEMENT", re.I), "legal_lpa"),
    (re.compile(r"AMENDED\s+AND\s+RESTATED\s+(?:LIMITED\s+PARTNERSHIP|LPA)", re.I), "legal_lpa"),
    (re.compile(r"SUBSCRIPTION\s+(?:AGREEMENT|BOOKLET)", re.I), "legal_subscription"),
    (re.compile(r"POWER\s+OF\s+ATTORNEY", re.I), "legal_poa"),
    (re.compile(r"CREDIT\s+(?:AGREEMENT|FACILITY)", re.I), "legal_credit_agreement"),
    (re.compile(r"INTERCREDITOR\s+AGREEMENT", re.I), "legal_intercreditor"),
    (re.compile(r"SECURITY\s+(?:AGREEMENT|INTEREST)", re.I), "legal_security"),
    (re.compile(r"PLEDGE\s+AGREEMENT", re.I), "legal_security"),
    (re.compile(r"CERTIFICATE\s+OF\s+INSURANCE", re.I), "operational_insurance"),
    (re.compile(r"NET\s+ASSET\s+VALUE\s+(?:REPORT|STATEMENT)", re.I), "financial_nav"),
    (re.compile(r"PRIVATE\s+PLACEMENT\s+MEMORANDUM", re.I), "legal_lpa"),
    (re.compile(r"CONFIDENTIAL\s+(?:INFORMATION\s+)?MEMORANDUM", re.I), "legal_lpa"),
    (re.compile(r"OFFERING\s+MEMORANDUM", re.I), "legal_lpa"),
    (re.compile(r"INVESTMENT\s+(?:COMMITTEE\s+)?MEMORANDUM", re.I), "investment_memo"),
]


# =====================================================================
#  Layer 2 — TF-IDF vectorizer (lazy-init, not module-level)
# =====================================================================

_doc_type_vectorizer: TfidfVectorizer | None = None
_doc_type_labels: list[str] | None = None
_doc_type_matrix: np.ndarray | None = None

_vehicle_type_vectorizer: TfidfVectorizer | None = None
_vehicle_type_labels: list[str] | None = None
_vehicle_type_matrix: np.ndarray | None = None


def _ensure_doc_type_vectorizer() -> tuple[TfidfVectorizer, list[str], "np.ndarray"]:
    """Lazy-init TF-IDF vectorizer for doc_type classification."""
    global _doc_type_vectorizer, _doc_type_labels, _doc_type_matrix
    if _doc_type_vectorizer is not None:
        assert _doc_type_labels is not None
        assert _doc_type_matrix is not None
        return _doc_type_vectorizer, _doc_type_labels, _doc_type_matrix

    labels = list(DOC_TYPE_DESCRIPTIONS.keys())
    descriptions = list(DOC_TYPE_DESCRIPTIONS.values())

    vectorizer = TfidfVectorizer(
        sublinear_tf=True,
        ngram_range=(1, 2),
        max_features=5000,
        stop_words="english",
    )
    matrix = vectorizer.fit_transform(descriptions)

    _doc_type_vectorizer = vectorizer
    _doc_type_labels = labels
    _doc_type_matrix = matrix
    return vectorizer, labels, matrix


def _ensure_vehicle_type_vectorizer() -> tuple[TfidfVectorizer, list[str], "np.ndarray"]:
    """Lazy-init TF-IDF vectorizer for vehicle_type classification."""
    global _vehicle_type_vectorizer, _vehicle_type_labels, _vehicle_type_matrix
    if _vehicle_type_vectorizer is not None:
        assert _vehicle_type_labels is not None
        assert _vehicle_type_matrix is not None
        return _vehicle_type_vectorizer, _vehicle_type_labels, _vehicle_type_matrix

    labels = list(VEHICLE_TYPE_DESCRIPTIONS.keys())
    descriptions = list(VEHICLE_TYPE_DESCRIPTIONS.values())

    vectorizer = TfidfVectorizer(
        sublinear_tf=True,
        ngram_range=(1, 2),
        max_features=5000,
        stop_words="english",
    )
    matrix = vectorizer.fit_transform(descriptions)

    _vehicle_type_vectorizer = vectorizer
    _vehicle_type_labels = labels
    _vehicle_type_matrix = matrix
    return vectorizer, labels, matrix


# =====================================================================
#  OCR window
# =====================================================================

def _ocr_window(text: str) -> str:
    """Extract head+tail window from OCR text for classification."""
    total = _OCR_HEAD_CHARS + _OCR_TAIL_CHARS
    if len(text) <= total:
        return text
    return text[:_OCR_HEAD_CHARS] + "\n\n[...]\n\n" + text[-_OCR_TAIL_CHARS:]


# =====================================================================
#  Layer 2 — cosine similarity classification
# =====================================================================

def _classify_cosine(
    text: str,
    vectorizer: TfidfVectorizer,
    labels: list[str],
    matrix: "np.ndarray",
) -> tuple[str, float, bool]:
    """Classify text using TF-IDF cosine similarity.

    Returns (label, confidence, accepted).
    ``accepted=False`` means the result should be escalated to Layer 3.
    """
    query_vec = vectorizer.transform([text])
    similarities = cosine_similarity(query_vec, matrix).flatten()

    # Sort descending
    sorted_indices = similarities.argsort()[::-1]
    top1_idx = sorted_indices[0]
    top1_score = float(similarities[top1_idx])
    top1_label = labels[top1_idx]

    # Rejection: no match at all
    if top1_score < _MIN_SIMILARITY:
        return top1_label, top1_score, False

    # Rejection: ambiguous (top-1/top-2 ratio too close)
    if len(sorted_indices) > 1:
        top2_score = float(similarities[sorted_indices[1]])
        if top2_score > 0 and (top1_score / top2_score) < _MIN_RATIO:
            return top1_label, top1_score, False

    return top1_label, top1_score, True


# =====================================================================
#  Layer 3 — LLM fallback
# =====================================================================

async def _classify_llm(
    text: str,
    filename: str,
    *,
    title: str = "",
    container: str = "",
) -> tuple[str, float]:
    """Classify via LLM (gpt-4.1-mini). Returns (doc_type, confidence 0.0-1.0)."""
    from ai_engine.extraction.document_intelligence import async_classify_document

    result = await async_classify_document(
        title=title or filename,
        filename=filename,
        container=container,
        content=text[:6000],
    )
    # ClassificationResult.confidence is int 0-100 → normalize to 0.0-1.0
    return result.doc_type, result.confidence / 100.0


# =====================================================================
#  Vehicle type heuristics (from prepare_pdfs_full.py)
# =====================================================================

_V_HEURISTIC: dict[str, list[list[str]]] = {
    "feeder_master": [
        [r"\(offshore\)", r"offshore\s+feeder", r"onshore\s+feeder",
         r"\bCAOFF\b", r"feeder\s+fund", r"feeder\s+vehicle"],
        [r"master\s+fund",
         r"invests\s+substantially\s+all\s+of\s+its\s+assets\s+in\s+the\s+master",
         r"parallel\s+fund", r"master[- ]feeder"],
    ],
    "direct_investment": [
        [r"\bBorrower\s*:", r"\bAdministrative\s+Agent\s*:",
         r"\bFacility\s+Agent\s*:", r"\bObligor\s*:", r"\bGuarantor\s*:",
         r"\bPurchase\s+Price\s*:", r"\bProperty\s+Overview\b",
         r"\bCap\s+Rate\s*:", r"\bRent\s+Roll\b", r"\bEntry\s+(?:Cap|Yield)\b"],
        [r"\bCredit\s+Agreement\b", r"\bFacility\s+Agreement\b",
         r"\bLoan\s+Agreement\b", r"\bTerm\s+Loan\s+Agreement\b",
         r"\bOPPORTUNITY\s+OVERVIEW\b", r"\bINVESTMENT\s+HIGHLIGHTS\b",
         r"\b(?:Submarket|NRSF|Tenant)\s*:", r"\bpsf\b"],
    ],
    "fund_of_funds": [
        [r"\bfund[- ]of[- ]funds\b", r"\bFoF\b", r"\bmulti[- ]manager\b"],
        [r"\bmanager\s+selection\b", r"\bunderlying\s+managers?\b",
         r"\ballocates?\s+to\b", r"\bportfolio\s+of\s+funds\b"],
    ],
    "spv": [
        [r"\bSpecial\s+Purpose\s+(Vehicle|Entity)\b", r"\bSPV\b",
         r"\bSPE\b", r"\bCLO\b", r"\bCDO\b"],
        [r"\bIssuer\b", r"\bCo[- ]Issuer\b", r"\bNotes\s+due\b",
         r"\bSecuritizat", r"\bAsset[- ]Backed\b"],
    ],
    "standalone_fund": [
        [r"\bLimited\s+Partnership\b", r"\bL\.P\.\b", r"\bLimited\s+Partners?\b",
         r"\bFund\s+(?:I{1,3}|IV|V|VI{0,3}|IX|X|\d{1,2})\b"],
        [r"\bCommitment\s+Period\b", r"\bInvestment\s+Period\b",
         r"\bCapital\s+Call\b", r"\bDrawdown\b",
         r"\bCommitted\s+Capital\b", r"\bCapital\s+Committed\b",
         r"\bTotal\s+Commitments?\b", r"\bGross\s+Asset\s+Value\b",
         r"\bcapital\s+deployed\b", r"\bdeployed\s+capital\b",
         r"\bGAV\b",
         r"\bNAV\b", r"\bNet\s+Asset\s+Value\b",
         r"\bNet\s+IRR\b", r"\bGross\s+IRR\b",
         r"\bNet\s+MOIC\b", r"\bGross\s+MOIC\b",
         r"\btotal\s+capital\s+raised\b", r"\bcapital\s+raised\b",
         r"\bportfolio\s+(?:company|companies|overview|update|highlights)\b",
         r"\bfund\s+(?:highlights|overview|update|strategy|performance)\b",
         r"\bquarterly\s+(?:update|report|letter)\b"],
    ],
}

_REIT_RE = re.compile(
    r"\bnon[- ]traded\s+REIT\b"
    r"|\bReal\s+Estate\s+Investment\s+Trust\b"
    r"|\bReal\s+Estate\s+(?:\w+\s+){0,4}Trust\b"
    r"|\bUPREIT\b"
    r"|\bOP\s+Units?\b|\bOperating\s+Partnership\s+Units?\b"
    r"|\bClass\s+[A-Z]\s+(?:shares?|units?|stock)\b",
    re.IGNORECASE,
)


def classify_vehicle_rules(filename: str, text: str) -> str | None:
    """Layer 1 vehicle type: deterministic heuristics from prepare_pdfs_full.py."""
    corpus = filename + "\n" + text

    # Filename override — CAOFF is always feeder (Cayman offshore feeder fund)
    if re.search(r"\bCAOFF\b", filename):
        return "feeder_master"

    # REIT / Real-Estate Trust override
    if _REIT_RE.search(corpus):
        return "standalone_fund"

    for vehicle, groups in _V_HEURISTIC.items():
        for group in groups:
            if re.search("|".join(group), corpus, re.IGNORECASE):
                return vehicle

    return None


def _classify_vehicle_cosine(text: str) -> tuple[str, float, bool]:
    """Layer 2 vehicle type: TF-IDF cosine similarity."""
    vectorizer, labels, matrix = _ensure_vehicle_type_vectorizer()
    return _classify_cosine(text, vectorizer, labels, matrix)


# =====================================================================
#  Public API
# =====================================================================

async def classify(
    text: str,
    filename: str,
    *,
    title: str = "",
    container: str = "",
) -> HybridClassificationResult:
    """Three-layer hybrid classification. Returns doc_type + vehicle_type.

    Layer 1: Deterministic rules (filename patterns + content patterns).
    Layer 2: TF-IDF cosine similarity against synthetic exemplars.
    Layer 3: LLM fallback (gpt-4.1-mini) for genuinely ambiguous cases.
    """
    doc_type: str | None = None
    vehicle_type: str = "other"
    confidence: float = 1.0
    layer: int = 1
    model_name: str = "rules"

    # ── Layer 1: Filename rules ──────────────────────────────────────
    # Normalize underscores to spaces so \b word boundaries work with
    # filenames like "BridgeInvest_Investment Memo_Balfour Hotel.pdf"
    fn_normalized = filename.replace("_", " ")
    for pattern, dt in _FILENAME_RULES:
        if pattern.search(fn_normalized):
            doc_type = dt
            logger.info("Layer 1 filename match: %s → %s", filename, dt)
            break

    # ── Layer 1: Content rules (first 500 chars) ────────────────────
    if doc_type is None and text:
        head = text[:500]
        for pattern, dt in _CONTENT_RULES:
            if pattern.search(head):
                doc_type = dt
                logger.info("Layer 1 content match: %s → %s", filename, dt)
                break

    # ── Layer 2: TF-IDF cosine similarity ────────────────────────────
    if doc_type is None and text:
        layer = 2
        model_name = "embedding-v2"
        window = _ocr_window(text)
        query = f"Filename: {filename}\n\n{window}"

        # sklearn transform/cosine_similarity IS thread-safe on fitted
        # estimators — no lock needed.  Wrap in to_thread to avoid
        # blocking the event loop on large texts.
        vectorizer, labels, matrix = _ensure_doc_type_vectorizer()
        dt, score, accepted = await asyncio.to_thread(
            _classify_cosine, query, vectorizer, labels, matrix,
        )
        confidence = score

        if accepted:
            doc_type = dt
            logger.info(
                "Layer 2 cosine match: %s → %s (score=%.4f)", filename, dt, score,
            )
        else:
            logger.info(
                "Layer 2 rejected: %s → %s (score=%.4f, escalating to Layer 3)",
                filename, dt, score,
            )

    # ── Layer 3: LLM fallback ────────────────────────────────────────
    if doc_type is None:
        layer = 3
        model_name = "gpt-4.1-mini"
        doc_type, confidence = await _classify_llm(
            text, filename, title=title, container=container,
        )
        logger.info(
            "Layer 3 LLM classification: %s → %s (confidence=%.2f)",
            filename, doc_type, confidence,
        )

    # ── Validate doc_type ────────────────────────────────────────────
    if doc_type not in CANONICAL_DOC_TYPES:
        logger.warning(
            "Invalid doc_type '%s' from layer %d for '%s' — falling back to 'other'",
            doc_type, layer, filename,
        )
        doc_type = "other"

    # ── Vehicle type classification ──────────────────────────────────
    if doc_type in NO_VEHICLE_DOC_TYPES:
        vehicle_type = "other"
    else:
        # Layer 1: heuristic rules
        vt = classify_vehicle_rules(filename, _ocr_window(text) if text else "")
        if vt is not None and vt in CANONICAL_VEHICLE_TYPES:
            vehicle_type = vt
        elif text:
            # Layer 2: TF-IDF cosine similarity
            window = _ocr_window(text)
            query = f"Filename: {filename}\n\n{window}"
            vt_cosine, _, accepted = await asyncio.to_thread(
                _classify_vehicle_cosine, query,
            )
            if accepted and vt_cosine in CANONICAL_VEHICLE_TYPES:
                vehicle_type = vt_cosine

    return HybridClassificationResult(
        doc_type=doc_type,
        vehicle_type=vehicle_type,
        confidence=confidence,
        layer=layer,
        model_name=model_name,
    )
