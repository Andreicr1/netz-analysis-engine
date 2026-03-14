"""CU PDF Preparation — Full Pipeline: Mistral OCR + Cohere Rerank + Semantic Chunking
====================================================================================
Stage 1 — Mistral Document AI (OCR, base64, handles scanned docs, table_format=html)
Stage 2 — Cohere Rerank → doc_type (31 candidates, zero-shot classification)
Stage 3 — Cohere Rerank → vehicle_type (multi-type candidates)
Stage 4 — Multi-signal heuristic override + doc_type-based vehicle override
Stage 5 — Governance detection (deterministic regex, zero API cost)
Stage 6 — Semantic markdown chunking (semantic_chunker.py)
           Tables atomic, header breadcrumbs, adaptive size by doc_type

Output per folder:
    cu_chunks.json              — all chunks ready for Stage 7 (embedding)
    cu_preparation_report.json  — classification results without chunks

Entity context:
    fund_context.json per deal folder — populated by entity_bootstrap.py
    _FUND_ALIASES starts empty, populated at runtime from fund_context.json

Environment variables:
    MISTRAL_API_KEY — public Mistral API key (OCR)
    AZURE_API_KEY   — Azure AI Foundry key (Cohere Rerank)

Usage:
    python prepare_pdfs_full.py --file "C:/Deals/Blue Owl/deck.pdf" --dry-run
    python prepare_pdfs_full.py --folder "C:/Deals/Chicago Atlantic" --dry-run
    python prepare_pdfs_full.py --folder "C:/Deals/Chicago Atlantic"
"""

import base64
import json
import logging
import re
import time
from pathlib import Path

import fitz  # pymupdf
import requests

from ai_engine.extraction.semantic_chunker import chunk_document, print_chunk_summary
from ai_engine.prompts import prompt_registry

logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURAÇÃO
# ============================================================

MISTRAL_OCR_URL  = "https://api.mistral.ai/v1/ocr"
MISTRAL_MODEL    = "mistral-ocr-latest"

COHERE_RERANK_URL = "https://netzai.services.ai.azure.com/providers/cohere/v2/rerank"
COHERE_MODEL      = "Cohere-rerank-v4.0-pro"

# Limites reais da API Mistral OCR (console Mistral)
# https://docs.mistral.ai/capabilities/document_ai/basic_ocr
# API pública: 1.000 páginas / 250 MB por chamada.
MISTRAL_MAX_PAGES    = 1000   # limite da API pública Mistral
MISTRAL_MAX_FILE_MB  = 250     # limite de tamanho de arquivo (MB) — console Mistral
MISTRAL_MAX_FILE_BYTES = MISTRAL_MAX_FILE_MB * 1024 * 1024

# Padrão: envia o PDF inteiro (sem truncar). Pode ser sobrescrito via --max-pages.
DEFAULT_MAX_PAGES = MISTRAL_MAX_PAGES

SIDECAR_MIN_CONFIDENCE = 7
MIN_PAGE_WORDS = 10

# OCR window enviada ao Cohere Rerank como query (head + tail).
# Head: início do doc = fund name, parties, doc type header.
# Tail: final do doc = assinatura, entity declarations, service provider pages.
# Cohere best-practice (Context7): candidate descriptions são curtas (~150 tokens),
# max_tokens_per_doc=512 evita chunking desnecessário.
RERANK_OCR_HEAD_CHARS = 5000   # primeiros 5k chars — cabeçalho e partes do doc
RERANK_OCR_TAIL_CHARS = 2000   # últimos 2k chars  — assinaturas e entidades finais
RERANK_QUERY_CHARS    = 8500   # safety cap total da query (head+tail+prefix)

# ── Document Q&A fallback (Mistral chat/completions) ──────────────────────────
# Triggered when Cohere doc_type relevance score is below this threshold.
# Score 0.35 ≈ confidence 4/10 — indicates Cohere could not find a clear match.
MISTRAL_CHAT_URL          = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_CLASSIFY_MODEL    = "mistral-small-latest"
COHERE_FALLBACK_THRESHOLD = 0.35   # doc_score < this → trigger Document Q&A
QNA_CLASSIFY_CHARS        = 6000   # chars of OCR sent in the classification prompt

# ============================================================
# DOCUMENTOS EXCLUÍDOS DO PIPELINE
# Formulários padrão de compliance fiscal/regulatório não são relevantes
# para análise de deals e poluem o corpus. São detectados pelo nome do arquivo.
# ============================================================

_SKIP_PATTERNS = re.compile(
    r"W-8BEN"
    r"|W-9"
    r"|FATCA"
    r"|CRS.{0,10}Self.{0,10}Cert"
    r"|Self.{0,10}Certification"
    r"|KYC.{0,10}Form"
    r"|AML.{0,10}Form"
    r"|Beneficial.{0,10}Owner"
    r"|Anti.Money.Laundering",
    re.IGNORECASE,
)


def is_skippable(filename: str) -> bool:
    """Retorna True se o arquivo é um formulário padrão que deve ser ignorado."""
    return bool(_SKIP_PATTERNS.search(filename))

# ============================================================
# DOC_TYPE — candidatos para o Cohere Rerank
# Cada descrição é um "documento" que o reranker vai comparar ao texto do PDF
# Quanto mais específica e rica a descrição, melhor a classificação
# ============================================================

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
        "Investment memorandum, credit memo, deal memo, investment committee memo, "
        "or due diligence report on a SPECIFIC named company or asset. Contains "
        "investment thesis, financial analysis, risk factors, and recommendation "
        "for a particular deal or potential investment."
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

# ============================================================
# VEHICLE_TYPE — candidatos para o Cohere Rerank
# ============================================================

