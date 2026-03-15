"""Wealth Management vertical engine — fund manager DD reports.

Built fresh (not migrated from an existing codebase).  Provides:
  - 7-chapter fund manager due diligence report
  - Quant analysis integration (CVaR, Sharpe, drawdown via quant_engine)
  - DD report generation loop

Public entry points:
  - ``FundAnalyzer`` — implements BaseAnalyzer for liquid_funds profile
  - ``DDReportEngine`` — orchestrates chapter generation
  - ``QuantAnalyzer`` — bridges quant_engine services
"""
