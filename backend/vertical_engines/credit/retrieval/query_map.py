"""Chapter-specialized query expansion for IC-Grade retrieval.

Builds per-chapter query sets that anchor on the deal name. Generic
global queries are prohibited — every query is chapter-specialized.
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger()


def build_chapter_query_map(deal_name: str) -> dict[str, list[str]]:
    """Build chapter-specialized query expansion per IC-Grade standard.

    Each chapter receives its own query set. Generic global queries are
    prohibited. Every query includes the deal name for scope anchoring.

    Returns
    -------
    dict[str, list[str]]
        Mapping from chapter_key → list of specialized retrieval queries.

    """
    dn = deal_name  # shorthand

    return {
        "ch01_exec": [
            f"{dn} investment opportunity fund structure overview executive summary",
            f"{dn} fund profile strategy asset class target return",
            f"{dn} key investment highlights risk reward summary",
            "fund constitution governance board resolution investment policy overview",
            f"{dn} side letter agreement fund vehicle capital allocation structure",
        ],
        "ch02_macro": [
            f"{dn} market context private credit macro environment",
            f"{dn} industry sector competitive landscape market positioning",
            f"{dn} interest rate environment credit cycle outlook",
            "CIMA regulatory framework Cayman Islands mutual funds obligations reporting",
        ],
        "ch03_exit": [
            f"{dn} exit environment liquidity redemption secondary market",
            f"{dn} macro regime stress scenario economic downturn",
            f"{dn} interest rate sensitivity duration portfolio maturity",
        ],
        "ch04_sponsor": [
            f"{dn} sponsor management team track record key person biography",
            f"{dn} organizational chart governance board committee oversight",
            f"{dn} sponsor AUM assets under management investment history",
            "service provider administrator custodian auditor counterparty arrangement",
            "fund constitution board composition quorum amendment delegated authority",
            "CIMA regulatory responsible party compliance officer obligations",
        ],
        "ch05_legal": [
            f"{dn} LPA subscription agreement side letter legal terms",
            f"{dn} fund constitution prospectus offering memorandum",
            f"{dn} jurisdiction enforcement litigation regulatory filings",
            "offering memorandum share class amendment threshold quorum reserved matters",
            "board approved liberality policy override concentration exception waiver",
            "CIMA filing obligations AML KYC compliance penalties non-compliance",
        ],
        "ch06_terms": [
            f"{dn} investment terms fees management performance carried interest",
            f"{dn} covenants restrictions concentration limits leverage cap",
            f"{dn} waterfall distributions hurdle rate clawback",
            "offering memorandum fee schedule hurdle rate lock-up redemption terms",
            "service provider fee arrangement administrator custodian auditor costs",
        ],
        "ch07_capital": [
            f"{dn} capital structure leverage borrowing facility senior subordinated",
            f"{dn} financial statements balance sheet NAV AUM",
            f"{dn} capital raising presentation investor commitments",
            "fund constitution capital call leverage limit borrowing policy",
        ],
        "ch08_returns": [
            f"{dn} financial statements returns NAV performance AUM audited",
            f"{dn} historical returns net IRR MOIC yield track record",
            f"{dn} cash flow distributions income revenue EBITDA DSCR",
            "offering memorandum hurdle rate preferred return waterfall carried interest performance allocation",
        ],
        "ch09_downside": [
            f"{dn} risk assessment credit risk concentration default covenant",
            f"{dn} downside scenario stress test loss given default",
            f"{dn} worst case scenario portfolio deterioration recovery",
            "CIMA regulatory enforcement licence suspension wind-down penalty",
            "service provider termination resignation transition contingency",
            "offering memorandum lock-up redemption gate suspension side pocket",
        ],
        "ch10_covenants": [
            f"{dn} covenant compliance monitoring breach waiver amendment",
            f"{dn} credit policy lending standards limits covenants underwriting",
            f"{dn} financial covenants DSCR leverage ratio interest coverage",
            "investment policy concentration limit single-name sector geography board approved exception",
            "CIMA regulatory obligation audit delivery NAV reporting filing deadline",
        ],
        "ch11_risks": [
            f"{dn} risk assessment operational risk key person dependency",
            f"{dn} compliance AML KYC regulatory policies procedures anti-money",
            f"{dn} IT policy disaster recovery business continuity cybersecurity",
            "CIMA filing deadline penalty regulatory change obligation revision",
            "service provider termination liability cap jurisdiction mismatch concentration",
            "fund constitution governance quorum amendment conflict of interest related party",
        ],
        "ch12_peers": [
            f"{dn} peer comparison benchmark private credit market",
            f"{dn} competitive analysis similar funds strategy positioning",
            f"{dn} due diligence questionnaire DDQ ANBIMA operational risk",
        ],
        "ch13_recommendation": [
            f"{dn} employee handbook HR policies code of ethics professional conduct",
            f"{dn} code of ethics professional conduct business integrity",
        ],
        "ch14_governance_stress": [
            f"{dn} suspension redemption gate NAV determination valuation sole discretion board",
            f"{dn} investment manager removal cause without cause notice period transition successor",
            f"{dn} board directors composition removal appointment regulatory override adverse event",
            f"{dn} side letter enforceability conflict MFN priority queue adverse event investor rights",
            f"{dn} credit policy concentration limits borrower breach disclosure obligation single name",
            "CIMA intervention powers director substitution regulatory enforcement fund wind-down",
            f"{dn} management fee performance fee suspension NAV decline reset high water mark",
            f"{dn} liquidity gate threshold pro-rata mechanics suspension trigger condition cash reserve",
            f"{dn} financial statements NAV leverage yield default stress scenario impairment recovery",
            f"{dn} auditor appointment independence related party transactions conflict of interest",
        ],
    }