VEHICLE_TYPE_CANDIDATES: dict[str, str] = {
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

# ============================================================
# GOVERNANCE — pattern matching (determinístico, sem custo de API)
# ============================================================

_GOV_PATTERNS: list[tuple[str, str]] = [
    ("side_letter",              r"\bside\s+letter\b"),
    ("most_favored_nation",      r"\bmost[- ]favored[- ]nation\b|\bMFN\b"),
    ("key_person_clause",        r"\bkey[- ]person\b|\bkeyman\b"),
    ("clawback",                 r"\bclawback\b|\bclaw[- ]back\b"),
    ("carried_interest",         r"\bcarried\s+interest\b|\bperformance\s+(?:fee|allocation)\b|\bpromote\s+interest\b"),
    ("fee_rebate",               r"\bfee\s+rebate\b|\bfee\s+waiver\b|\bmanagement\s+fee\s+offset\b"),
    ("gating_provision",         r"\bgating\s+provision\b|\bredemption\s+gate\b"),
    ("suspension_of_redemptions",r"\bsuspension\s+of\s+redemption\b|\bsuspend\s+redemption\b"),
    ("concentration_limit",      r"\bconcentration\s+limit\b|\bconcentration\s+cap\b"),
    ("board_override",           r"\bboard\s+(override|resolution|approval)\b"),
    ("investment_limit_exception",r"\binvestment\s+limit\s+exception\b|\bpolicy\s+exception\b"),
    ("policy_override",          r"\bpolicy\s+override\b"),
    ("conflicts_of_interest",    r"\bconflicts?\s+of\s+interest\b"),
    ("related_party",            r"\brelated\s+party\b|\brelated[- ]party\s+transaction\b"),
    ("fund_of_funds_structure",  r"\bfund[- ]of[- ]funds\b|\bFoF\b|\bunderlying\s+fund\b"),
]

_GOVERNANCE_CRITICAL_PATTERNS = re.compile(
    r"\bside\s+letter\b"
    r"|\bmost[- ]favored[- ]nation\b|\bMFN\b"
    r"|\bfee\s+rebate\b|\bfee\s+waiver\b"
    r"|\bboard\s+override\b"
    r"|\binvestment\s+limit\s+exception\b"
    r"|\bfund[- ]of[- ]funds\b",
    re.IGNORECASE,
)


def detect_governance(text: str) -> tuple[bool, list[str]]:
    flags = []
    for flag, pattern in _GOV_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            flags.append(flag)
    critical = bool(_GOVERNANCE_CRITICAL_PATTERNS.search(text))
    return critical, flags


# ============================================================
# HEURÍSTICA DE VEHICLE_TYPE (multi-sinal)
# ============================================================

# ============================================================
# FILENAME HINTS — strong doc_type signals from the filename
# Table-driven: checked in priority order, first match wins.
# More specific patterns (LPA, Credit Policy) before generic (Q1/Q2).
# ============================================================

_FILENAME_HINT_TABLE: list[tuple[re.Pattern, str, str]] = [
    # --- Legal documents (most specific) ---
    (re.compile(r"\bLPA\b|\bLimited\s+Partnership\s+Agreement\b", re.I),
     "legal_lpa",
     "HINT: filename contains 'LPA' or 'Limited Partnership Agreement' — "
     "this document is almost certainly legal_lpa. "
     "Strongly prefer legal_lpa over fund_presentation, fund_policy, or fund_profile."),

    (re.compile(r"\bSide\s+Letter\b", re.I),
     "legal_side_letter",
     "HINT: filename contains 'Side Letter' — "
     "this document is almost certainly legal_side_letter. "
     "Strongly prefer legal_side_letter over legal_agreement or attachment."),

    (re.compile(r"\bSubscription\s+(?:Booklet|Agreement|Doc)\b", re.I),
     "legal_subscription",
     "HINT: filename contains 'Subscription Booklet/Agreement' — "
     "this document is almost certainly legal_subscription. "
     "Strongly prefer legal_subscription over regulatory_compliance."),

    (re.compile(r"\bCredit\s+Agreement\b|\bLoan\s+Agreement\b|\bFacility\s+Agreement\b", re.I),
     "legal_credit_agreement",
     "HINT: filename contains 'Credit/Loan/Facility Agreement' — "
     "this document is almost certainly legal_credit_agreement."),

    (re.compile(r"\bMaster\s+Participation\b|\bParticipation\s+Agreement\b", re.I),
     "legal_agreement",
     "HINT: filename contains 'Master Participation Agreement' — "
     "this document is almost certainly legal_agreement. "
     "Strongly prefer legal_agreement over fund_presentation or fund_profile."),

    # --- Financial ---
    (re.compile(r"\bFinancial\s+Statements?\b|\bAudit(?:ed)?\s+(?:Financial|Report)\b", re.I),
     "financial_statements",
     "HINT: filename contains 'Financial Statements' — "
     "this document is almost certainly financial_statements. "
     "Strongly prefer financial_statements over fund_policy, fund_presentation, or credit_policy."),

    # --- Fund documents (specific before generic) ---
    (re.compile(r"\bFact[\s_\-]?Card\b|\bFact[\s_\-]?Sheet\b", re.I),
     "fund_profile",
     "HINT: filename contains 'Fact Card' or 'Fact Sheet' — "
     "this document is almost certainly fund_profile. "
     "Strongly prefer fund_profile over fund_policy, fund_structure, or fund_presentation."),

    (re.compile(r"\bFund\s+Profile\b|\bFund\s+Overview\b", re.I),
     "fund_profile",
     "HINT: filename contains 'Fund Profile' or 'Fund Overview' — "
     "this document is almost certainly fund_profile. "
     "Strongly prefer fund_profile over fund_policy, fund_presentation, or strategy_profile."),

    (re.compile(r"\bStructure\s+(?:Chart|Diagram)\b|\bEntity\s+Chart\b", re.I),
     "fund_structure",
     "HINT: filename contains 'Structure Chart' or 'Structure Diagram' — "
     "this document is almost certainly fund_structure. "
     "Strongly prefer fund_structure over fund_presentation or org_chart."),

    (re.compile(r"\bStrategy\s+(?:Profile|Overview)\b", re.I),
     "strategy_profile",
     "HINT: filename contains 'Strategy Profile' or 'Strategy Overview' — "
     "this document is almost certainly strategy_profile. "
     "Strongly prefer strategy_profile over fund_profile, fund_presentation, or operational_monitoring."),

    (re.compile(r"\b(?:Podcast|Interview|Webinar|Commentary|Market[\s_\-]Update|White[\s_\-]Paper)\b", re.I),
     "strategy_profile",
     "HINT: filename contains thought leadership keywords — "
     "this document is almost certainly strategy_profile. "
     "Strongly prefer strategy_profile over fund_structure or fund_presentation."),

    (re.compile(r"\bCapital\s+Rais(?:ing|e)\b|\bFundraising\b|\bRoadshow\b", re.I),
     "capital_raising",
     "HINT: filename contains capital raising keywords — "
     "this document is almost certainly capital_raising. "
     "Strongly prefer capital_raising over fund_presentation."),

    # --- Policy / Operational ---
    (re.compile(r"\bCredit\s+Policy\b|\bUnderwriting\s+(?:Guide|Policy|Manual)\b", re.I),
     "credit_policy",
     "HINT: filename contains 'Credit Policy' or 'Underwriting Guidelines' — "
     "this document is almost certainly credit_policy. "
     "Strongly prefer credit_policy over fund_policy, attachment, or other."),

    (re.compile(r"\bCompliance\s+(?:Manual|Program)\b|\bSupervisory\s+Procedures?\b", re.I),
     "fund_policy",
     "HINT: filename contains 'Compliance Manual' or 'Compliance Program' — "
     "this document is almost certainly fund_policy (internal compliance governance). "
     "Strongly prefer fund_policy over regulatory_compliance or operational_service."),

    (re.compile(r"\bEmployee\s+Handbook\b|\bHR\s+(?:Policy|Manual|Handbook)\b", re.I),
     "operational_service",
     "HINT: filename contains 'Employee Handbook' or 'HR Policy' — "
     "this document is almost certainly operational_service. "
     "Strongly prefer operational_service over org_chart, attachment, or other."),

    (re.compile(r"\bIT\s+(?:Policy|Disaster|Security)\b|\bBusiness\s+Continuity\b|\bDisaster\s+Recovery\b", re.I),
     "operational_service",
     "HINT: filename contains IT/disaster recovery/business continuity keywords — "
     "this document is almost certainly operational_service. "
     "Strongly prefer operational_service over attachment or other."),

    (re.compile(r"\bCode\s+of\s+(?:Ethics|Conduct)\b", re.I),
     "operational_service",
     "HINT: filename contains 'Code of Ethics' or 'Code of Conduct' — "
     "this document is almost certainly operational_service. "
     "Strongly prefer operational_service over attachment or fund_policy."),

    (re.compile(r"\bOrg(?:anization(?:al)?)?[\s_\-]?Chart\b", re.I),
     "org_chart",
     "HINT: filename contains 'Org Chart' — "
     "this document is almost certainly org_chart. "
     "Strongly prefer org_chart over fund_structure or attachment."),

    (re.compile(r"\bRisk\s+Assessment\b", re.I),
     "risk_assessment",
     "HINT: filename contains 'Risk Assessment' — "
     "this document is almost certainly risk_assessment. "
     "Strongly prefer risk_assessment over fund_policy or credit_policy."),

    (re.compile(r"\bQDD\b", re.I),
     "regulatory_qdd",
     "HINT: filename contains 'QDD' — "
     "this document is likely regulatory_qdd or QDD due diligence. "
     "Consider regulatory_qdd over operational_service."),

    # --- Deal / investment-level intro materials ---
    (re.compile(r"\bIntro\s+Materials?(?:\b|_)", re.I),
     "investment_memo",
     "HINT: filename contains 'Intro Materials' — "
     "this document is almost certainly investment_memo (deal intro for a specific asset). "
     "Strongly prefer investment_memo over legal_term_sheet or fund_presentation."),

    # --- Fund pipeline / condensed presentations ---
    (re.compile(r"\bPipeline\b|\bSourcing\b", re.I),
     "fund_presentation",
     "HINT: filename contains 'Pipeline' or 'Sourcing' — "
     "this document is almost certainly fund_presentation (fund pipeline overview). "
     "Strongly prefer fund_presentation over legal_term_sheet."),

    (re.compile(r"\bCondensed\s+Version\b|\bBrochure\b|\bTeaser\b", re.I),
     "fund_presentation",
     "HINT: filename contains 'Condensed Version', 'Brochure', or 'Teaser' — "
     "this document is almost certainly fund_presentation. "
     "Strongly prefer fund_presentation over legal_term_sheet or attachment."),

    (re.compile(r"\bPresentation\b|\bInvestor\s+Deck\b|\bPitch\s*Book\b", re.I),
     "fund_presentation",
     "HINT: filename contains 'Presentation', 'Investor Deck', or 'Pitch Book' — "
     "this document is almost certainly fund_presentation. "
     "Strongly prefer fund_presentation over legal_term_sheet."),

    # --- Quarterly / periodic (WEAKEST — checked last) ---
    (re.compile(
        r"\b(?:1Q|2Q|3Q|4Q|Q1|Q2|Q3|Q4|YTD)[\s_\-]?\d{2,4}\b"
        r"|\b\d{2,4}[\s_\-]?(?:1Q|2Q|3Q|4Q|Q1|Q2|Q3|Q4)\b"
        r"|\b\d{4}[\s_\-]?(?:annual|year.end|semi.annual)\b",
        re.I),
     "fund_presentation",
     "HINT: filename contains a quarterly period indicator — "
     "this document might be fund_presentation (periodic investor update). "
     "Consider fund_presentation but verify with content."),
]


def filename_hint(filename: str) -> tuple[str | None, str | None]:
    """Returns (doc_type_hint, hint_text) or (None, None).

    Checks filename against _FILENAME_HINT_TABLE in priority order.
    First match wins — specific keywords are checked before generic date patterns.
    """
    for pattern, doc_type, hint_text in _FILENAME_HINT_TABLE:
        if pattern.search(filename):
            return doc_type, hint_text
    return None, None


# doc_types for which vehicle_type is not applicable → force "other"
_NO_VEHICLE_DOC_TYPES = frozenset({
    "strategy_profile", "org_chart", "attachment",
    "credit_policy", "operational_service", "operational_insurance",
    "risk_assessment", "regulatory_cima", "regulatory_compliance",
    "regulatory_qdd", "other",
    "legal_side_letter",  # governs investor terms, not vehicle structure
    "capital_raising",    # describes a fund but is not the vehicle
    "fund_structure",     # diagram of vehicles, not a vehicle itself
    "fund_profile",       # describes a fund, is not the vehicle
    "fund_policy",        # internal governance doc, not a vehicle
    "legal_agreement",    # bilateral contract, not a fund vehicle
})

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
         # Real estate deal markers
         r"\bPurchase\s+Price\s*:", r"\bProperty\s+Overview\b",
         r"\bCap\s+Rate\s*:", r"\bRent\s+Roll\b", r"\bEntry\s+(?:Cap|Yield)\b"],
        [r"\bCredit\s+Agreement\b", r"\bFacility\s+Agreement\b",
         r"\bLoan\s+Agreement\b", r"\bTerm\s+Loan\s+Agreement\b",
         # Real estate deal language
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
        # Grupo 1 — identificadores do veículo (nome do fundo ou estrutura LP)
        [r"\bLimited\s+Partnership\b", r"\bL\.P\.\b", r"\bLimited\s+Partners?\b",
         r"\bFund\s+(?:I{1,3}|IV|V|VI{0,3}|IX|X|\d{1,2})\b"],
        # Grupo 2 — linguagem de fundo (aceita LPA *e* apresentação de investidores)
        [r"\bCommitment\s+Period\b", r"\bInvestment\s+Period\b",
         r"\bCapital\s+Call\b", r"\bDrawdown\b",
         r"\bCommitted\s+Capital\b", r"\bCapital\s+Committed\b",
         r"\bTotal\s+Commitments?\b", r"\bGross\s+Asset\s+Value\b",
         r"\bcapital\s+deployed\b", r"\bdeployed\s+capital\b",
         r"\bGAV\b",
         # Linguagem de quarterly decks / investor presentations
         r"\bNAV\b", r"\bNet\s+Asset\s+Value\b",
         r"\bNet\s+IRR\b", r"\bGross\s+IRR\b",
         r"\bNet\s+MOIC\b", r"\bGross\s+MOIC\b",
         r"\btotal\s+capital\s+raised\b", r"\bcapital\s+raised\b",
         r"\bportfolio\s+(?:company|companies|overview|update|highlights)\b",
         r"\bfund\s+(?:highlights|overview|update|strategy|performance)\b",
         r"\bquarterly\s+(?:update|report|letter)\b"],
    ],
}


