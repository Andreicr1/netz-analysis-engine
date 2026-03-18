"""Lightweight intent router: given a question and optional deal_folder,
returns the list of knowledge domains that should be queried.

Uses keyword heuristics — no LLM call to keep latency low.
If deal_folder is provided, PIPELINE is always included.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Keyword lists per domain (all lowercase).
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "PIPELINE": [
        "deal", "fund", "manager", "sponsor", "commitment", "ticket",
        "lp", "irr", "return", "lock-up", "lockup", "nav", "redemption",
        "lpa", "term sheet", "strategy", "portfolio", "chicago atlantic",
        "garrington", "blue owl", "hays mews", "pipeline", "investimento",
        "investimentos", "cypress", "posição", "posições", "carteira",
        "alocação", "ltv", "yield", "rendimento", "risco",
    ],
    "REGULATORY": [
        "cima", "filing", "regulatory", "regulation", "compliance",
        "aml", "kyc", "fatca", "crs", "mutual funds act", "annual report",
        "audit", "deadline", "penalty", "registration", "license",
        "regulatório", "regulação", "conformidade", "multa", "prazo",
    ],
    "CONSTITUTION": [
        "constitution", "lpa", "ima", "investment management agreement",
        "offering memorandum", "subscription", "articles", "memorandum",
        "board", "director", "governance", "shareholder", "amendment",
        "constituição", "estatuto", "governança", "conselho", "cotista",
    ],
    "SERVICE_PROVIDER": [
        "administrator", "zedra", "auditor", "legal counsel", "prime broker",
        "custodian", "service provider", "engagement letter", "fee",
        "termination", "liability",
        "administrador", "custodiante", "prestador", "contrato",
    ],
}

# Canonical ordering: PIPELINE first, then regulatory domains.
_DOMAIN_ORDER = ["PIPELINE", "REGULATORY", "CONSTITUTION", "SERVICE_PROVIDER"]

ALL_DOMAINS: list[str] = list(_DOMAIN_ORDER)


class IntentRouter:
    """Stateless keyword-based intent router."""

    @staticmethod
    def detect_domains(question: str, deal_folder: str | None = None) -> list[str]:
        """Return the list of knowledge domains relevant to *question*.

        Rules:
        - If *deal_folder* is provided, PIPELINE is always included.
        - Each domain's keyword list is checked against the lowercased question.
        - If no domain is detected, all domains are returned (full fan-out).
        - Result is deduplicated and ordered: PIPELINE first.
        """
        q = question.lower()
        detected: set[str] = set()

        if deal_folder is not None:
            detected.add("PIPELINE")

        for domain, keywords in DOMAIN_KEYWORDS.items():
            for kw in keywords:
                if kw in q:
                    detected.add(domain)
                    break  # one match per domain is enough

        # Fallback: if nothing matched, query everything.
        if not detected:
            logger.debug(
                "INTENT_ROUTER no keywords matched — falling back to all domains",
            )
            return list(ALL_DOMAINS)

        # Preserve canonical order.
        result = [d for d in _DOMAIN_ORDER if d in detected]

        logger.info(
            "INTENT_ROUTER question=%r deal_folder=%s domains=%s",
            question[:80],
            deal_folder,
            result,
        )
        return result
