"""Wealth Management vertical engine — fund manager DD reports + asset universe.

Built fresh (not migrated from an existing codebase).  Provides:
  - 8-chapter fund manager due diligence report with adversarial critic
  - Quant analysis integration (CVaR, Sharpe, drawdown via quant_engine)
  - DD report generation loop with confidence scoring
  - Asset universe fund approval workflow with governance controls

Public entry points:
  - ``FundAnalyzer`` — implements BaseAnalyzer for liquid_funds profile
  - ``DDReportEngine`` — orchestrates chapter generation (dd_report/)
  - ``QuantAnalyzer`` — bridges quant_engine services
  - ``UniverseService`` — manages approved fund universe (asset_universe/)
"""

from pathlib import Path

from ai_engine.prompts.registry import get_prompt_registry

# Register wealth-specific prompt templates search path (fix #67).
# Without this, PromptRegistry only searches ai_engine/prompts/.
_prompts_dir = Path(__file__).parent / "prompts"
if _prompts_dir.is_dir():
    get_prompt_registry().add_search_path(_prompts_dir)