def vehicle_hint(filename: str, text: str, debug: bool = False) -> tuple[str | None, str | None]:
    corpus = filename + "\n" + text

    # Filename override — CAOFF é sempre feeder (Cayman offshore feeder fund)
    if re.search(r"\bCAOFF\b", filename):
        return "feeder_master", "feeder_master: signals -> ['CAOFF filename override']"

    # REIT / Real-Estate Trust override — non-traded REITs and real-estate trusts
    # have distribution and share-class language (OP units, distribution waterfalls,
    # Class A/T/D shares) that trips the feeder_master and spv heuristics.
    # A REIT or real-estate trust is always a standalone vehicle.
    _REIT_RE = re.compile(
        r"\bnon[- ]traded\s+REIT\b"
        r"|\bReal\s+Estate\s+Investment\s+Trust\b"
        r"|\bReal\s+Estate\s+(?:\w+\s+){0,4}Trust\b"  # entity names like "Real Estate Net Lease Trust"
        r"|\bUPREIT\b"
        r"|\bOP\s+Units?\b|\bOperating\s+Partnership\s+Units?\b"
        r"|\bClass\s+[A-Z]\s+(?:shares?|units?|stock)\b",
        re.IGNORECASE,
    )
    if _REIT_RE.search(corpus):
        return "standalone_fund", "standalone_fund: signals -> ['REIT override']"

    if debug:
        # Mostra quais termos-chave do standalone_fund estão presentes no corpus
        _probes = [
            "Investment Period", "Commitment Period", "Capital Call", "Drawdown",
            "Committed Capital", "Gross Asset Value", "GAV", "capital deployed",
            "Limited Partnership", "L.P.",
            "NAV", "Net Asset Value", "Net IRR", "Gross IRR", "capital raised",
            "portfolio company", "fund highlights", "quarterly update",
        ]
        hits = [t for t in _probes if re.search(re.escape(t), corpus, re.IGNORECASE)]
        logger.info("[hint-probe] termos encontrados: %s", hits)
        logger.info("[hint-ocr-sample] primeiros 800 chars do OCR:")
        logger.info("%s", corpus[len(filename)+1:len(filename)+800])
    for vehicle, groups in _V_HEURISTIC.items():
        matched: list[str] = []
        for i, group in enumerate(groups):
            m = re.search("|".join(group), corpus, re.IGNORECASE)
            if m:
                matched.append(m.group(0).strip())
            elif debug:
                logger.info("[hint] %s grupo %d: SEM MATCH (1o padrao: %s)", vehicle, i + 1, group[0][:60])
        if debug:
            logger.info("[hint] %s: %d/%d grupos matched", vehicle, len(matched), len(groups))
        if len(matched) >= len(groups):
            return vehicle, f"{vehicle}: signals -> {matched}"
    return None, None


# ============================================================
# ESTÁGIO 1 — MISTRAL OCR
# ============================================================

def _pdf_batch_to_base64(pdf_path: str, start_page: int, end_page: int) -> str:
    """Extrai páginas [start_page, end_page) do PDF e retorna como base64.
    end_page é exclusivo (Python slice-style).
    """
    doc = fitz.open(pdf_path)
    out = fitz.open()
    for p in range(start_page, end_page):
        out.insert_pdf(doc, from_page=p, to_page=p)
    data = out.tobytes()
    out.close()
    doc.close()

    if len(data) > MISTRAL_MAX_FILE_BYTES:
        raise ValueError(
            f"Lote págs {start_page+1}–{end_page} excede {MISTRAL_MAX_FILE_MB} MB "
            "(PDF com muitas imagens de alta resolução). Comprima o arquivo ou reduza max_pages.",
        )

    return base64.b64encode(data).decode()


