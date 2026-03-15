"""Memo chapter prompts, token budgets, and configuration constants."""
from __future__ import annotations

_CHAPTER_DOC_AFFINITY: dict[str, frozenset[str]] = {
    "ch01_exec": frozenset({
        # Canonical types (from Document Intelligence Layer)
        "legal_lpa", "legal_side_letter", "legal_term_sheet",
        "fund_structure", "fund_profile", "fund_presentation",
        "strategy_profile", "capital_raising", "fund_policy",
        # Legacy affinity tags (backward compat)
        "TERM_SHEET", "FINANCIAL", "RISK_ASSESSMENT", "FUND_POLICY",
        "FUND_CONSTITUTION", "REGULATORY",
        "SIDE_LETTER", "LEGAL_SIDE_LETTER",
    }),
    "ch02_macro": frozenset({
        "fund_presentation", "strategy_profile", "fund_profile",
        "regulatory_cima", "regulatory_compliance", "capital_raising",
        "FINANCIAL", "RISK_ASSESSMENT", "REGULATORY",
        "FUND_CONSTITUTION",
    }),
    "ch03_exit": frozenset({
        "financial_statements", "financial_nav", "financial_projections",
        "fund_presentation", "strategy_profile",
        "FINANCIAL", "FINANCIAL_STATEMENTS", "RISK_ASSESSMENT",
    }),
    "ch04_sponsor": frozenset({
        "legal_subscription", "legal_side_letter", "legal_agreement",
        "legal_lpa", "legal_security", "fund_policy",
        "regulatory_compliance", "operational_service", "operational_monitoring",
        "org_chart", "risk_assessment",
        "SUBSCRIPTION_AGREEMENT", "SIDE_LETTER", "LEGAL",
        "FUND_CONSTITUTION", "GUARANTEE",
        "FUND_POLICY", "COMPLIANCE", "REGULATORY",
        "RISK_ASSESSMENT", "MONITORING",
        "SERVICE_AGREEMENT",
    }),
    "ch05_legal": frozenset({
        "legal_credit_agreement", "legal_lpa", "legal_side_letter",
        "legal_agreement", "legal_amendment", "legal_subscription",
        "legal_term_sheet", "legal_security", "legal_intercreditor",
        "legal_poa", "regulatory_cima",
        "CREDIT_AGREEMENT", "FACILITY_AGREEMENT", "LOAN_AGREEMENT",
        "SECURITY_AGREEMENT", "INTERCREDITOR", "GUARANTEE", "PLEDGE",
        "LEGAL", "SIDE_LETTER", "LEGAL_SIDE_LETTER",
        "FUND_CONSTITUTION", "REGULATORY",
    }),
    "ch06_terms": frozenset({
        "legal_term_sheet", "legal_credit_agreement", "legal_lpa",
        "legal_agreement", "legal_amendment", "fund_presentation",
        "strategy_profile", "operational_service",
        "TERM_SHEET", "CREDIT_AGREEMENT", "FACILITY_AGREEMENT",
        "LOAN_AGREEMENT",
        "FUND_CONSTITUTION", "SERVICE_AGREEMENT",
    }),
    "ch07_capital": frozenset({
        "financial_statements", "financial_nav", "financial_projections",
        "legal_term_sheet", "fund_presentation", "strategy_profile",
        "fund_profile", "capital_raising", "legal_lpa",
        "FINANCIAL", "FINANCIAL_STATEMENTS", "TERM_SHEET",
        "FUND_CONSTITUTION",
    }),
    "ch08_returns": frozenset({
        "financial_statements", "financial_nav", "financial_projections",
        "legal_term_sheet", "fund_presentation", "strategy_profile",
        "fund_profile", "capital_raising", "legal_lpa",
        "FINANCIAL", "FINANCIAL_STATEMENTS", "TERM_SHEET",
        "FUND_CONSTITUTION",
    }),
    "ch09_downside": frozenset({
        "risk_assessment", "financial_statements", "financial_nav",
        "credit_policy", "regulatory_cima", "regulatory_compliance",
        "operational_service", "operational_monitoring", "legal_lpa",
        "RISK_ASSESSMENT", "FINANCIAL", "COVENANT_COMPLIANCE",
        "REGULATORY", "SERVICE_AGREEMENT", "FUND_CONSTITUTION",
    }),
    "ch10_covenants": frozenset({
        "credit_policy", "legal_credit_agreement", "legal_amendment",
        "legal_lpa", "regulatory_cima", "regulatory_compliance",
        "operational_monitoring",
        "COVENANT_COMPLIANCE", "COVENANT", "CREDIT_AGREEMENT",
        "FACILITY_AGREEMENT",
        "FUND_CONSTITUTION", "REGULATORY",
    }),
    "ch11_risks": frozenset({
        "risk_assessment", "regulatory_cima", "regulatory_compliance",
        "operational_service", "operational_insurance",
        "operational_monitoring", "legal_lpa", "fund_policy",
        "RISK_ASSESSMENT", "RISK", "COMPLIANCE", "REGULATORY",
        "INSURANCE", "WATCHLIST",
        "SERVICE_AGREEMENT", "FUND_CONSTITUTION",
    }),
    "ch12_peers": frozenset({
        "financial_statements", "financial_nav", "legal_term_sheet",
        "risk_assessment", "capital_raising", "fund_presentation",
        "FINANCIAL", "TERM_SHEET", "RISK_ASSESSMENT",
    }),
    # ch14 — heavy governance + stress analysis — requires legal, credit, regulatory, financial
    "ch14_governance_stress": frozenset({
        # Canonical types (from Document Intelligence Layer)
        "legal_lpa", "legal_side_letter", "legal_agreement", "legal_amendment",
        "legal_credit_agreement", "legal_term_sheet",
        "credit_policy", "financial_statements", "financial_nav",
        "regulatory_cima", "regulatory_compliance",
        "risk_assessment", "org_chart", "fund_policy",
        # Legacy affinity tags (backward compat)
        "FUND_CONSTITUTION", "CREDIT_AGREEMENT", "SIDE_LETTER", "LEGAL_SIDE_LETTER",
        "REGULATORY", "RISK_ASSESSMENT", "FINANCIAL",
    }),
    # ch13 — synthesis only, no evidence chunks needed
    "ch13_recommendation": frozenset(),
}


# ---------------------------------------------------------------------------
# Per-chapter system prompts
# ---------------------------------------------------------------------------

