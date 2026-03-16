"""Fact-Sheet PDF generation for wealth model portfolios.

Two formats: executive summary (1-2 pages) and institutional complete (4-6 pages).
All client-facing PDFs support bilingual generation (Portuguese and English).
"""

from vertical_engines.wealth.fact_sheet.fact_sheet_engine import FactSheetEngine
from vertical_engines.wealth.fact_sheet.models import FactSheetData

__all__ = ["FactSheetData", "FactSheetEngine"]