def extract_ocr_text(
    pdf_path: str,
    mistral_key: str,
    batch_size: int = MISTRAL_MAX_PAGES,
) -> tuple[str, int, int]:
    """Extrai texto OCR do PDF COMPLETO, dividindo automaticamente em lotes de
    `batch_size` páginas (padrão = 1000, limite da API pública Mistral).

    Para PDFs normais (≤ 1000 págs) o documento inteiro é enviado em uma única
    chamada. Documentos maiores são particionados automaticamente.
    Para cada lote: converte para base64 → Mistral OCR → markdown.
    Concatena todos os textos na ordem original.

    Retorna:
        ocr_text    : texto completo do documento
        total_pages : número total de páginas do PDF
        batches     : quantos lotes foram enviados ao Mistral
    """
    doc = fitz.open(pdf_path)
    total = len(doc)
    doc.close()

    # Monta lista de (start, end) para cada lote
    ranges = [(s, min(s + batch_size, total)) for s in range(0, total, batch_size)]

    texts: list[str] = []
    for i, (start, end) in enumerate(ranges):
        label = f"lote {i+1}/{len(ranges)} (págs {start+1}–{end})"
        if len(ranges) > 1:
            logger.info("OCR %s...", label)

        t0_b = time.time()
        b64  = _pdf_batch_to_base64(pdf_path, start, end)
        text = call_mistral_ocr(b64, mistral_key)
        elapsed = round(time.time() - t0_b, 1)

        if len(ranges) > 1:
            logger.info("OCR %s → %d chars | %ss", label, len(text), elapsed)

        texts.append(text)

    return "\n\n".join(texts), total, len(ranges)



def call_mistral_ocr(pdf_b64: str, mistral_key: str) -> str:
    """Chama a API pública Mistral OCR e retorna o texto extraído como markdown.
    Capacidades utilizadas:
      - table_format: "html" → tabelas financeiras extraídas como HTML (mais preciso)
      - include_image_base64: False → não retorna imagens (reduz payload)
    Limites da API pública Mistral: 1.000 páginas / 250 MB por chamada.
    Ref: https://docs.mistral.ai/capabilities/document_ai/basic_ocr
    """
    payload = {
        "model": MISTRAL_MODEL,
        "document": {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{pdf_b64}",
        },
        "table_format": "html",       # tabelas financeiras em HTML (mais fiel que markdown)
        "include_image_base64": False,
    }

    resp = requests.post(
        MISTRAL_OCR_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {mistral_key}",
        },
        json=payload,
        timeout=120,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Mistral OCR HTTP {resp.status_code}: {resp.text[:500]}")

    data = resp.json()

    # Coalesce text from pages — replace table placeholders with actual HTML
    pages = data.get("pages", [])
    if pages:
        parts: list[str] = []
        for p in pages:
            md = p.get("markdown", "") or p.get("text", "")
            # Replace [tbl-X.html](tbl-X.html) placeholders with real HTML content
            for tbl in p.get("tables", []):
                tbl_id  = tbl.get("id", "")
                content = tbl.get("content", "")
                if tbl_id and content:
                    md = md.replace(f"[{tbl_id}]({tbl_id})", content)
            parts.append(md)
        return "\n\n".join(parts)

    return data.get("text", "") or data.get("content", "")


# ============================================================
# ESTÁGIO 2/3 — COHERE RERANK como zero-shot classifier
# ============================================================

def _rerank_ocr_window(ocr_text: str) -> str:
    """Extrai janela head+tail do OCR para a query do Cohere Rerank.

    Head (primeiros RERANK_OCR_HEAD_CHARS): nome do fundo, partes, tipo do doc.
    Tail (últimos RERANK_OCR_TAIL_CHARS): bloco de assinatura, declarações de
    entidade, páginas de estrutura — frequentes no final de docs de marketing.

    Para docs curtos retorna o texto completo sem separador.
    """
    total = RERANK_OCR_HEAD_CHARS + RERANK_OCR_TAIL_CHARS
    if len(ocr_text) <= total:
        return ocr_text
    head = ocr_text[:RERANK_OCR_HEAD_CHARS]
    tail = ocr_text[-RERANK_OCR_TAIL_CHARS:]
    return head + "\n\n[...]\n\n" + tail


def cohere_classify(
    query: str,
    candidates: dict[str, str],
    api_key: str,
    top_n: int | None = None,
) -> list[tuple[str, float]]:
    """Usa o Cohere Rerank para classificar o texto contra os candidatos.
    query = texto do documento (pré-processado via _rerank_ocr_window)
    candidates = {label: description}
    Retorna lista ordenada de (label, relevance_score).
    """
    labels = list(candidates.keys())
    docs   = list(candidates.values())

    payload: dict = {
        "model":              COHERE_MODEL,
        "query":              query[:RERANK_QUERY_CHARS],  # safety cap
        "documents":          docs,
        "max_tokens_per_doc": 512,   # descriptions are short — avoid unnecessary chunking
    }
    if top_n:
        payload["top_n"] = top_n

    resp = requests.post(
        COHERE_RERANK_URL,
        headers={
            "Content-Type": "application/json",
            "api-key":      api_key,
        },
        json=payload,
        timeout=60,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Cohere Rerank HTTP {resp.status_code}: {resp.text[:500]}")

    results = resp.json().get("results", [])
    # results[i] = {"index": int, "relevance_score": float}
    ranked = sorted(results, key=lambda r: r["relevance_score"], reverse=True)
    return [(labels[r["index"]], round(r["relevance_score"], 4)) for r in ranked]


def classify_doc_type(ocr_text: str, api_key: str, filename: str,
                     subfolder_hint: str = "") -> tuple[str, float, list]:
    """Classify doc_type via Cohere Rerank. Returns (doc_type, score, top3)."""
    hint_type, hint_text = filename_hint(filename)

    # Hard override — filename hints that are unambiguous skip Cohere entirely
    _HARD_OVERRIDE_HINTS = frozenset({
        "legal_lpa", "legal_side_letter", "legal_subscription",
        "legal_credit_agreement", "legal_agreement",
        "financial_statements", "fund_profile", "fund_structure",
        "credit_policy", "fund_policy", "operational_service",
        "org_chart", "risk_assessment",
    })
    if hint_type in _HARD_OVERRIDE_HINTS:
        return hint_type, 1.0, [(hint_type, 1.0)]

    # Always prepend filename — it's a strong classification signal
    query = f"Filename: {filename}\n\n"
    if hint_text:
        query += hint_text + "\n\n"

    # Subfolder-based doc_type hint from deal folder structure
    if subfolder_hint:
        query += subfolder_hint + "\n\n"

    # Inject deal-level context from deal_context.json
    deal_ctx = _build_deal_context_string()
    if deal_ctx:
        query += deal_ctx + "\n\n"

    # Inject Netz ecosystem context when known entities are detected
    if _NETZ_ENTITY_DETECT_RE.search(ocr_text[:5000]) or _NETZ_ENTITY_DETECT_RE.search(filename):
        query += _NETZ_ENTITY_CONTEXT + "\n\n"

    query += _rerank_ocr_window(ocr_text)

    ranked = cohere_classify(query, DOC_TYPE_CANDIDATES, api_key, top_n=3)
    return ranked[0][0], ranked[0][1], ranked  # (label, score, top3)


def classify_vehicle_type(ocr_text: str, api_key: str, filename: str,
                         subfolder_hint: str = "") -> tuple[str, float, list]:
    """Classifica vehicle_type via Cohere Rerank. Retorna (vehicle_type, score, top3)."""
    # Prepend filename — fund numbering (Fund VI, Fund II) is a strong standalone_fund signal
    query = f"Filename: {filename}\n\n"

    # Subfolder-based vehicle hint from deal folder structure
    if subfolder_hint:
        query += subfolder_hint + "\n\n"

    # Inject deal-level context from deal_context.json
    deal_ctx = _build_deal_context_string()
    if deal_ctx:
        query += deal_ctx + "\n\n"

    # Inject Netz ecosystem context when known entities are detected
    if _NETZ_ENTITY_DETECT_RE.search(ocr_text[:5000]) or _NETZ_ENTITY_DETECT_RE.search(filename):
        query += _NETZ_ENTITY_CONTEXT + "\n\n"

    query += _rerank_ocr_window(ocr_text)
    ranked = cohere_classify(query, VEHICLE_TYPE_CANDIDATES, api_key, top_n=3)
    return ranked[0][0], ranked[0][1], ranked  # (label, score, top3)


def classify_with_document_qna(
    ocr_text: str,
    mistral_key: str,
    filename: str,
) -> tuple[str, str, float]:
    """Fallback classifier using Mistral Document Q&A (chat/completions + JSON mode).
    Called when Cohere doc_type score < COHERE_FALLBACK_THRESHOLD.

    Uses the already-extracted OCR text (no re-upload) to ask mistral-small-latest
    for structured classification via response_format=json_object.

    Returns:
        (doc_type, vehicle_type, confidence_0_to_1)
    All values are validated against the canonical candidate lists.

    """
    doc_type_list    = list(DOC_TYPE_CANDIDATES.keys())
    vehicle_type_list = list(VEHICLE_TYPE_CANDIDATES.keys())

    system_prompt, user_prompt = prompt_registry.render_pair(
        "qna_classify",
        subdirectory="extraction",
        filename=filename,
        qna_classify_chars=QNA_CLASSIFY_CHARS,
        ocr_text_excerpt=ocr_text[:QNA_CLASSIFY_CHARS],
        doc_type_list=doc_type_list,
        vehicle_type_list=vehicle_type_list,
    )

    payload = {
        "model":           MISTRAL_CLASSIFY_MODEL,
        "messages":        [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature":     0,
        "max_tokens":      80,
    }

    resp = requests.post(
        MISTRAL_CHAT_URL,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {mistral_key}",
        },
        json=payload,
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Mistral QnA HTTP {resp.status_code}: {resp.text[:300]}")

    content = resp.json()["choices"][0]["message"]["content"]
    parsed  = json.loads(content)

    dt   = parsed.get("doc_type",     "other")
    vt   = parsed.get("vehicle_type", "other")
    conf = parsed.get("confidence",   5)

    # Validate against canonical lists
    if dt not in DOC_TYPE_CANDIDATES:
        dt = "other"
    if vt not in VEHICLE_TYPE_CANDIDATES:
        vt = "other"

    score = max(0.1, min(1.0, int(conf) / 10))
    return dt, vt, score


# ============================================================
# NETZ FUND ECOSYSTEM — known entities for name extraction & context
# ============================================================

# Entities that are SERVICE PROVIDERS / MANAGERS — not fund names.
# When these appear as the first filename segment, skip to next segment
# to find the actual deal/fund name.
# Pattern: (compiled_regex, canonical_name, role)
_NETZ_NON_FUND_ENTITIES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"^Previse\b", re.I),
     "Previse Capital Partners SA",
     "Former Investment Manager (merged into Necker Finance)"),
    (re.compile(r"^Necker\s*Finance\b", re.I),
     "Necker Finance (Suisse) SA",
     "Current Investment Manager"),
    (re.compile(r"^Netz\s+Asset\b", re.I),
     "Netz Asset Gestão de Recursos LTDA",
     "Sponsor / Brazilian Asset Manager"),
    (re.compile(r"^BRL\s*Trust\b", re.I),
     "BRL Trust DTVM S.A.",
     "Brazilian Feeder Administrator"),
    (re.compile(r"^Zedra\b", re.I),
     "Zedra Fund Administration (Cayman) Ltd.",
     "Fund Administrator"),
    (re.compile(r"^Walkers\b", re.I),
     "Walkers Corporate Limited",
     "Cayman Legal Counsel / Registered Office"),
    (re.compile(r"^Moore\s+Professional\b", re.I),
     "Moore Professional Services Ltd.",
     "Auditors"),
    (re.compile(r"^Barbosa\s+Legal\b", re.I),
     "Barbosa Legal",
     "Legal Advisor"),
]