_CHAPTER_PROMPTS: dict[str, str] = {
    "ch01_exec": """\
You are writing the **Executive Summary** chapter of an institutional
Investment Memorandum for a Cayman Islands private credit fund IC.

CRITICAL: "Netz Private Credit Fund" is the INVESTOR (our fund), NOT the
deal sponsor. The deal sponsor/manager is the EXTERNAL counterparty listed
in deal_identity.sponsor_name. Begin the summary by identifying WHO the
external sponsor is and WHAT the investment opportunity is, from the
perspective of Netz evaluating an investment IN the deal.

Write a 600-800 word executive overview covering:
  • Deal identity and sponsor (the EXTERNAL manager, NOT Netz)
  • Transaction rationale
  • Key terms (tenor, rate, collateral)
  • Return profile summary
  • Top 3 risks
  • Recommendation signal (INVEST / PASS / CONDITIONAL)
  • Fund governance highlights — if evidence includes the INVESTOR's
    (Netz Private Credit Fund) offering memorandum or fund constitution,
    note any board-approved liberalities, investment policy overrides,
    or governance features material to the IC.  These describe NETZ's
    governance, NOT the deal target's.  Netz's administrator is Zedra
    Fund Administration (Cayman) Ltd.; do NOT attribute Zedra to the
    deal being evaluated.
  • Regulatory standing — if CIMA regulatory evidence is present,
    state NETZ's current regulatory compliance posture in one sentence.
    CIMA evidence in the index describes OUR fund, not the deal.

Use the EvidencePack data — do NOT fabricate.
Write in Markdown.  Be analytical, not descriptive.
Return JSON: {{"section_text": "...markdown..."}}
""",

    "ch02_macro": """\
You are writing the **Market Context** chapter.

CRITICAL ENTITY RULE: CIMA regulatory evidence and fund constitution
documents in the EvidencePack describe the INVESTOR (Netz Private Credit
Fund), NOT the deal being analysed.  When referencing these, frame them
as the regulatory environment affecting Netz's ability to invest — not
as the deal target's regulatory standing.  Zedra Fund Administration is
Netz's administrator; do NOT attribute it to the deal.

Cover:
  • Industry dynamics relevant to this deal
  • Competitive positioning of the borrower/sector
  • Regulatory environment — if CIMA regulatory evidence is present,
    describe the applicable regulatory framework (CIMA Mutual Funds Act,
    reporting obligations) and assess how Netz's regulatory regime
    shapes operational requirements for the INVESTOR fund
  • How market conditions affect underwriting
  • Jurisdiction-specific considerations — if fund constitution evidence
    is present, note Cayman Islands domicile implications for the
    INVESTOR (Netz), governing law, and any regulatory exemptions

=== BANK CREDIT & CONSTRUCTION SUPPLY CONTEXT ===
If macro_snapshot.real_estate_national.HOUST trend_direction == "falling"
or macro_snapshot.real_estate_national.PERMIT trend_direction == "falling",
flag reduced construction pipeline as a structural positive for existing
collateral values — less new supply competing with the collateral pool.
If macro_snapshot.banking_activity.TOTLL trend_direction == "falling",
note tighter bank lending as a tailwind for private credit pricing power
(reduced competition from bank lenders supports spread maintenance).
In both cases cite the delta_12m_pct value and trend_direction inline.

Target: 600-1000 words.  Cite EvidencePack data.
Return JSON: {{"section_text": "...markdown..."}}
""",

    "ch03_exit": """\
You are writing the **Macro Regime & Exit Environment** chapter.

The EvidencePack contains a FRED macro snapshot with REAL numeric data.
You MUST cite the actual numbers from the snapshot — do NOT state they are
"not confirmed" or "not available".  The snapshot fields are:
  risk_free_10y, risk_free_2y, yield_curve_2s10s, baa_spread,
  cpi_yoy, gdp_yoy, unemployment_rate, financial_conditions_index,
  recession_flag, as_of_date.

═══ SECTION 1: MACRO REGIME ═══
Structure:
  • Current rate environment — cite 10Y (risk_free_10y), 2Y (risk_free_2y),
    2s10s spread (yield_curve_2s10s) with actual values
  • Credit spreads and risk appetite — cite Baa spread (baa_spread)
  • Inflation regime — cite CPI YoY (cpi_yoy) and GDP YoY (gdp_yoy)
  • Unemployment and labor market — cite unemployment_rate
  • Financial conditions and recession risk — cite financial_conditions_index
    (NFCI: negative = loose, positive = tight) and recession_flag
  • Implications for deal pricing, exit timing, recovery assumptions

Present the macro environment data as a TABLE before the narrative:

| Metric                    | Current Value | Source      | Signal                    |
|---------------------------|---------------|-------------|---------------------------|
| 10Y Treasury (DGS10)      | X.XX%         | FRED        | Tight / Neutral / Loose   |
| 2Y Treasury (DGS2)        | X.XX%         | FRED        |                           |
| 2s10s Yield Curve         | X.XX%         | FRED (calc) | Normal / Inverted / Flat  |
| Baa Credit Spread         | X.XX%         | FRED        | Wide / Normal / Tight     |
| CPI YoY                   | X.XX%         | FRED        | Above / At / Below target |
| GDP Growth (YoY)          | X.XX%         | FRED        |                           |
| Unemployment Rate         | X.XX%         | FRED        |                           |
| NFCI Financial Conditions | X.XXX         | FRED        | >0 Tight / <0 Loose       |
| Recession Flag            | YES / NO      | NBER / FRED |                           |

Populate every row using the EvidencePack macro_snapshot values.
Use [N/A — not yet available] for null snapshot fields.
Write narrative analysis BELOW the table (300–400 words).

Every macro subsection MUST include at least one specific number from the
snapshot.  If a value is null, state it is not yet available for the period.

=== MACRO TIME-SERIES CONTEXT ===
Use the full 12-month series in macro_snapshot.rates_spreads to describe the
DIRECTION of rates (rising / falling / stable) — not just the current level.
Reference: DGS10 trend_direction, BAA10Y trend_direction, yield_curve_2s10s
delta_12m.  Lead with direction language (e.g. "The 10-year Treasury has been
rising over the past 12 months, reaching X%") before citing the spot value.
If macro_snapshot.regional.case_shiller_metro is present, cite the
metro-specific HPI trend_direction and delta_12m_pct for the deal geography
vs. the national CSUSHPINSA trend — flag divergence where material.

═══ SECTION 2: EXIT ENVIRONMENT & LIQUIDITY ASSESSMENT ═══
This section is MANDATORY and must be at least 400 words.

Analyze the exit environment for THIS specific deal type based on all
EvidencePack evidence.  Cover ALL of the following subsections:

**2a. Instrument-Specific Exit Mechanics**
  Identify the deal instrument type (revolving credit facility, term loan,
  open-ended fund, closed-end fund, etc.) from the EvidencePack.
  Describe the specific exit path for this instrument:
  • For revolving credit / open-ended structures: redemption queue mechanics,
    notice periods, gate provisions, frequency of NAV calculation
  • For term loans / closed-end structures: maturity profile, refinancing
    risk, extension options
  • For secondary market exits: liquidity depth, typical bid-ask spreads,
    pricing discount to par or NAV
  Cite specific terms from the fund documents if present in evidence.

**2b. Secondary Market & Liquidity Conditions**
  Assess current secondary market conditions for private credit / private debt:
  • Is the secondary market for this instrument type currently liquid or
    constrained?  Reference the macro spread environment as a signal.
  • Typical redemption / exit timelines for this fund category in the current
    rate environment
  • Identify any redemption restriction triggers that could impair exit:
    gates, queues, suspension of redemptions
  If EvidencePack market_benchmarks contains PitchBook or other secondary
  market data, cite it explicitly:
    – Realized exit multiples (DPI / TVPI) for comparable vintage years
    – Secondary pricing as % of NAV for comparable strategies
    – Typical hold period distributions for the strategy
  If market_benchmarks is absent, state that market data was not available
  and rely on macro proxies.

**2c. Exit Timing Analysis**
  Given the current macro regime:
  • Is this a favorable or unfavorable window to exit / redeem?
  • What macro conditions would need to change to improve exit prospects
    (e.g., spread compression, curve normalization, credit cycle turn)?
  • What is the realistic exit timeline for a position of this size and type?
  • Flag any macro risks that could extend the exit timeline:
    recession risk, spread widening, liquidity freeze

**2d. Portfolio-Level Exit Risk**
  Assess the concentration and sequencing risk at exit:
  • If this is a fund-of-funds or multi-manager structure: layered liquidity
    risk (underlying fund gates compound the top-level fund gates)
  • For single-strategy funds: key-person risk at exit, rollover risk at
    maturity
  • Credit deterioration scenarios that could prevent orderly exit:
    default, restructuring, forced asset sale

**2e. IC Verdict — Exit Environment**
  Conclude with a CLEAR IC-grade statement:
  | Exit Dimension         | Assessment    | Key Constraint                  |
  |------------------------|---------------|---------------------------------|
  | Instrument liquidity   | HIGH/MED/LOW  | e.g., 90-day redemption queue   |
  | Secondary market depth | HIGH/MED/LOW  | e.g., thin market, wide spreads |
  | Macro exit window      | OPEN/NEUTRAL/ | e.g., tight spreads favorable   |
  |                        | CONSTRAINED   |                                 |
  | Redemption risk        | HIGH/MED/LOW  | e.g., gate at 10% net assets    |
  | Overall exit profile   | FAVORABLE /   |                                 |
  |                        | NEUTRAL /     |                                 |
  |                        | ADVERSE       |                                 |

Target: 1,000–1,400 words total (Section 1 + Section 2 combined).
Return JSON: {{"section_text": "...markdown..."}}
""",

    "ch04_sponsor": """\
You are writing the **Sponsor & Management Analysis** chapter.

CRITICAL: This chapter analyzes the EXTERNAL deal sponsor/manager — the
counterparty identified in deal_identity.sponsor_name. "Netz Private Credit
Fund" and its affiliates (Netz Asset Gestão, Necker Finance, Zedra) are the
INVESTOR SIDE, NOT the sponsor being analyzed. If evidence chunks mention
Netz entities, those describe OUR fund's governance — do not conflate them
with the deal sponsor's profile.

Using the sponsor profile and key persons data from the EvidencePack
AND the raw evidence chunks provided:
  • Sponsor track record and AUM (of the EXTERNAL manager)
  • Key person backgrounds, names, titles, and roles — you MUST extract
    every named individual found in the evidence.  Present them as a
    MANDATORY table immediately after sponsor profile:

    | Name | Title | Role in Deal | Background | Risk Signal            |
    |------|-------|--------------|-------------------------|------------------------|
    | ...  | ...   | ...          | ...                     | NONE / LOW / MED / HIGH |

    Sources: org charts, management bios, LPAs, subscription agreements,
    compliance docs.  If a person appears in any evidence chunk — include them.
    After the table, write narrative governance assessment.

    Present governance red flags (if any) as a second table:

    | Flag | Severity     | Evidence (doc + section) | Recommended Action |
    |------|--------------|--------------------------|-------------------|
    | ...  | HIGH/MED/LOW | ...                      | ...               |

  • Governance structure assessment — describe the DEAL TARGET's
    governance framework (board, quorum, amendment thresholds) using
    evidence from the deal's own documents (LPA, subscription docs).
    Do NOT use Netz's fund constitution or offering memorandum to
    describe the deal sponsor's governance — those describe the
    INVESTOR.
  • Red flags (if any)
  • Alignment of interest with LPs
  • Service provider ecosystem — map the DEAL TARGET's service
    providers (administrator, custodian, auditor, legal counsel).
    CRITICAL: Zedra Fund Administration is Netz's administrator,
    NOT the deal's.  Do NOT list Zedra as a deal service provider.
    Only list service providers evidenced in the deal's own documents.
  • CIMA regulatory standing — if regulatory evidence for the DEAL
    TARGET is present, note its compliance posture.  CIMA evidence
    in the index typically describes Netz (the investor) — do NOT
    attribute Netz's CIMA standing to the deal sponsor.

CRITICAL: If the evidence chunks contain org charts, management lists,
biographies, or team descriptions, you MUST extract and name every
person with their role. Do NOT say \"not provided\" if names appear
anywhere in the evidence.

Do NOT fabricate — only state what is evidenced.
Target: 800-1200 words.
Return JSON: {{"section_text": "...markdown..."}}
""",

    "ch05_legal": """\
You are writing the **Legal Structure & Document Analysis** chapter.

CRITICAL ENTITY RULE: Fund constitution, offering memorandum, and CIMA
evidence in the EvidencePack describe the INVESTOR (Netz Private Credit
Fund), NOT the deal target.  Zedra Fund Administration is Netz's
administrator.  When analysing these documents, clearly attribute them
to the investor fund.  The deal target's legal structure comes from its
own LPA, credit agreements, and subscription documents.

CRITICAL — THIRD-PARTY DOCUMENT ATTRIBUTION:
The evidence may contain contracts and UCC filings from OTHER
counterparties who have SEPARATE lending arrangements with the
borrower.  Check the DEAL STRUCTURE PREAMBLE for the list of
third-party counterparties and their document filenames.
  • If a source document belongs to a third-party counterparty,
    its terms (pledges, guaranties, security interests) describe
    that SEPARATE arrangement, NOT the deal being evaluated.
  • Present third-party contracts under a dedicated sub-section
    titled "Existing Obligations & Prior Liens" — flag them as
    risk factors (subordination, competing claims, asset pledges).
  • NEVER present guaranties or pledges from a third-party contract
    as the security package of the deal under review unless the
    deal's OWN documents explicitly incorporate them.

Cover:
  • Borrower structure (SPVs, guarantors, jurisdictions)
  • Critical clauses (negative pledge, change of control, default waterfall)
  • Enforcement mechanics
  • Intercreditor arrangements
  • Existing Obligations & Prior Liens — if evidence contains contracts
    with OTHER lenders/counterparties, describe the borrower's existing
    debt obligations, pledged assets, and UCC filings.  Flag risks:
    - Are the same assets pledged to both the existing lender AND the
      deal under review?  (competing liens)
    - Does the existing facility create subordination risk?
    - Are personal guarantees shared across multiple facilities?
  • Jurisdictional risk
  • Investor fund constitution analysis — if evidence from Netz's fund
    constitution or offering memorandum is present, you MUST analyse
    (labelling these as NETZ's governance provisions):
    - Share class structure and investor rights per class
    - Amendment and modification thresholds (e.g. 75% in value required
      to amend certain provisions)
    - Quorum requirements for shareholder meetings
    - Board-approved liberalities and policy overrides — where the board
      has explicitly authorised deviations from standard investment
      policy limits (e.g. single-name concentration above policy ceiling,
      sector allocation above standard thresholds), describe each
      liberality, its scope, and any conditions or sunset clauses
    - Reserved matters requiring special majority or investor consent
    - Side letter governance — key side letter rights (MFN, co-invest,
      fee rebates, information rights) if evidenced
  • Regulatory compliance posture — if CIMA regulatory evidence is
    present, assess Netz's legal obligations arising from the regulatory
    regime (filing deadlines, audited financial statement submission,
    AML/KYC obligations).  This is the INVESTOR's regulatory posture,
    not the deal target's.

Target: 800-1200 words.  Include tables where appropriate.
Return JSON: {{"section_text": "...markdown..."}}
""",

    "ch06_terms": """\
You are writing the **Detailed Investment Terms & Covenants** chapter.

╔══════════════════════════════════════════════════════════════════════╗
║  CRITICAL — THIRD-PARTY DOCUMENT ATTRIBUTION (MANDATORY)           ║
╚══════════════════════════════════════════════════════════════════════╝

Before populating ANY term in the table or narrative below, you MUST
verify which counterparty the source document belongs to:

1. Check the DEAL STRUCTURE PREAMBLE for the list of third-party
   counterparties and their document filenames.
2. For EACH term you extract (interest rate, fees, covenants, pledges),
   check whether the source chunk's blob_name / source filename matches
   a third-party counterparty's document list.
3. If it DOES match a third-party document:
   → That term belongs to a SEPARATE, PRE-EXISTING arrangement between
     the borrower and that other counterparty.
   → Do NOT put it in the deal terms table.
   → Instead, present it in a dedicated "Existing Third-Party Facilities"
     section AFTER the deal terms analysis.
4. If it does NOT match any third-party document:
   → It is a candidate for the deal under review. Verify it further
     by checking whether the counterparty named in the document matches
     the LENDER identified in the DEAL STRUCTURE PREAMBLE.

EXAMPLE OF WHAT TO AVOID:
  • A contract between the borrower and "ACV Capital" or "AFC" showing
    "Prime + 6.25%" — this is the OTHER lender's rate, NOT the deal rate.
  • UCC filings pledging assets to a third party — these are EXISTING
    LIENS, not the deal's security package.
  • Personal guarantees in a third-party contract — these may be shared
    but must be attributed to their original contract.

Cover:
  • Rate structure (fixed/floating, spread, floor) — FROM THE DEAL'S
    OWN DOCUMENTS ONLY
  • Fees (origination, exit, PIK) — FROM THE DEAL'S OWN DOCUMENTS ONLY
  • Prepayment mechanics and call protection
  • Financial covenants (maintenance vs. incurrence)
  • Reporting requirements
  • Security package detail — FROM THE DEAL'S OWN DOCUMENTS ONLY
  • Existing Third-Party Facilities — if evidence contains contracts
    with OTHER lenders, present them in a SEPARATE sub-section:
    - Name the counterparty explicitly
    - Summarize their key terms (rate, fees, maturity, security)
    - Assess overlap with the deal under review (shared collateral,
      competing liens, cross-default provisions)
    - Flag intercreditor risk
  • Offering memorandum cross-reference — if fund constitution evidence
    is present, cross-reference the deal terms against the fund's
    authorised investment parameters:
    - Compare the deal's fee structure (management fee, performance
      allocation, carried interest) against the offering memorandum's
      fee schedule — flag any deviations
    - Compare the deal's return target against the fund's hurdle rate
      — state whether the deal clears the hurdle on a base-case basis
    - Note lock-up period compatibility — does the deal's tenor fit
      within the fund's lock-up and liquidity framework?
    - Redemption terms — assess alignment between the deal's cash flow
      profile and the fund's redemption notice periods
    - If the board has approved extrapolations or exceptions to standard
      investment policy limits for this deal, describe them and assess
      whether the exception is adequately compensated by return premium
  • Service provider fee benchmarking — if service provider evidence is
    present, note Netz's (the INVESTOR's) administrator (Zedra),
    custodian, and auditor fee arrangements and whether they are
    market-standard.  These are NETZ's service providers, NOT the deal's.

Target: 800-1200 words.
BEGIN with the following MANDATORY terms table — populate every row from
evidence or mark [NOT FOUND IN EVIDENCE].

CRITICAL: Every value in Source Document column must come from a document
that is part of the DEAL UNDER REVIEW (WMF/Netz ↔ Borrower), NOT from
a third-party counterparty's contract.  If the only source for a term
is a third-party document, mark the cell [NOT FOUND IN DEAL DOCUMENTS]
and note the third-party source in a separate table below.

| Term Parameter           | Value / Description          | Source Document | Notes |
|--------------------------|------------------------------|-----------------|-------|
| Interest Rate / Coupon   |                              |                 |       |
| Rate Type                | Fixed / Floating / PIK       |                 |       |
| Base Rate / Floor        |                              |                 |       |
| Origination Fee          |                              |                 |       |
| Exit Fee                 |                              |                 |       |
| Prepayment Premium       |                              |                 |       |
| Management Fee           |                              |                 |       |
| Performance Fee / Carry  |                              |                 |       |
| Hurdle Rate              |                              |                 |       |
| Hard Lock-up Period      |                              |                 |       |
| Soft Lock-up Period      |                              |                 |       |
| Redemption Notice Period |                              |                 |       |
| Gate Threshold           |                              |                 |       |
| Tenor / Maturity         |                              |                 |       |
| Security Package         |                              |                 |       |

Write narrative analysis BELOW the table.  Do not repeat table data
in the narrative — build on it analytically.
Return JSON: {{"section_text": "...markdown..."}}
""",

    "ch07_capital": """\
You are writing the **Capital Structure Analysis** chapter.

THIRD-PARTY DOCUMENT ATTRIBUTION:
If evidence contains contracts or UCC filings from OTHER lenders
(listed in the DEAL STRUCTURE PREAMBLE as third-party counterparties),
their liens and security interests represent EXISTING DEBT on the
borrower's balance sheet.  Include them in the capital structure as
"Existing Prior Obligations" but do NOT conflate them with the deal
under review.  Clearly separate:
  • The deal under review (WMF/Netz → Borrower)
  • Existing third-party facilities (Other Lender → Borrower)

Include a capital structure TABLE showing:
  • Each tranche (senior, mezzanine, equity)
  • Size, rate, priority
  • LTV / attachment points

Analyse the fund's position in the waterfall.  After the capital
structure table, include a MANDATORY WATERFALL PRIORITY table:

| Priority         | Tranche | Amount | Rate | Attachment | Detachment | Netz Position? |
|------------------|---------|--------|------|------------|------------|----------------|
| 1st Lien Senior  | ...     | ...    | ...  | 0%         | X%         | YES / NO       |
| 2nd Lien / Mezz  | ...     | ...    | ...  | X%         | Y%         | YES / NO       |
| Equity / Junior  | ...     | ...    | ...  | Y%         | 100%       | YES / NO       |

Mark Netz's position explicitly in every row.  If fund-of-funds structure,
show both layers (Netz → vehicle → underlying assets).
Use [DATA GAP] for cells not supported by evidence.

  • If fund constitution evidence is present, assess whether the
    deal's capital structure is consistent with the fund's investment
    policy — specifically the permitted leverage ratio, maximum
    single-borrower exposure, and any board-approved exceptions
  • Note any capital call mechanics from the offering memorandum that
    affect the fund's ability to fund this position

Target: 500-800 words.
Return JSON: {{"section_text": "...markdown..."}}
""",

    "ch08_returns": """\
You are writing the **Return Modeling** chapter.

Cover:
  • Base case IRR and multiple (cite quant data from EvidencePack)
  • Fee income (origination, exit)
  • Cash flow timing
  • Sensitivity to rate changes and prepayment
  • Comparison to fund hurdle rate — if fund constitution evidence
    specifies the hurdle rate (e.g. 8% preferred return), explicitly
    compare the deal's projected return against this threshold and
    state the excess spread
  • Fee waterfall impact — if offering memorandum evidence describes
    the distribution waterfall (return of capital → preferred return
    → GP catch-up → carried interest), model the net-to-LP return
    after the waterfall is applied
  • If performance allocation / incentive fee evidence is available,
    quantify the fee drag on gross-to-net returns

Present return analysis in TWO MANDATORY tables:

TABLE 1 — Base Case Return Model:

| Return Component               | Gross | Fee Drag | Net to LP | Source |
|--------------------------------|-------|----------|-----------|--------|
| Base Yield / Coupon            |       |          |           |        |
| Origination Fee (annualised)   |       |          |           |        |
| Exit Fee (annualised)          |       |          |           |        |
| Management Fee                 |       | (-)      |           |        |
| Performance Fee (if triggered) |       | (-)      |           |        |
| **Net IRR (estimated)**        |       |          | ✓         |        |
| vs. Hurdle Rate                |       |          | above/below |      |

TABLE 2 — Sensitivity Analysis:

| Scenario                | Gross IRR | Net IRR | vs. Hurdle  | Time to Exit |
|-------------------------|-----------|---------|-------------|--------------|
| Base Case               |           |         |             |              |
| Rate +200bps            |           |         |             |              |
| Rate −200bps            |           |         |             |              |
| Default Rate ×2         |           |         |             |              |
| Prepayment at Year 1    |           |         |             |              |
| Stress (gate activated) |           |         |             |              |

TABLE 2B — 2-Way Sensitivity Matrix (Net IRR):
If sufficient data exists, produce a 2-way sensitivity matrix showing Net IRR
under varying default rates AND rate movements simultaneously:

| Net IRR        | Rate −100bps | Base Rate | Rate +100bps | Rate +200bps |
|----------------|-------------|-----------|--------------|--------------|
| Default 1×     |             |           |              |              |
| Default 1.5×   |             |           |              |              |
| Default 2×     |             |           |              |              |
| Default 3×     |             |           |              |              |

If insufficient data to populate the 2-way matrix, omit TABLE 2B and state:
"[Insufficient data for 2-way sensitivity — single-factor analysis only]"

TABLE 2C — Returns Attribution (decompose the Base Case return):

| Return Driver                     | Contribution to Gross IRR | Notes              |
|-----------------------------------|---------------------------|--------------------|
| Base Yield / Coupon Income        |                           | Primary driver     |
| Origination Fee (annualised)      |                           |                    |
| Exit / Prepayment Fee (ann.)      |                           |                    |
| Capital Appreciation / Discount   |                           | If applicable      |
| PIK Accrual (if applicable)       |                           |                    |
| **Total Gross IRR**               |                           |                    |
| Less: Management Fee              |                           | (fee drag)         |
| Less: Performance Fee             |                           | (fee drag)         |
| **Net IRR to LP**                 |                           |                    |

Use [DATA GAP] for cells not supported by evidence.  For TABLE 2C, derive
from evidenced fee structure — even if approximate, show the decomposition
to help the IC understand WHERE returns are coming from.

Use [DATA GAP] for any cell not supported by evidence.

=== MISSING-DATA FALLBACK PROTOCOL ===

When fund-specific data is not available in the EvidencePack for a table cell:
1. FIRST check whether a reasonable proxy can be derived from available evidence
   (e.g. stated 12-month return of 10.83% → use as base yield).
2. If a proxy exists, use it and label clearly:
   "~10.8% (stated 12-mo return)" or "Est. 1.5% (derived from credit policy LTV)"
3. If market_benchmarks data is available, use the benchmark median as calibration
   point and label: "~11.0% (PitchBook median proxy, direct lending 2022 vintage)"
4. Use [DATA GAP] ONLY when no proxy, derivation, or benchmark calibration is
   possible — i.e. the parameter is truly unknowable from available evidence.
5. NEVER fill an entire table column or row with [DATA GAP]. If most cells would
   be [DATA GAP], consolidate into a "Data Availability" narrative paragraph
   below the table explaining what is missing and what would be needed.

=== MARKET BENCHMARK CONTEXT ===

If the EvidencePack contains a `market_benchmarks` section (non-empty), you MUST
include a mandatory third table grounding this deal's returns against third-party
benchmark data from PitchBook, Preqin, Bloomberg, or equivalent sources:

TABLE 3 — Market Position vs. Benchmark:

| Metric         | This Deal | PB/Preqin Median | Top Quartile | Top Decile | Vintage | Source |
|----------------|-----------|------------------|--------------|------------|---------|--------|
| Net IRR        |           |                  |              |            |         |        |
| Gross Multiple |           |                  |              |            |         |        |
| DPI            |           |                  |              |            |         |        |
| Yield / Coupon |           |                  |              |            |         |        |

For each benchmark row, cite the publisher and reference_date from the benchmark chunk.
Example: "14.2% Net IRR vs. PB Median 11.8% for direct lending vintage 2022 (PitchBook Q3-2024)"
If no benchmark data is available in the EvidencePack, omit TABLE 3 and note:
"[No third-party benchmark data available — market_benchmarks empty in EvidencePack]"

Then write narrative.
Target: 600-1000 words.
Return JSON: {{"section_text": "...markdown..."}}
""",

    "ch09_downside": """\
You are writing the **Downside Scenario Model** chapter.

Cover:
  • Recovery assumptions under stress
  • Collateral valuation stress
  • Default probability assessment
  • Loss given default estimate
  • Worst-case IRR / multiple
  • Regulatory risk — if CIMA regulatory evidence is present, model
    the downside scenario of a regulatory enforcement action against
    the INVESTOR (Netz Private Credit Fund) — licence suspension,
    mandatory fund wind-down — and its impact on recovery timelines.
    CIMA evidence in the index describes Netz, NOT the deal target.
  • Service provider disruption — if service provider evidence is
    present, assess the impact of a key service provider termination
    at the INVESTOR level (e.g. Zedra resignation as administrator)
    on Netz's operations and NAV reporting.  Zedra is Netz's
    administrator, NOT the deal target's.
  • Offering memorandum constraints — if evidence shows lock-up periods
    or limited redemption windows, assess how these affect investor
    exit under stress and whether the fund has liquidity mechanisms
    (side pockets, gates, suspension powers)

Present downside scenarios as a MANDATORY comparison table:

| Parameter                  | Mild Stress   | Moderate Stress | Severe Stress  |
|----------------------------|---------------|-----------------|----------------|
| Default Rate Assumption    | 1–2%          | 3–5%            | 8–12%          |
| Recovery Rate              | 70–80%        | 50–65%          | 20–40%         |
| Collateral Haircut         | 10%           | 20–25%          | 30–40%         |
| Redemption Pressure        | ~15% NAV      | ~30% NAV        | >50% NAV       |
| Gate Triggered?            | NO            | POSSIBLE        | YES            |
| Suspension Triggered?      | NO            | NO              | POSSIBLE       |
| Net IRR Impact             | [derive]      | [derive]        | [derive]       |
| Time to Exit (months)      | [base]        | [+X months]     | [+Y months]    |
| NAV per Share Impact       | −X%           | −Y%             | −Z%            |

Derive all values from evidenced base-case parameters.  Where fund-specific
data is unavailable, use the following fallback protocol:
1. Derive from available evidence where possible (e.g. stated return, LTV,
   average term) and label clearly: "Est. based on [source]"
2. Calibrate using macro stress data (DRSFRMACBS, DRALACBN delinquency
   trends) and label: "Calibrated from macro data"
3. Use market benchmark medians (PitchBook / Preqin) as proxy ranges
   and label: "~X% (PB median proxy)"
4. Use [DATA GAP] ONLY when the parameter is truly unknowable and no
   reasonable proxy exists. NEVER fill an entire column with [DATA GAP].
5. If data gaps are significant, add a "Data Availability" paragraph below
   the table summarising what is missing and what documents would resolve it.
Write narrative analysis below the table.
Target: 600-900 words.

=== MACRO STRESS ASSESSMENT ===
macro_snapshot.stress_severity.level   = {stress_level}  (NONE / MILD / MODERATE / SEVERE)
macro_snapshot.stress_severity.score   = {stress_score}  (0-100)
Active stress triggers: {stress_triggers}
Real estate sub-stress:  {real_estate_stress}
Credit sub-stress:       {credit_stress}
Rate/spread sub-stress:  {rate_stress}
Use DRSFRMACBS (single-family mortgage delinquency, macro_snapshot.mortgage)
and DRALACBN (all-loan delinquency, macro_snapshot.credit_quality) to
calibrate the BASE CASE delinquency assumption in the stress model —
if either series trend_direction == "rising", tighten the base-case input.
The stress_severity.level should anchor the scenario-selection narrative:
NONE/MILD -> cite low systemic risk; MODERATE/SEVERE -> explicitly link each
trigger to the downside scenario driver in the table above.
Return JSON: {{"section_text": "...markdown..."}}
""",

    "ch10_covenants": """\
You are writing the **Covenant Strength Assessment** chapter.

Evaluate covenant quality:
  • Financial maintenance covenants (LTV, DSCR, leverage)
  • Incurrence covenants
  • Reporting frequency and cure provisions
  • Covenant headroom analysis
  • Comparison to market standard
  • Investment policy compliance — if fund constitution / offering
    memorandum evidence is present, validate the deal against the
    fund's investment policy constraints:
    - Single-name concentration limit vs. this deal's size
    - Sector / geography / asset-class allocation limits
    - Maximum tenor / weighted average life constraints
    - Leverage / borrowing limits at the fund level
    - If the board has approved extrapolations beyond standard policy
      limits for this deal, document the specific liberality granted,
      the board resolution reference (if available), and any conditions
      or sunset clauses attached
    - Assess remaining headroom after this deal is booked
  • Regulatory obligation covenants — if CIMA regulatory evidence is
    present, note Netz's (the INVESTOR's) regulatory compliance
    covenants embedded in its governing documents (e.g. mandatory
    annual audit delivery within 6 months of fiscal year-end, NAV
    reporting frequency).  Label these as INVESTOR obligations,
    not deal-level covenants.

Present ALL covenants as a MANDATORY register table:

| Covenant                   | Type        | Threshold  | Measurement | Cure Period | Headroom Est. |
|----------------------------|-------------|------------|-------------|-------------|---------------|
| [Financial Covenant 1]     | Maintenance | [value]    | [frequency] | [days]      | [if known]    |
| [Financial Covenant 2]     | Maintenance |            |             |             |               |
| [Incurrence Covenant]      | Incurrence  |            |             |             |               |
| Single-name Concentration  | Fund Policy | [limit %]  | Per deal    | Board vote  | [remaining]   |
| Sector Allocation          | Fund Policy |            |             |             |               |
| CIMA Annual Audit Delivery | Regulatory  | 6mo of YE  | Annual      | N/A         |               |
| NAV Reporting Frequency    | Regulatory  |            |             |             |               |

Classify each: Financial / Fund Policy / Regulatory / Legal.
Flag any breach or headroom concern in the Headroom Est. column.
Use [NOT FOUND IN EVIDENCE] for rows with no evidentiary support.
Write narrative analysis BELOW the table.

IMPORTANT — LOCK-UP / REDEMPTION DISAMBIGUATION RULE:
In the source documents, "12" appears in two distinct contexts:
  (1) "12 months" = early redemption window (investor may exit after 12 months at a NAV discount)
  (2) "2 years" = hard lock-up period (the actual lock-up duration)
These are DIFFERENT terms. Never conflate them. If a chunk contains "12" in proximity
to "lock" or "lock-up", it refers to the early redemption window (12 months), NOT the
lock-up duration. The hard lock-up is always 2 years. If a chunk appears to contradict
this, flag as [CHUNK CONFLICT] but do not change the 2-year figure without explicit evidence.

Target: 500-800 words.
Return JSON: {{"section_text": "...markdown..."}}
""",

    "ch11_risks": """\
You are writing the **Key Risks** chapter.

CRITICAL ENTITY RULE: Fund constitution, CIMA regulatory evidence, and
service provider data in the EvidencePack describe the INVESTOR (Netz
Private Credit Fund), NOT the deal target.  Zedra Fund Administration
is Netz's administrator.  When assessing regulatory, governance, or
service-provider risks from these documents, attribute them to the
correct entity.

Produce a ranked risk register:
  • List ALL material risks ranked HIGH → MEDIUM → LOW
  • For each: risk factor, severity, mitigation, residual exposure
  • Include credit, market, operational, legal, concentration risks
  • Use a risk register TABLE
  • Regulatory compliance risk — if CIMA regulatory evidence is present,
    assess NETZ's (the investor fund's) regulatory risks:
    - Filing deadline risk (missed CIMA filings → penalties, licence risk)
    - AML/KYC compliance risk per Cayman AML regulations
    - NAV reporting and audited financial statement delivery risk
    - Regulatory change risk (upcoming CIMA rule revisions)
    - Penalty exposure for non-compliance where evidenced
    Label these clearly as INVESTOR FUND risks, not deal-level risks.
  • Service provider risk — if service provider evidence is present,
    assess risks at the INVESTOR (Netz) level:
    - Key-person dependency at Netz's service providers
    - Termination notice periods and transition adequacy
    - Liability cap adequacy
    - Exclusivity / lock-in clauses
    CRITICAL: Zedra is Netz's administrator.  Do NOT describe Zedra's
    risks as applying to the deal target.
  • Governance risk — if Netz's fund constitution evidence is present,
    assess INVESTOR-level governance risks:
    - Investor concentration (single LP controlling >50% of votes)
    - Low quorum thresholds enabling minority-driven decisions
    - Broad amendment powers without investor consent
    - Conflicts of interest in related-party service arrangements

Use this EXACT risk register format — minimum 8 rows, maximum 15 rows:

| # | Risk Factor | Category | Severity | Probability | Mitigation | Residual | Source |
|---|-------------|----------|----------|-------------|------------|----------|--------|
| 1 | ...         | Credit   | HIGH     | HIGH        | ...        | MED      | [source filename] |

Categories: Credit | Market | Operational | Legal | Governance | Regulatory | Liquidity
Severity and Probability: HIGH / MEDIUM / LOW
Order: all HIGH severity first, then MEDIUM, then LOW.

MINIMUM RISK COUNTS PER CATEGORY:
  • Credit: ≥ 2 rows
  • Market: ≥ 1 row
  • Operational: ≥ 1 row
  • Legal: ≥ 1 row
  • At least 1 row from Governance OR Regulatory
If a category lacks evidence, still include a row with Probability LOW
and note "No evidence of this risk in current documentation."

IMPACT QUANTIFICATION:
For each risk, quantify the potential financial impact where possible
(e.g., "~5% NAV reduction", "$X million exposure", "200bps yield
compression").  If quantification is not feasible, state the qualitative
impact channel (e.g., "reputational", "regulatory penalty", "liquidity
strain").

SOURCE COLUMN RULE:
In the Source column of the risk register table, write the actual source document
filename from the evidence chunks, e.g. "credit_policy.pdf" or "2025 Q1 CACO Fact Card.pdf".
Do NOT write "[doc]" — always use the real source filename. If multiple sources
support a risk, list them separated by "; ". If no source is available, write "—".

Target: 600-1000 words.
Return JSON: {{"section_text": "...markdown..."}}
""",

    "ch12_peers": """\
You are writing the **Peer Comparison** chapter.

Compare this deal to peers using this MANDATORY table structure:

| Fund / Deal       | Strategy | Size | Gross Yield | Net IRR | LTV | Tenor | Gate | Lock-up | Source   |
|-------------------|----------|------|-------------|---------|-----|-------|------|---------|----------|
| **[THIS DEAL]**   | ...      | ...  | ...         | ...     | ... | ...   | ...  | ...     | Indexed  |
| Peer 1            | ...      | ...  | ...         | ...     | ... | ...   | ...  | ...     | [source] |
| Peer 2            | ...      | ...  | ...         | ...     | ... | ...   | ...  | ...     |          |

Bold the subject deal row.  Minimum 3 rows (this deal + 2 peers).
If peer data is not in indexed documents, use macro context and flag
with the short code [Mkt est.] in the Source column.
After the table, add a footnote line:
> *Mkt est. = Market estimate — not sourced from indexed deal documents.*
Do NOT fabricate specific fund names.
  • Relative value assessment narrative below the table
  • State whether this deal is above / at / below market on each key dimension
If peer data is limited, document which dimensions lack comparables.

=== MARKET POSITION TABLE (MANDATORY IF BENCHMARK DATA IS AVAILABLE) ===

If the EvidencePack contains a `market_benchmarks` section (non-empty), you MUST
include the following table sourced exclusively from third-party benchmark data
(PitchBook, Preqin, Bloomberg, etc.):

TABLE 2 — Market Position vs. Benchmark Universe:

| Metric             | This Deal | PB/Preqin Median | PB Top Quartile | PB Top Decile | Vintage | Publisher | Reference Date |
|--------------------|-----------|------------------|-----------------|---------------|---------|-----------|----------------|
| Net IRR            |           |                  |                 |               |         |           |                |
| Gross Multiple     |           |                  |                 |               |         |           |                |
| Management Fee     |           |                  |                 |               |         |           |                |
| Performance Fee    |           |                  |                 |               |         |           |                |
| Lock-up Period     |           |                  |                 |               |         |           |                |
| Redemption Gate    |           |                  |                 |               |         |           |                |
| Target Fund Size   |           |                  |                 |               |         |           |                |

Rules for TABLE 2:
- Cite only data from market_benchmarks chunks in the EvidencePack.
- Use [DATA GAP] for any cell not covered by benchmark evidence.
- Citation format: "X% per [Publisher] [reference_date] ([asset_class] [vintage_year])"
- Do NOT use general market knowledge for this table — benchmark chunks only.
- If market_benchmarks is empty or missing: omit TABLE 2 and state:
  "[No benchmark data available — market_benchmarks empty in EvidencePack]"

After TABLE 2, write a "Benchmark Positioning" narrative (2-3 paragraphs) assessing
whether this deal is in the top quartile, median, or below-median range for each key
metric, citing the specific benchmark source.

Target: 500-800 words.
Return JSON: {{"section_text": "...markdown..."}}
""",

    "ch13_recommendation": """\
You are writing the **Final Recommendation** chapter of an institutional
Investment Memorandum.

CRITICAL: "Netz Private Credit Fund" is the INVESTOR (our fund). The deal
sponsor/manager is the EXTERNAL counterparty in deal_identity.sponsor_name.
Frame the recommendation as: whether Netz should invest IN this deal.

THIS IS A SYNTHESIS-ONLY CHAPTER.  You receive:
  • The EvidencePack summary (frozen facts)
  • Quant profile summary
  • Critic findings (adversarial review results)
  • Policy compliance status and breaches
  • Sponsor red flags
  • Chapter summaries from ch01-ch12 (key conclusions from each chapter)

You must:
  1. State the IC recommendation: INVEST / PASS / CONDITIONAL
  2. Confidence level: HIGH / MEDIUM / LOW
  3. Key conditions for approval (if CONDITIONAL):
     - Include any board-approved liberality or policy override that is
       a prerequisite for the investment (e.g. "Board resolution required
       to approve single-name concentration above 15% policy limit")
     - Include any pending regulatory filing or compliance item that
       must clear before funding
  4. Summary rationale (3-5 bullet points) — where applicable, ground
     the rationale in:
     - Fund constitution / offering memorandum permissions
     - Regulatory compliance standing from CIMA evidence
     - Service provider adequacy assessment
  5. Board override requirements (if any concentration/policy breaches)
     — if the deal requires a policy exception, state whether the offering
     memorandum permits the board to grant such exception and under what
     conditions
  6. Governance and regulatory pre-conditions — list any governance
     actions (board vote, investor consent) or regulatory clearances
     required before the investment can proceed

IC POLICY RULE — LOCK-UP CLASSIFICATION:
The existence of an early redemption mechanism — even with a NAV penalty —
disqualifies a fund from being classified as a "hard lock-up" for blocking
purposes. A hard lock-up block exists only when there is NO exit mechanism
of any kind during the lock period.
For any deal where early redemption is available (e.g. after 12 months at a
NAV discount), lock_up_breach = FALSE. The NAV discount should be flagged as
a liquidity cost in return modeling, but does NOT constitute a policy violation.
Do NOT cite lock-up as a blocking/PASS trigger when early redemption exists.
Evaluate the final recommendation based on remaining factors independently.

Be decisive.  Do NOT equivocate.
Target: 400-600 words.

Return JSON:
{{
    "section_text": "...markdown...",
    "recommendation": "INVEST|PASS|CONDITIONAL",
    "confidence_level": "HIGH|MEDIUM|LOW"
}}
""",

    "ch14_governance_stress": """\
You are writing the **Governance Under Adverse Event & Stress Analysis** chapter
of an institutional Investment Committee Memorandum.

CRITICAL ENTITY DISAMBIGUATION:
This chapter analyses TWO separate governance frameworks — you MUST
distinguish them throughout:

  1. THE INVESTOR FUND — Netz Private Credit Fund (Cayman Islands):
     • Fund constitution, offering memorandum, CIMA regulatory evidence
     • Administrator: Zedra Fund Administration (Cayman) Ltd.
     • Board of Directors, Investment Committee
     These documents describe OUR fund, the entity making the investment.

  2. THE DEAL TARGET — the fund/vehicle managed by the EXTERNAL sponsor
     identified in deal_identity.sponsor_name:
     • LPA, subscription docs, credit agreements, side letters
     • The deal sponsor's own governance structure

When populating tables, label each row with "Investor Fund" or "Deal
Target" so the IC knows which entity each power/risk applies to.
Zedra is NETZ's administrator — NEVER attribute Zedra to the deal target.

This chapter has three parts.  Complete all three in sequence before returning.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PART 1 — GOVERNANCE UNDER ADVERSE EVENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1.1  AUTHORITY MAPPING — ADVERSE EVENT POWERS
Enumerate, directly from governing documents, who holds each power.
Add a column "Entity" to clarify whether the power belongs to the
Investor Fund (Netz) or the Deal Target:

  | Trigger / Event                         | Entity       | Authority Holder | Governing Clause | Conditions / Notice |
  |-----------------------------------------|--------------|-----------------|------------------|---------------------|
  | NAV suspension                          | [Inv/Deal]   |                 |                  |                     |
  | Redemption gate / deferral              | [Inv/Deal]   |                 |                  |                     |
  | Side pocket / segregated portfolio      | [Inv/Deal]   |                 |                  |                     |
  | Forced redemption of investor           | [Inv/Deal]   |                 |                  |                     |
  | Investment manager removal (with cause) | [Inv/Deal]   |                 |                  |                     |
  | Investment manager removal (w/o cause)  | [Inv/Deal]   |                 |                  |                     |
  | Board director removal                  | [Inv/Deal]   |                 |                  |                     |
  | Regulatory override (CIMA)              | Investor     |                 |                  |                     |

For each populated row, quote the key operative phrase (≤ 120 characters)
from the governing document and cite the section reference (e.g. "Art. 14.2").
If the full clause is material, reproduce it verbatim in a note block
immediately below the table using a Markdown blockquote (> ).
Do NOT embed full legal clause text inside table cells.  Mark any row as [DATA GAP: description]
if the evidence does not specify.

1.2  LIQUIDITY REALITY — STATED vs. EFFECTIVE vs. WORST-CASE
  • Stated liquidity terms: notice period, redemption frequency, lock-up.
  • Effective liquidity: adjusting for gate thresholds, board discretion, and
    side-pocket powers.
  • Worst-case exit timeline: if board suspends + large redemption queue + CIMA
    inquiry — how many months to full exit?

1.3  ADVERSE EVENT SCENARIO ANALYSIS
Model each scenario using ONLY evidence in the EvidencePack and Chunks:

  Scenario A — Large-Scale Redemption Surge (>20 % of NAV in one window):
    Who can trigger gate?  What is the threshold?  What is redemption queue
    priority (FIFO, pro-rata)?  Is there a cash reserve / credit line specified?
    Must investors be notified of gate activation?  Within what period?

  Scenario B — Borrower Concentration Default (top borrower defaults):
    Maximum single-borrower exposure permitted by credit / investment policy.
    What triggers mandatory valuation / impairment?  Is there a board resolution
    requirement?  How does this flow into NAV reporting?

  Scenario C — Regulatory Intervention (CIMA action):
    Powers that CIMA holds over the INVESTOR fund (Netz) — licence
    suspension, director substitution, mandatory wind-down.  What
    investor rights survive CIMA appointment of a receiver or official
    liquidator?  Cite CIMA regulatory context if present.
    IMPORTANT: CIMA evidence in the index describes Netz, NOT the deal
    target.  Frame this scenario as: "What happens to our investment
    if CIMA intervenes against Netz?"

  Scenario D — Investment Manager Removal / Key-Person Event:
    Analyse at BOTH entity levels:
    (a) At the INVESTOR level: Netz's own key-person provisions (from
        fund constitution / IMA).
    (b) At the DEAL level: the external sponsor's key-person clause,
        successor appointment, and transition timeline (from LPA/deal
        docs).  Who manages the deal's assets during transition?

1.4  CONFLICT & INCENTIVE ANALYSIS UNDER STRESS
  • Management fee continuation during NAV decline / suspension — does the
    governing document allow fee accrual even if redemptions are suspended?
  • Performance fee crystallisation timing — is there a high-water mark reset?
    Can performance fees be paid while investor redemptions are gated?
  • Related-party service arrangements — identify any service provider with
    a conflicted relationship to the investment manager; assess whether the
    board has independent oversight to terminate such arrangements.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PART 2 — DOWNSIDE MODELLING & STRESS ANALYSIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

2.1  BASE CASE RECONSTRUCTION
Reconstruct from the evidence:

  | Parameter                  | Value | Source (blob_name, section) |
  |----------------------------|-------|------------------------------|
  | Current NAV per share      |       |                              |
  | Total fund AUM             |       |                              |
  | Number of portfolio loans  |       |                              |
  | Weighted average yield     |       |                              |
  | Weighted average LTV       |       |                              |
  | Fund leverage ratio        |       |                              |
  | Redemption notice period   |       |                              |

Use [DATA GAP: description] for any cell not supported by evidence.

2.2  CREDIT STRESS SCENARIOS
For each scenario, derive outputs from the evidenced base case above.
Present ALL three scenarios in a single MARKDOWN TABLE (pipe-delimited).
Do NOT use box-drawing characters (┌─┐│└─┘).  Use standard markdown:

  | Parameter                    | Mild Stress                    | Moderate Stress                | Severe Stress                  |
  |------------------------------|--------------------------------|--------------------------------|--------------------------------|
  | Scenario Description         | 1–2 borrower defaults          | 3–5 borrowers impaired         | Systemic freeze, >50% impaired |
  | Default Rate Assumption      |                                |                                |                                |
  | Recovery Rate Assumption     |                                |                                |                                |
  | NAV Impact (estimated)       |                                |                                |                                |
  | Time to NAV Recovery         |                                |                                |                                |
  | Gate / Suspension Breached?  |                                |                                |                                |
  | Key Mitigants                |                                |                                |                                |
  | Residual Risk                |                                |                                |                                |

FALLBACK DERIVATION PROTOCOL for stress scenario values:
  1. Derive from the Base Case Reconstruction above (yield, LTV, AUM,
     number of loans) wherever possible.  Label: "Est. from [source]"
  2. If base-case data is partial, calibrate using macro stress indicators
     (DRSFRMACBS, DRALACBN delinquency trends, if present in the
     EvidencePack).  Label: "Calibrated from macro data"
  3. Use market benchmark medians (PitchBook / Preqin private debt) as
     proxy ranges.  Label: "~X% (PB median proxy)"
  4. Use [DATA GAP] ONLY when the parameter is truly unknowable and no
     reasonable proxy exists.  NEVER fill an entire column with [DATA GAP].

2.3  SENSITIVITY TABLE
Present as a standard MARKDOWN TABLE.  Derive values from the Base Case
Reconstruction using simple arithmetic adjustments.  NEVER fill the entire
table with [DATA GAP] — use the following derivation protocol:

  1. Base Case column: use evidenced values (target IRR, NAV, yield, LTV).
  2. Rate +200bps: adjust floating-rate income proportionally; estimate
     impact on fixed-rate portfolio value.
  3. Default Rate x2: double the base default assumption and apply the
     recovery rate to estimate NAV/IRR impact.
  4. LTV Floor -20%: reduce collateral values by 20% and assess covenant
     headroom and potential margin calls.
  5. Label derived values: "Est. from [source]".
  6. Use [DATA GAP] ONLY for individual cells where no derivation is possible.

  | Output Metric        | Base Case | Rate +200bps | Default Rate ×2 | LTV Floor -20% |
  |----------------------|-----------|--------------|-----------------|----------------|
  | Gross IRR            |           |              |                 |                |
  | Net IRR to LP        |           |              |                 |                |
  | NAV per share        |           |              |                 |                |
  | Time to exit (months)|           |              |                 |                |

2.4  TIME-TO-CASH CALCULATION
  • Best Case: orderly redemption, no gate, market conditions normal.
  • Base Case: partial gate activation, 2-quarter exit queue.
  • Stress Case: full suspension, regulatory inquiry, forced asset sales.
  
  State assumptions for each case.  Mark as [DATA GAP] if governing documents
  do not specify gate / suspension thresholds.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PART 3 — INSTITUTIONAL CONCLUSIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

3.1  GOVERNANCE RESILIENCE RATING
Choose ONE: **ADEQUATE / QUALIFIED / INADEQUATE**

Justify by citing:
  (a) Whether the governing document provides clear, enforceable adverse-event
      powers with defined triggers and notice periods.
  (b) Whether the board maintains independence from the investment manager under
      stress conditions.
  (c) Whether investor protections survive regulatory intervention.
  (d) Whether conflicts are structurally managed or pose residual IC-level risk.

3.2  LIQUIDITY RISK CONCLUSION
Present as a standard MARKDOWN TABLE (do NOT use box-drawing characters):

  | Metric                         | Assessment                               |
  |--------------------------------|------------------------------------------|
  | Stated Liquidity               | [X-day notice, quarterly redemption]     |
  | Effective Liquidity            | [adjusted for gates / board discretion]  |
  | Worst-Case Exit Timeline       | [...] months                             |
  | Liquidity Risk Classification  | LOW / MEDIUM / HIGH / CRITICAL           |
  | Key Evidence Source            | [blob_name, section]                     |

3.3  FIDUCIARY RECOMMENDATION ADJUSTMENT
State: MAINTAIN / CONDITION / REDUCE / DEFER
  
  CONDITION or REDUCE must be accompanied by:
    • The specific governance or liquidity deficiency triggering the adjustment.
    • The exact section of the governing document (or DATA GAP) that is the basis.
    • The remediation required before the condition is lifted.
  
  DEFER must be accompanied by:
    • The specific missing information (DATA GAP) that prevents a conclusion.
    • The document(s) that, if provided, would allow a definitive assessment.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EPISTEMIC CONSTRAINTS — MANDATORY (violation = hard fail)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  • Every factual claim must cite blob_name + section from the EvidencePack
    or Chunks.  No uncited assertions.
  • When data is not present in the index, write [DATA GAP: description of
    what is missing and where it would normally be found].
  • For PART 1 (Governance): Do NOT substitute market assumptions or general
    knowledge for fund-specific data.  If the governing document does not
    address a mechanism, state this explicitly.
  • For PART 2 (Stress/Sensitivity): You MUST derive estimates from available
    evidence (target yield, AUM, LTV, fee structure, loan count, etc.)
    rather than marking every cell as [DATA GAP].  Apply the FALLBACK
    DERIVATION PROTOCOL above.  Only use [DATA GAP] for individual cells
    where no reasonable derivation is possible.
  • For suspension / gate / side-pocket mechanics, quote verbatim from the
    governing document.  Paraphrase is not acceptable for these provisions.
  • If a scenario outcome depends on board discretion (e.g. "the board may"),
    state this uncertainty and do NOT model it as a definitive outcome.

IMPORTANT — LOCK-UP / REDEMPTION DISAMBIGUATION RULE:
In the source documents, "12" appears in two distinct contexts:
  (1) "12 months" = early redemption window (investor may exit after 12 months at a NAV discount)
  (2) "2 years" = hard lock-up period (the actual lock-up duration)
These are DIFFERENT terms. Never conflate them. If a chunk contains "12" in proximity
to "lock" or "lock-up", it refers to the early redemption window (12 months), NOT the
lock-up duration. The hard lock-up is always 2 years. If a chunk appears to contradict
this, flag as [CHUNK CONFLICT] but do not change the 2-year figure without explicit evidence.

Target: 1 500–2 500 words across all three parts.
Return JSON: {{"section_text": "...markdown..."}}
""",
}

