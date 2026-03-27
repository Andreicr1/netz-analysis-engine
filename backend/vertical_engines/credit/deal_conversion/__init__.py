"""Deal Conversion Engine — pipeline → portfolio deal transition.

Public API:
    convert_pipeline_to_portfolio()  — convert an approved pipeline deal
    ConversionResult                 — frozen result dataclass

Error contract: raises-on-failure (transactional engine).
Raises ValueError on validation gates (deal not found, already converted,
intelligence not READY, empty research_output).
"""
from vertical_engines.credit.deal_conversion.models import ConversionResult
from vertical_engines.credit.deal_conversion.service import convert_pipeline_to_portfolio

__all__ = [
    "ConversionResult",
    "convert_pipeline_to_portfolio",
]