# Populated at runtime by entity_bootstrap via fund_context.json
# Do NOT add hardcoded entries here — use entity_bootstrap.py
_FUND_ALIASES: dict[str, str] = {}

# Validated vehicles from fund_context.json — maps vehicle name → {vehicle_type, confidence}
# Used to override Cohere Rerank when a document matches a known alias
_CONTEXT_VALIDATED_VEHICLES: dict[str, dict] = {}

# deal_name = folder name (stable, user-controlled, matches blob structure)
# fund_name  = specific entity name from bootstrap (e.g. "Blue Owl Real Estate Fund VI")
_CONTEXT_DEAL_NAME: str = ""
_CONTEXT_FUND_NAME: str = ""

# Fund metadata from bootstrap v3 — enriches chunk metadata for better queries
_CONTEXT_FUND_STRATEGY: list[str] = []
_CONTEXT_FUND_JURISDICTION: str = ""
_CONTEXT_KEY_TERMS: dict[str, str] = {}
_CONTEXT_INVESTMENT_MANAGER: str = ""

# deal_context.json — optional deal-level metadata & LLM context
_DEAL_CONTEXT: dict = {}

# ── Subfolder → classification hints ──────────────────────────
# When a PDF resides inside a recognized subfolder, the folder name
# provides a strong doc_type or vehicle_type prior that is injected
# into the Cohere Rerank query as a HINT (not a hard override).
_SUBFOLDER_DOC_HINTS: dict[str, str] = {
    "presentations": "fund_presentation",
    "legal":         "legal_agreement",
    "financial":     "financial_statements",
    "operational":   "operational_service",
    "regulatory":    "regulatory_compliance",
    "memos":         "investment_memo",
    "strategy":      "strategy_profile",
    "hr":            "operational_service",
}

_SUBFOLDER_VEHICLE_HINT: str = "vehicles"   # parent = vehicles/ → vehicle_name from folder


def _build_deal_context_string() -> str:
    """Build a context string from deal_context.json for injection into Cohere queries."""
    if not _DEAL_CONTEXT:
        return ""
    parts: list[str] = []
    desc = _DEAL_CONTEXT.get("description", "")
    if desc:
        parts.append(f"DEAL CONTEXT: {desc}")
    deal_type = _DEAL_CONTEXT.get("deal_type", "")
    if deal_type:
        parts.append(f"Deal type: {deal_type}")
    vehicles = _DEAL_CONTEXT.get("vehicles", [])
    if vehicles:
        veh_strs = [f"  - {v['name']} ({v.get('type','unknown')})" for v in vehicles if v.get("name")]
        if veh_strs:
            parts.append("Known vehicles:\n" + "\n".join(veh_strs))
    return "\n".join(parts)

# Entities that are SUBSIDIARIES of the fund — corporate vehicles for deals.
# When these appear in filename, the fund_name should be the subsidiary entity,
# not the ultimate borrower.
_FUND_SUBSIDIARY_ENTITIES: dict[str, str] = {
    "WMF Corp": "WMF Corp (Netz PCF subsidiary)",
}

# Names that indicate the document is about the Netz PCF itself (not a deal)
_NETZ_FUND_RE = re.compile(
    r"\bNetz\s+Private\s+Credit\b|\bNetz\s+PCF\b|\bNetz\s+Feeder\b"
    r"|\bNetz\s+Private\s+Credit\s+Fund\s+Corp\b",
    re.I,
)

# Context string appended to Cohere query when Netz ecosystem entities
# are detected in the document text — helps disambiguate doc_type
_NETZ_ENTITY_CONTEXT = (
    "CONTEXT: This document is part of the Netz Private Credit Fund ecosystem. "
    "Known entities: Netz Private Credit Fund (Cayman standalone_fund), "
    "Netz Asset (Brazilian sponsor), Necker Finance (Investment Manager, Switzerland), "
    "Previse Capital Partners (FORMER Investment Manager, now merged into Necker Finance — "
    "references to Previse are historical), "
    "Zedra (Fund Admin), Walkers (Legal Counsel), Moore Professional (Auditors), "
    "BRL Trust (Brazilian feeder admin), NELI US LP (US vehicle), "
    "Netz Private Credit Fund Corp LLC (US Blocker, Delaware). "
    "Documents governing relationships between these entities are likely "
    "legal_lpa, legal_agreement, or legal_side_letter. "
    "Documents describing the fund to investors are fund_presentation or capital_raising."
)