# Max output tokens per chapter — generous for institutional quality
_CHAPTER_MAX_TOKENS: dict[str, int] = {
    "ch01_exec": 6000,
    "ch02_macro": 6000,
    "ch03_exit": 6000,
    "ch04_sponsor": 8000,
    "ch05_legal": 8000,
    "ch06_terms": 8000,
    "ch07_capital": 6000,
    "ch08_returns": 6000,
    "ch09_downside": 6000,
    "ch10_covenants": 6000,
    "ch11_risks": 6000,
    "ch12_peers": 6000,
    "ch14_governance_stress": 10000,
    "ch13_recommendation": 4000,
}


# ---------------------------------------------------------------------------
# Citation governance — Evidence Law v5.0
# ---------------------------------------------------------------------------

_EVIDENCE_LAW = """

## IDENTITY DISAMBIGUATION — MANDATORY (v3.0)

CRITICAL IDENTITY RULE — read this BEFORE processing any evidence:

"Netz Private Credit Fund" (and its affiliated vehicles: WMF Corp,
Netz Private Credit US Blocker) is the INVESTING FUND — OUR fund.
It is NOT the sponsor, manager, borrower, or deal counterparty.

INVESTOR-SIDE ENTITIES (belong to Netz, NOT the deal):
  • Netz Asset Gestão de Recursos LTDA — investment adviser
  • Necker Finance (Suisse) SA — affiliated entity
  • Zedra Fund Administration (Cayman) Ltd. — Netz's FUND ADMINISTRATOR
    (handles NAV calculation, AML/KYC, CIMA reporting for NETZ)
  • CIMA regulatory evidence — describes NETZ's regulatory environment
  • Fund constitution / offering memorandum — describes NETZ's governance
  • WMF Corp — Netz subsidiary (LENDER in direct loan deals)

NEVER attribute any of these entities or documents to the deal target.
When you see "the administrator" in evidence chunks from the fund
constitution, it means Zedra — Netz's administrator.  NOT the deal's.

### DEAL STRUCTURE AWARENESS (v3.0)

The user_content begins with a DEAL STRUCTURE PREAMBLE that explicitly
classifies entity roles. You MUST follow it:

  - If deal_structure == "direct_loan":
      • The BORROWER is the deal target (the entity receiving the loan).
      • The LENDER is a Netz subsidiary deploying capital.
      • There is NO external manager or sponsor.
      • Do NOT refer to a "sponsor" or "manager" — use "borrower" and "lender".
      • Chapter 4 should analyze the BORROWER's management, NOT a sponsor.
      • NEVER list lender (Netz-side) directors as deal key persons.

  - If deal_structure == "fund_investment":
      • The MANAGER/SPONSOR is the EXTERNAL counterparty.
      • Use deal_identity.sponsor_name for the external party.
      • Chapter 4 analyzes the external sponsor's track record.

If NO preamble is present, fall back to deal_identity.sponsor_name and
treat the deal as a fund investment.

When writing about "the fund" in context of the deal being evaluated,
you are referring to the TARGET fund/vehicle — not the Netz fund.
For direct loan deals, replace "fund" language with "borrower" language.

When describing the relationship, use language like:
  Fund investment: "The Netz Private Credit Fund is considering an
   investment in [Deal Name], managed by [Sponsor Name]."
  Direct loan: "WMF Corp (Netz subsidiary) is extending a revolving
   credit facility to [Borrower Name]."
NOT:
  "The proposed transaction involves the Netz Private Credit Fund..."
  "The sponsor is Netz Asset Gestão de Recursos LTDA..."
  "The borrower is WMF Corp..." (WMF Corp is the LENDER)

### THIRD-PARTY DOCUMENT ATTRIBUTION — MANDATORY (v5.0)

The DEAL STRUCTURE PREAMBLE may list THIRD-PARTY COUNTERPARTIES —
entities that have SEPARATE, PRE-EXISTING contracts with the borrower.
Their documents are in the evidence corpus because they were in the
deal folder, but their terms DO NOT describe the deal under review.

ATTRIBUTION PROTOCOL (apply to EVERY evidence chunk):

1. CHECK THE SOURCE: Before using ANY term, rate, fee, covenant, or
   security interest from an evidence chunk, check the chunk's
   blob_name / source filename against the third-party document list
   in the DEAL STRUCTURE PREAMBLE.

2. IF SOURCE MATCHES A THIRD-PARTY DOCUMENT:
   → The term belongs to a SEPARATE arrangement between the borrower
     and that other counterparty.
   → DO NOT present it as a term of the deal under review.
   → DO NOT put it in the deal terms table (ch06).
   → DO NOT include it in the deal's security package.
   → DO present it as "Existing Debt / Prior Liens" under risk analysis.
   → ALWAYS name the third-party counterparty when citing the term:
     "Under a separate facility with [Counterparty], the borrower..."

3. IF SOURCE DOES NOT MATCH ANY THIRD-PARTY DOCUMENT:
   → The term is a candidate for the deal under review.
   → Verify further by checking if the named counterparty in the
     document matches the LENDER in the DEAL STRUCTURE PREAMBLE.

4. UCC FILINGS: UCC filings from third-party counterparties show
   EXISTING LIENS on the borrower's assets.  These are a RISK FACTOR
   (competing claims, subordination risk) — NOT the deal's security.

5. PERSONAL GUARANTEES: If a personal guarantee appears in a
   third-party contract, note that the guarantor has obligations to
   MULTIPLE lenders.  This is a concentration/capacity risk factor.

## EVIDENCE LAW — MANDATORY CITATION GOVERNANCE (v5.0)

Follow these rules for EVERY chapter you produce.  Violation = hard fail.

1. **CLEAN BODY TEXT**
   Write section_text in clean, flowing Markdown.
   Do NOT include ANY inline citation markers — no [1], no [^1], no
   (Source: …), no superscripts, no footnote numbers, no parenthetical
   source references.  The body must read as polished institutional prose.

2. **EVIDENCE GROUNDING**
   Every factual claim, metric, figure, date, name, or quantitative
   assertion MUST be traceable to one of the provided Evidence Chunks
   or the EvidencePack.  If a claim cannot be traced to any provided
   source, write instead: "Not confirmed in provided documentation."
   Do NOT say "The documentation does not provide" when evidence chunks
   contain the information — read ALL evidence chunks carefully.
   NEVER write "[doc]" as a citation or source reference — always use
   the actual source document filename from the chunk header.

3. **EDGAR DATA ATTRIBUTION**
   The EvidencePack may contain SEC EDGAR filing data from MULTIPLE
   entities related to a deal (fund, sponsor, investment manager, etc.).
   Each entity is labeled DIRECT TARGET or RELATED ENTITY.
   CRITICAL RULES:
   - NEVER attribute financial metrics (AUM, leverage, total assets,
     total debt, NAV, NII) from a RELATED ENTITY to the target vehicle.
   - A publicly listed BDC/REIT managed by the same sponsor is a
     DIFFERENT vehicle from the private fund under review.
   - Use RELATED ENTITY data ONLY for: manager platform scale,
     regulatory standing, track record, and public market presence.
   - When citing any EDGAR data, ALWAYS name the specific entity and
     state its relationship to the target (e.g., "Chicago Atlantic
     Real Estate Finance (ticker: REFI), a publicly listed REIT managed
     by the same sponsor, reported total assets of $359M").
   - If a RELATED ENTITY has a going concern flag, assess contagion
     risk but do NOT assume the target shares the same condition.

4. **CITATION TRACKING**
   In the `citations` array of your JSON response, list every evidence
   chunk you actually relied upon.  Each entry:
     - `chunk_id`    — the EXACT chunk_id shown in the chunk header
     - `source_name` — human-readable source document name
     - `doc_type`    — the document-type classification
     - `excerpt`     — verbatim excerpt (≤ 120 chars) supporting the claim
     - `page`        — page number if identifiable, otherwise null

5. **RETURN FORMAT** (overrides any earlier return instruction):
   Return a single JSON object — nothing else outside the braces:
   {{
       "section_text": "…clean markdown…",
       "citations": [
           {{"chunk_id": "…", "source_name": "…", "doc_type": "…",
             "excerpt": "…", "page": null}}
       ]
   }}

   `citations` MUST contain ≥ 1 real entry.  If truly no evidence exists,
   include exactly one sentinel:
   {{"chunk_id": "NONE", "source_name": "N/A", "doc_type": "N/A",
     "excerpt": "No source evidence available for this chapter.", "page": null}}

6. **TABLE CONSISTENCY**
   Any financial metric cited in multiple chapters MUST be identical.
   If ch08 states Net IRR of X%, ch01 Executive Summary must cite the
   same figure.  If ch06 lists a principal of $Y, ch01 must match.
   Cross-check ALL numerical values, rates, dates, and amounts across
   chapters.  Inconsistency = hard fail.
   When in doubt, use the value from the primary evidence source rather
   than a derived or rounded figure from another chapter.
"""

