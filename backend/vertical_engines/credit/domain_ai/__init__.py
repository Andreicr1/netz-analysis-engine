"""Domain AI Engine — domain-aware AI analysis dispatcher.

Public API:
    run_deal_ai_analysis()  — unified entrypoint (PIPELINE or PORTFOLIO mode)

Cross-layer imports: service.py imports from ai_engine/ and app/domains/credit/.
These are inherited dependencies — documented for Wave 2 cleanup.
"""
from vertical_engines.credit.domain_ai.service import run_deal_ai_analysis

__all__ = [
    "run_deal_ai_analysis",
]