# Regex to detect Netz ecosystem entities in OCR text (triggers context injection)
_NETZ_ENTITY_DETECT_RE = re.compile(
    r"\bNetz\s+(?:Private\s+Credit|Asset|PCF)\b"
    r"|\bNecker\s+Finance\b"
    r"|\bPrevise\s+Capital\b"
    r"|\bZedra\b"
    r"|\bNELI\s+US\b"
    r"|\bWMF\s+Corp\b"
    r"|\bWalkers\s+(?:Corporate|Global)\b"
    r"|\bBRL\s+Trust\b"
    r"|\bMoore\s+Professional\b"
    r"|\bGarrington\b"
    r"|\bCoral\s+Cove\b",
    re.I,
)


# ============================================================
# FUND NAME EXTRACTION
# ============================================================

# Segmentos genéricos do filename que não são nomes de fundo/empresa
_SKIP_SEGMENTS = frozenset({
    "DRAFT", "FINAL", "SIGNED", "EXECUTED", "CONFIDENTIAL", "COPY",
    "SECURED", "REDACTED", "CLEAN", "MARKED", "V2", "V3",
})

_DATE_ONLY_RE = re.compile(
    r"^(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{4}$"
    r"|^\d{4}$"
    r"|^(?:Q[1-4]|[1-4]Q)\s*\d{2,4}$"
    r"|^\d{8}$",
    re.IGNORECASE,
)

# Sufixos de doc_type que podem aparecer no filename após o nome da entidade
_DOC_SUFFIXES_RE = re.compile(
    r"\b(?:Financial\s+Statements?|LPA|Side\s+Letter|Subscription|"
    r"Credit\s+(?:Policy|Agreement)|Compliance\s+Manual|Employee\s+Handbook|"
    r"Org(?:\s+|anizational\s+)?Chart|Risk\s+Assessment|IT\s+Policy|"
    r"IT\s+Disaster|Business\s+Continuity|Code\s+of\s+(?:Ethics|Conduct)|"
    r"Capital\s+Raising|Fund\s+Profile|Strategy\s+Profile|Structure\s+Chart|"
    r"Fact\s+(?:Card|Sheet)|Presentation|Annual\s+Report|QDD|"
    r"Anti.Money.Laundering|Policies\s+and\s+Procedures)\b",
    re.IGNORECASE,
)


def _extract_fund_name(filename: str, ocr_text: str) -> str:
    """Extract fund/entity name from filename first, then OCR as fallback.

    Strategy:
    1. Split filename on ' - ' delimiters
    2. Skip generic prefixes (DRAFT, FINAL) and date-only segments
    3. Skip known non-fund entities (Previse, Necker, Zedra, etc.) — use next segment
    4. Expand known fund abbreviations (GPCF → Garrington Private Credit Fund)
    5. Strip trailing doc-type suffixes
    6. Fall back to first meaningful OCR line if filename yields nothing
    """
    stem = Path(filename).stem  # remove .pdf

    # Try splitting on " - " → take first meaningful segment
    parts = [p.strip() for p in stem.split(" - ")]

    # Also handle underscore-separated filenames (e.g. "Cert_-_Incorp_-_WMF_Corp")
    if len(parts) == 1 and "_-_" in stem:
        parts = [p.strip().replace("_", " ") for p in stem.split("_-_")]

    candidate = ""
    for part in parts:
        if part.upper() in _SKIP_SEGMENTS:
            continue
        if _DATE_ONLY_RE.match(part):
            continue

        # Check if this segment is a known non-fund entity (service provider/manager)
        is_non_fund = False
        for pat, _canonical, _role in _NETZ_NON_FUND_ENTITIES:
            if pat.search(part):
                is_non_fund = True
                break

        if is_non_fund:
            # Skip service provider names — the deal/fund name follows
            continue

        candidate = part
        break

    if candidate:
        # Check if candidate matches a known subsidiary entity BEFORE stripping suffixes
        # (e.g. "WMF Corp" should stay as-is, not strip "Corp")
        for sub_key, sub_canonical in _FUND_SUBSIDIARY_ENTITIES.items():
            if sub_key.upper() in candidate.upper():
                return sub_canonical[:100]

        # Remove trailing doc-type descriptors to isolate the entity name
        stripped = _DOC_SUFFIXES_RE.sub("", candidate).strip(" -\u2013\u2014")
        # Collapse double spaces left by suffix removal (e.g. "Garrington  Code of Conduct")
        stripped = re.sub(r"\s{2,}", " ", stripped).strip()
        if len(stripped) >= 4:
            candidate = stripped
        # Remove common legal suffixes
        candidate = re.sub(
            r"\s+(?:Ltd\.?|LLC|LP|L\.P\.|Inc\.?|Corp\.?)\s*$",
            "", candidate, flags=re.IGNORECASE,
        ).strip()

        # Expand known fund abbreviations (e.g. GPCF → Garrington Private Credit Fund)
        # Check if the first word is a known alias
        first_word = candidate.split()[0] if candidate.split() else ""
        if first_word.upper() in _FUND_ALIASES:
            expanded = _FUND_ALIASES[first_word.upper()]
            # Replace alias with full name, keep any trailing qualifier
            rest = candidate[len(first_word):].strip()
            candidate = f"{expanded} {rest}".strip() if rest else expanded

        # Also try the whole candidate (for cases like "SREIF. LP")
        clean_upper = re.sub(r"[.\s]+$", "", candidate).upper()
        if clean_upper in _FUND_ALIASES:
            candidate = _FUND_ALIASES[clean_upper]

        # Reject single-word candidates that are countries, regions, or generic labels
        # (e.g. "Canada" from "Canada Employee Handbook", "ANBIMA" from "QDD ANBIMA")
        _INVALID_STANDALONE = re.compile(
            r"^(US|USA|UK|Canada|Australia|Germany|France|Japan|Brazil|Brasil"
            r"|ANBIMA|CVM|SEC|FINRA|CIMA|FCA"
            r"|International|Global|General|Standard|Default"
            r"|Annual|Monthly|Quarterly|Weekly"
            r"|Draft|Final|Signed|Executed|Confidential)$",
            re.IGNORECASE,
        )
        if len(candidate.split()) == 1 and _INVALID_STANDALONE.match(candidate):
            candidate = ""  # fall through to OCR fallback

        if len(candidate) >= 4:
            return candidate[:100]

    # Fallback: OCR first meaningful line
    for line in ocr_text.split("\n"):
        line = line.strip().lstrip("#").strip()
        if not line or line.startswith("![") or line.startswith("http"):
            continue
        if len(line) <= 8:
            continue
        return line[:100]

    return "Unknown"


def _resolve_vehicle_from_context(filename: str) -> tuple[str | None, str | None]:
    """Check if the filename matches a known alias from fund_context.json and
    resolve to a validated vehicle_type.

    Flow:  filename → alias key → full vehicle name → validated_vehicles → vehicle_type

    Returns (vehicle_type, reason_str) or (None, None).
    """
    if not _CONTEXT_VALIDATED_VEHICLES or not _FUND_ALIASES:
        return None, None

    fn_upper = filename.upper()
    for alias_key, full_name in _FUND_ALIASES.items():
        if alias_key in fn_upper and full_name in _CONTEXT_VALIDATED_VEHICLES:
            vt = _CONTEXT_VALIDATED_VEHICLES[full_name].get("vehicle_type")
            if vt:
                conf = _CONTEXT_VALIDATED_VEHICLES[full_name].get("confidence", 0)
                return vt, f"{alias_key} → {full_name} → {vt} (conf={conf:.2f})"
    return None, None


# ============================================================
# PROCESSAMENTO PRINCIPAL
# ============================================================