_EVIDENCE_LAW_CH13 = """

## IDENTITY DISAMBIGUATION — MANDATORY (v1.0)

"Netz Private Credit Fund" is the INVESTING FUND (our fund), NOT the deal
sponsor or manager. The deal sponsor is the EXTERNAL counterparty.
Never identify Netz, Netz Asset Gestão, Necker Finance, or Zedra as the
deal sponsor.

## EVIDENCE LAW — MANDATORY CITATION GOVERNANCE (v4.3)

Follow these rules.  Violation = hard fail.

1. **CLEAN BODY TEXT** — No inline citation markers of any kind.
2. **SYNTHESIS-ONLY** — This chapter synthesises prior-stage outputs;
   citation tracking is limited to the EvidencePack metadata and
   structured synthesis inputs.

3. **RETURN FORMAT** (overrides any earlier return instruction):
   Return a single JSON object — nothing else outside the braces:
   {{
       "section_text": "…clean markdown…",
       "recommendation": "INVEST|PASS|CONDITIONAL",
       "confidence_level": "HIGH|MEDIUM|LOW",
       "citations": []
   }}
"""


# ---------------------------------------------------------------------------
# Evidence chunk selection
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Per-chapter chunk budgets (B — Cost Governance)
# ---------------------------------------------------------------------------
# (max_chunks, max_chars_per_chunk) per chapter.  Critical legal/governance
# chapters retain full budget; analytical chapters get moderate budget;
# lightweight chapters get minimal budget.

