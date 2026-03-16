"""Wealth Management vertical engine — fund manager DD reports.

Built fresh (not migrated from an existing codebase).  Provides:
  - 8-chapter fund manager due diligence report with adversarial critic
  - Quant analysis integration (CVaR, Sharpe, drawdown via quant_engine)
  - DD report generation loop with confidence scoring

Public entry points:
  - ``FundAnalyzer`` — implements BaseAnalyzer for liquid_funds profile
  - ``DDReportEngine`` — orchestrates chapter generation (dd_report/)
  - ``QuantAnalyzer`` — bridges quant_engine services
"""

from pathlib import Path

from ai_engine.prompts.registry import get_prompt_registry

# Register wealth-specific prompt templates search path (fix #67).
# Without this, PromptRegistry only searches ai_engine/prompts/.
_prompts_dir = Path(__file__).parent / "prompts"
if _prompts_dir.is_dir():
    get_prompt_registry().add_search_path(_prompts_dir)