def process_file(
    pdf_path: str,
    mistral_key: str,
    cohere_key: str,
    dry_run: bool = False,
    max_pages: int = DEFAULT_MAX_PAGES,
    debug: bool = False,
) -> dict:
    path = Path(pdf_path)
    logger.info(">> %s", path.name)

    # Skip standard compliance forms
    if is_skippable(path.name):
        logger.info("[SKIP] standard compliance form")
        return {"file": path.name, "skipped": True, "reason": "standard_compliance_form"}

    # ── Stage 1: Mistral OCR ──────────────────────────────
    t0 = time.time()
    try:
        ocr_text, total_pages, n_batches = extract_ocr_text(
            pdf_path, mistral_key, batch_size=max_pages,
        )
    except Exception as e:
        logger.warning("[FAIL] Mistral OCR: %s", e)
        return {"file": path.name, "error": f"Mistral OCR: {e}"}
    t_ocr = round(time.time() - t0, 1)

    if not ocr_text.strip():
        logger.warning("[FAIL] OCR returned empty text")
        return {"file": path.name, "error": "OCR returned empty text"}

    batch_info = f" | {n_batches} batches" if n_batches > 1 else ""
    logger.info("OCR: %d pages → %s chars | %ss%s", total_pages, f"{len(ocr_text):,}", t_ocr, batch_info)

    # ── Subfolder hints from deal folder structure ────────────
    subfolder_doc_hint = ""
    subfolder_veh_hint = ""
    if _CONTEXT_DEAL_NAME:
        # Derive relative path parts between deal folder and this file
        # e.g. "vehicles/Fund VI/legal/LPA.pdf" → parts = ["vehicles", "Fund VI", "legal"]
        try:
            # Walk up from the file to find the deal folder
            p = path.parent
            parts: list[str] = []
            while p.name and p.name != _CONTEXT_DEAL_NAME:
                parts.insert(0, p.name)
                p = p.parent
        except ValueError:
            parts = []

        for part in parts:
            part_lower = part.lower()
            if part_lower in _SUBFOLDER_DOC_HINTS:
                doc_type_hint = _SUBFOLDER_DOC_HINTS[part_lower]
                subfolder_doc_hint = (
                    f"FOLDER HINT: This file is inside the '{part}/' folder. "
                    f"Files in this folder are typically '{doc_type_hint}'. "
                    f"Strongly prefer {doc_type_hint} unless content clearly contradicts."
                )
            if part_lower == _SUBFOLDER_VEHICLE_HINT and len(parts) > 1:
                # The folder after "vehicles/" is the vehicle name
                idx = parts.index(part)
                if idx + 1 < len(parts):
                    vehicle_folder = parts[idx + 1]
                    subfolder_veh_hint = (
                        f"FOLDER HINT: This file is inside 'vehicles/{vehicle_folder}/'. "
                        f"The vehicle name is '{vehicle_folder}'. "
                        f"Use this as the fund/vehicle identifier for classification."
                    )

        if subfolder_doc_hint:
            logger.info("[folder-hint] doc: %s...", subfolder_doc_hint[:80])
        if subfolder_veh_hint:
            logger.info("[folder-hint] veh: %s...", subfolder_veh_hint[:80])

    # ── Stage 2: Cohere Rerank → doc_type ────────────────────
    t1 = time.time()
    try:
        doc_type, doc_score, doc_top3 = classify_doc_type(
            ocr_text, cohere_key, path.name, subfolder_hint=subfolder_doc_hint,
        )
    except Exception as e:
        logger.warning("[FAIL] Cohere doc_type: %s", e)
        return {"file": path.name, "error": f"Cohere doc_type: {e}"}

    # ── Stage 3: Cohere Rerank → vehicle_type ────────────────
    try:
        vehicle_type, vehicle_score, vehicle_top3 = classify_vehicle_type(
            ocr_text, cohere_key, path.name, subfolder_hint=subfolder_veh_hint,
        )
    except Exception as e:
        logger.warning("[FAIL] Cohere vehicle_type: %s", e)
        vehicle_type, vehicle_score, vehicle_top3 = "other", 0.0, []
    t_rerank = round(time.time() - t1, 1)

    # ── Stage 3b: Document Q&A fallback (low Cohere confidence) ──────────────
    qna_fallback_used = False
    if doc_score < COHERE_FALLBACK_THRESHOLD:
        logger.info("[QnA] doc_score=%.3f < %s → Mistral Document Q&A fallback", doc_score, COHERE_FALLBACK_THRESHOLD)
        try:
            fb_doc, fb_veh, fb_score = classify_with_document_qna(
                ocr_text, mistral_key, path.name,
            )
            doc_type      = fb_doc
            doc_score     = fb_score
            vehicle_type  = fb_veh
            vehicle_score = fb_score
            qna_fallback_used = True
            logger.info("[QnA] → doc_type=%s  vehicle=%s  confidence=%d/10", fb_doc, fb_veh, round(fb_score * 10))
        except Exception as e:
            logger.warning("[QnA] fallback failed: %s — keeping Cohere result", e)

    # ── Stage 4a: Bootstrap vehicle override (fund_context.json) ────
    vehicle_source = "rerank"
    ctx_v, ctx_reason = _resolve_vehicle_from_context(path.name)
    hint_v, hint_reason = None, None
    if ctx_v:
        vehicle_type   = ctx_v
        vehicle_source = "bootstrap"
        vehicle_score  = 1.0
        if debug:
            logger.info("[vehicle] bootstrap override: %s", ctx_reason)

    # ── Stage 4b: Multi-signal heuristic override ─────────────
    if vehicle_source == "rerank":
        hint_v, hint_reason = vehicle_hint(path.name, ocr_text, debug=debug)
        if hint_v:
            vehicle_type   = hint_v
            vehicle_source = "heuristic"
            vehicle_score  = 1.0

    # ── Stage 4c: doc_types with no fund vehicle → force "other" ─
    if vehicle_source == "rerank" and doc_type in _NO_VEHICLE_DOC_TYPES:
        vehicle_type   = "other"
        vehicle_source = "doc_type_override"
        vehicle_score  = 1.0

    # ── Stage 5: Governance detection ────────────────────────
    gov_critical, gov_flags = detect_governance(ocr_text)

    # deal_name = folder name (stable, user-controlled)
    # fund_name = specific entity from bootstrap (enrichment for metadata)
    deal_name = _CONTEXT_DEAL_NAME or path.parent.name
    fund_name = _CONTEXT_FUND_NAME or _extract_fund_name(path.name, ocr_text)

    # Confidence = doc_type score only (vehicle_score is unreliable when heuristic fires)
    confidence = max(1, min(10, round(doc_score * 10)))

    # ── Stage 6: Semantic chunking ────────────────────────────
    doc_id   = path.stem
    metadata = {
        "deal_name":           deal_name,
        "fund_name":           fund_name,
        "doc_type":            doc_type,
        "doc_type_score":      doc_score,
        "vehicle_type":        vehicle_type,
        "vehicle_type_score":  vehicle_score,
        "vehicle_source":      vehicle_source,
        "governance_critical": gov_critical,
        "governance_flags":    gov_flags,
        "confidence":          confidence,
        "qna_fallback":        qna_fallback_used,
        "source_file":         path.name,
        # BUG FIX: use canonical deal name (not immediate parent folder, which
        # may be a subfolder like "presentations" or "legal").
        "deal_folder": (
            _CONTEXT_DEAL_NAME.lower().replace(" ", "_")
            if _CONTEXT_DEAL_NAME
            else path.parent.name.lower().replace(" ", "_")
        ),
        # Capture the original subfolder name for traceability (empty when
        # the PDF lives directly inside the deal root).
        "subfolder": (
            path.parent.name
            if _CONTEXT_DEAL_NAME and path.parent.name != _CONTEXT_DEAL_NAME
            else ""
        ),
    }
    # Enrich with bootstrap v3 metadata (only if available — zero bloat)
    if _CONTEXT_FUND_STRATEGY:
        metadata["fund_strategy"] = _CONTEXT_FUND_STRATEGY
    if _CONTEXT_FUND_JURISDICTION:
        metadata["fund_jurisdiction"] = _CONTEXT_FUND_JURISDICTION
    if _CONTEXT_KEY_TERMS:
        metadata["key_terms"] = _CONTEXT_KEY_TERMS
    if _CONTEXT_INVESTMENT_MANAGER:
        metadata["investment_manager"] = _CONTEXT_INVESTMENT_MANAGER
    chunks = chunk_document(
        ocr_markdown = ocr_text,
        doc_id       = doc_id,
        doc_type     = doc_type,
        metadata     = metadata,
    )

    # ── Log ──────────────────────────────────────────────────
    gov_icon     = "!! " if gov_critical else "   "
    doc_top3_str = "  ".join(f"{label}({score})" for label, score in doc_top3)
    veh_top3_str = "  ".join(f"{label}({score})" for label, score in vehicle_top3)

    qna_tag      = " [+QnA fallback]" if qna_fallback_used else ""
    logger.info("deal_name:   %s", deal_name[:60])
    logger.info("%sdoc_type:    [%s]%s", gov_icon, doc_top3_str, qna_tag)
    logger.info("cohere veh:  [%s] | %ss", veh_top3_str, t_rerank)
    logger.info("vehicle:     %s [%s] | confidence: %d/10", vehicle_type, vehicle_source, confidence)
    if vehicle_source == "bootstrap" and ctx_reason:
        logger.info("[bootstrap]  %s", ctx_reason)
    if vehicle_source == "heuristic" and hint_reason:
        logger.info("[heuristic]  %s", hint_reason)
    if gov_flags:
        logger.info("gov_flags:   %s", gov_flags)
    print_chunk_summary(chunks, path.name)

    if dry_run:
        logger.info("[DRY RUN] metadata not written")

    return {
        "file":                path.name,
        "deal_name":           deal_name,
        "doc_type":            doc_type,
        "doc_type_score":      doc_score,
        "vehicle_type":        vehicle_type,
        "vehicle_type_score":  vehicle_score,
        "vehicle_source":      vehicle_source,
        "governance_critical": gov_critical,
        "governance_flags":    gov_flags,
        "confidence":          confidence,
        "qna_fallback":        qna_fallback_used,
        "pages":               total_pages,
        "chunks":              chunks,
        "chunk_count":         len(chunks),
    }