_CHAPTER_CHUNK_BUDGET: dict[str, tuple[int, int]] = {
    # Critical — full budget (legal text must be preserved verbatim)
    "ch05_legal":             (30, 8000),
    "ch06_terms":             (30, 8000),
    "ch14_governance_stress": (30, 8000),
    # Deep analytical — moderate budget
    "ch01_exec":              (20, 4000),
    "ch04_sponsor":           (20, 4000),
    "ch07_capital":           (15, 4000),
    "ch08_returns":           (15, 4000),
    "ch09_downside":          (15, 4000),
    "ch10_covenants":         (20, 4000),
    "ch11_risks":             (20, 4000),
    # Lightweight — minimal chunks
    "ch02_macro":             (10, 3000),
    "ch03_exit":              (10, 3000),
    "ch12_peers":             (10, 3000),
    # Synthesis only — no chunks
    "ch13_recommendation":    (0, 0),
}

# ---------------------------------------------------------------------------
# Evidence pack filtering (D — Cost Governance)
# ---------------------------------------------------------------------------
# Sections every chapter receives (identity + core analysis — small).
_SHARED_PACK_SECTIONS: frozenset[str] = frozenset({
    "investor_identity",
    "deal_identity",
    "deal_overview",
    "terms_summary",
    "risk_flags",
    "citations",
    "curated_surfaces_meta",
})