def process_folder(
    folder_path: str,
    mistral_key: str,
    cohere_key: str,
    dry_run: bool = False,
    max_pages: int = DEFAULT_MAX_PAGES,
    debug: bool = False,
) -> list:

    # Reset deal context — prevents bleed between deals in recursive runs
    global _CONTEXT_DEAL_NAME, _CONTEXT_FUND_NAME, _DEAL_CONTEXT
    global _CONTEXT_FUND_STRATEGY, _CONTEXT_FUND_JURISDICTION
    global _CONTEXT_KEY_TERMS, _CONTEXT_INVESTMENT_MANAGER
    _CONTEXT_DEAL_NAME = ""
    _CONTEXT_FUND_NAME = ""
    _DEAL_CONTEXT = {}
    _CONTEXT_FUND_STRATEGY = []
    _CONTEXT_FUND_JURISDICTION = ""
    _CONTEXT_KEY_TERMS = {}
    _CONTEXT_INVESTMENT_MANAGER = ""
    _FUND_ALIASES.clear()
    _CONTEXT_VALIDATED_VEHICLES.clear()

    folder = Path(folder_path)

    # deal_name = folder name (stable, user-controlled)
    _CONTEXT_DEAL_NAME = folder.name

    # ── Load deal_context.json (optional deal-level metadata) ────
    deal_ctx_path = folder / "deal_context.json"
    if deal_ctx_path.exists():
        try:
            _DEAL_CONTEXT = json.loads(deal_ctx_path.read_text(encoding="utf-8"))
            logger.info("[deal_context] loaded: %s", deal_ctx_path.name)
        except Exception as e:
            logger.warning("[deal_context] Could not load: %s", e)

    # ── Load fund_context.json from entity_bootstrap ────────────
    ctx_path = folder / "fund_context.json"
    if ctx_path.exists():
        try:
            fund_context = json.loads(ctx_path.read_text(encoding="utf-8"))
            n_aliases = 0
            if "discovered_aliases" in fund_context:
                _FUND_ALIASES.update(fund_context["discovered_aliases"])
                n_aliases = len(fund_context["discovered_aliases"])
            validated = fund_context.get("validated_vehicles", {})
            n_vehicles = len(validated)
            _CONTEXT_VALIDATED_VEHICLES.update(validated)
            _CONTEXT_FUND_NAME = fund_context.get("fund_name", "")

            # ── Bootstrap v3 metadata fields ──
            _CONTEXT_FUND_STRATEGY = fund_context.get("fund_strategy", [])
            _CONTEXT_FUND_JURISDICTION = fund_context.get("fund_jurisdiction", "")
            _CONTEXT_KEY_TERMS = fund_context.get("key_terms", {})
            # Derive investment_manager from entities
            entities = fund_context.get("entities", {})
            for role_key in ("investment_manager", "manager", "fund_manager"):
                mgr = entities.get(role_key, {})
                if mgr.get("name"):
                    _CONTEXT_INVESTMENT_MANAGER = mgr["name"]
                    break

            extras = []
            if _CONTEXT_FUND_STRATEGY:
                extras.append(f"strategy={_CONTEXT_FUND_STRATEGY}")
            if _CONTEXT_FUND_JURISDICTION:
                extras.append(f"jurisd={_CONTEXT_FUND_JURISDICTION}")
            if _CONTEXT_KEY_TERMS:
                extras.append(f"terms={_CONTEXT_KEY_TERMS}")
            if _CONTEXT_INVESTMENT_MANAGER:
                extras.append(f"mgr={_CONTEXT_INVESTMENT_MANAGER}")
            extra_str = " | " + " | ".join(extras) if extras else ""
            logger.info("[bootstrap] fund_name='%s' | deal_name='%s' | %d aliases + %d validated vehicles%s", _CONTEXT_FUND_NAME, _CONTEXT_DEAL_NAME, n_aliases, n_vehicles, extra_str)
        except Exception as e:
            logger.warning("[bootstrap] Could not load fund_context.json: %s", e)

    pdfs = sorted(Path(folder_path).rglob("*.pdf"))
    if not pdfs:
        logger.warning("No PDFs found in: %s", folder_path)
        return []

    prefix = "[DRY RUN] " if dry_run else ""
    logger.info("%sFound %d PDFs in %s", prefix, len(pdfs), folder_path)

    results:    list[dict] = []
    all_chunks: list[dict] = []
    errors:     list[str]  = []
    skipped:    list[str]  = []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _process_one(pdf_path):
        return process_file(str(pdf_path), mistral_key, cohere_key, dry_run, max_pages, debug)

    total = len(pdfs)
    done_count = 0
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_pdf = {executor.submit(_process_one, pdf): pdf for pdf in pdfs}
        for future in as_completed(future_to_pdf):
            pdf = future_to_pdf[future]
            done_count += 1
            logger.info("[%d/%d] %s", done_count, total, pdf.name)
            try:
                result = future.result()
                results.append(result)
                if result.get("skipped"):
                    skipped.append(pdf.name)
                elif "error" in result:
                    errors.append(pdf.name)
                else:
                    all_chunks.extend(result.get("chunks", []))
            except Exception as e:
                logger.warning("[FAIL] Exception processing %s: %s", pdf.name, e)
                errors.append(pdf.name)
                results.append({"file": pdf.name, "error": str(e)})

    # ── Write outputs ──────────────────────────────────────

    # Report — strips chunks to keep readable
    report_path = folder / "cu_preparation_report.json"
    report_data = [
        {k: v for k, v in r.items() if k != "chunks"}
        for r in results
    ]
    report_path.write_text(
        json.dumps(report_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Chunks — full semantic chunks for Stage 7 (embedding)
    if all_chunks:
        chunks_path = folder / "cu_chunks.json"
        chunks_path.write_text(
            json.dumps(all_chunks, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Chunks written: %s → %s", f"{len(all_chunks):,}", chunks_path.name)

    # ── Summary ───────────────────────────────────────────
    processed = len(results) - len(skipped) - len(errors)
    logger.info("=" * 50)
    logger.info("Processed: %d PDFs", processed)
    logger.info("Skipped:   %d (standard compliance forms)", len(skipped))
    for s in skipped:
        logger.info("[SKIP] %s", s)
    logger.info("Errors:    %d", len(errors))
    for e in errors:
        logger.warning("[FAIL] %s", e)
    logger.info("Report:    %s", report_path.name)

    return results


# (CLI entry point removed — use process_folder() directly)