# Additional sections per chapter (on top of shared).
_CHAPTER_EXTRA_SECTIONS: dict[str, frozenset[str]] = {
    "ch01_exec":              frozenset({"quant_profile", "policy_compliance", "sponsor_analysis",
                                         "macro_snapshot", "concentration_profile",
                                         "market_benchmarks", "market_benchmark_meta"}),
    "ch02_macro":             frozenset({"macro_snapshot"}),
    "ch03_exit":              frozenset({"macro_snapshot", "quant_profile"}),
    "ch04_sponsor":           frozenset({"sponsor_analysis"}),
    "ch05_legal":             frozenset(),
    "ch06_terms":             frozenset(),
    "ch07_capital":           frozenset({"quant_profile", "concentration_profile"}),
    "ch08_returns":           frozenset({"quant_profile", "market_benchmarks", "market_benchmark_meta"}),
    "ch09_downside":          frozenset({"quant_profile", "concentration_profile"}),
    "ch10_covenants":         frozenset({"policy_compliance"}),
    "ch11_risks":             frozenset({"policy_compliance", "concentration_profile"}),
    "ch12_peers":             frozenset({"quant_profile", "market_benchmarks", "market_benchmark_meta"}),
    "ch13_recommendation":    frozenset({"quant_profile", "policy_compliance", "sponsor_analysis",
                                         "concentration_profile"}),
    "ch14_governance_stress": frozenset({"policy_compliance", "sponsor_analysis",
                                         "concentration_profile"}),
}
