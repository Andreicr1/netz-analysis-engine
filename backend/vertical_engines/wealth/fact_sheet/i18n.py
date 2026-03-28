"""Bilingual label dictionaries and formatting helpers for fact-sheet PDFs.

All static PDF labels (section headers, table headers, footers, disclaimers)
are rendered via ``LABELS[language]`` — no hardcoded strings in renderers.

Date and number formatting uses manual helpers (no system locale dependency).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

Language = Literal["pt", "en"]

# ── Label dictionaries ──────────────────────────────────────────────────────

LABELS: dict[str, dict[str, str]] = {
    "pt": {
        # Cover
        "report_title_executive": "Resumo Executivo",
        "report_title_institutional": "Relatório Institucional",
        "confidential": "CONFIDENCIAL — USO INTERNO",
        "as_of": "Data-base",
        "profile": "Perfil",
        "portfolio": "Portfólio Modelo",
        # Returns table
        "returns": "Retornos",
        "mtd": "Mês",
        "qtd": "Trimestre",
        "ytd": "Ano",
        "1y": "1 Ano",
        "3y": "3 Anos",
        "since_inception": "Desde Início",
        "backtest_note": "* Período de backtest (simulado)",
        # Allocation
        "allocation": "Alocação por Bloco",
        # Holdings
        "top_holdings": "Maiores Posições",
        "fund_name": "Fundo",
        "block": "Bloco",
        "weight": "Peso",
        # Risk metrics
        "risk_metrics": "Métricas de Risco",
        "annualized_vol": "Volatilidade Anualizada",
        "sharpe": "Índice de Sharpe",
        "max_drawdown": "Drawdown Máximo",
        "cvar_95": "CVaR 95%",
        # Charts
        "nav_chart_title": "NAV vs Benchmark",
        "allocation_chart_title": "Alocação Estratégica",
        "regime_chart_title": "Regimes Econômicos",
        # Attribution
        "attribution": "Análise de Atribuição (Brinson)",
        "block_name": "Bloco",
        "allocation_effect": "Efeito Alocação",
        "selection_effect": "Efeito Seleção",
        "interaction_effect": "Efeito Interação",
        "total_effect": "Efeito Total",
        # Stress
        "stress_scenarios": "Cenários de Estresse",
        "scenario": "Cenário",
        "period": "Período",
        "portfolio_return": "Retorno Portfólio",
        # Rebalance
        "rebalance_history": "Histórico de Rebalanceamento",
        "rebalance_date": "Data",
        "rebalance_reason": "Motivo",
        # Fee Drag
        "fee_drag_analysis": "Análise de Arrasto de Taxas",
        "fd_instruments": "Instrumentos",
        "fd_gross_return": "Retorno Bruto",
        "fd_net_return": "Retorno Líquido",
        "fd_drag_ratio": "Arrasto (%)",
        "fd_inefficient": "Ineficientes",
        # Fee comparison (per-fund)
        "fee_comparison": "Comparação de Taxas por Fundo",
        "fc_fund": "Fundo",
        "fc_mgmt_fee": "Taxa Gestão",
        "fc_perf_fee": "Taxa Perf.",
        "fc_other_fee": "Outras",
        "fc_total_fee": "Total",
        "fc_drag": "Arrasto",
        "fc_status": "Status",
        "fc_efficient": "Eficiente",
        "fc_inefficient": "Ineficiente",
        # ESG
        "esg_section": "ESG",
        "esg_placeholder": "Dados ESG serão incorporados quando disponíveis.",
        # Disclaimer
        "disclaimer": (
            "Este documento é de uso exclusivo do destinatário e contém informações "
            "confidenciais. Rentabilidade passada não é garantia de resultados futuros. "
            "Os dados de backtest são simulados e podem não refletir condições reais de mercado."
        ),
        # Commentary
        "manager_commentary": "Comentário do Gestor",
        # DD Report
        "dd_report_title": "Relatório de Due Diligence",
        "dd_cover_subtitle": "Análise Institucional de Fundo",
        "dd_disclaimer": (
            "Este relatório foi gerado por inteligência artificial e validado pelo "
            "motor de crítica adversarial da Netz. As análises não constituem "
            "recomendação de investimento."
        ),
        # Content Production
        "investment_outlook_title": "Perspectiva de Investimento",
        "flash_report_title": "Relatório Flash de Mercado",
        "manager_spotlight_title": "Destaque do Gestor",
        "content_disclaimer": (
            "Este conteúdo foi gerado por inteligência artificial e requer "
            "aprovação do comitê de investimento antes de distribuição."
        ),
        "global_macro_summary": "Resumo Macro Global",
        "regional_outlook": "Perspectiva Regional",
        "asset_class_views": "Visão por Classe de Ativos",
        "portfolio_positioning": "Posicionamento do Portfólio",
        "key_risks": "Riscos Principais",
        "market_event": "Evento de Mercado",
        "market_impact": "Impacto no Mercado",
        "recommended_actions": "Ações Recomendadas",
        "fund_overview": "Visão Geral do Fundo",
        "quant_analysis": "Análise Quantitativa",
        "peer_comparison": "Comparação com Pares",
    },
    "en": {
        # Cover
        "report_title_executive": "Executive Summary",
        "report_title_institutional": "Institutional Report",
        "confidential": "CONFIDENTIAL — INTERNAL USE ONLY",
        "as_of": "As of",
        "profile": "Profile",
        "portfolio": "Model Portfolio",
        # Returns table
        "returns": "Returns",
        "mtd": "MTD",
        "qtd": "QTD",
        "ytd": "YTD",
        "1y": "1Y",
        "3y": "3Y",
        "since_inception": "Since Inception",
        "backtest_note": "* Backtest period (simulated)",
        # Allocation
        "allocation": "Allocation by Block",
        # Holdings
        "top_holdings": "Top Holdings",
        "fund_name": "Fund",
        "block": "Block",
        "weight": "Weight",
        # Risk metrics
        "risk_metrics": "Risk Metrics",
        "annualized_vol": "Annualized Volatility",
        "sharpe": "Sharpe Ratio",
        "max_drawdown": "Maximum Drawdown",
        "cvar_95": "CVaR 95%",
        # Charts
        "nav_chart_title": "NAV vs Benchmark",
        "allocation_chart_title": "Strategic Allocation",
        "regime_chart_title": "Economic Regimes",
        # Attribution
        "attribution": "Attribution Analysis (Brinson)",
        "block_name": "Block",
        "allocation_effect": "Allocation Effect",
        "selection_effect": "Selection Effect",
        "interaction_effect": "Interaction Effect",
        "total_effect": "Total Effect",
        # Stress
        "stress_scenarios": "Stress Scenarios",
        "scenario": "Scenario",
        "period": "Period",
        "portfolio_return": "Portfolio Return",
        # Rebalance
        "rebalance_history": "Rebalance History",
        "rebalance_date": "Date",
        "rebalance_reason": "Reason",
        # Fee Drag
        "fee_drag_analysis": "Fee Drag Analysis",
        "fd_instruments": "Instruments",
        "fd_gross_return": "Gross Return",
        "fd_net_return": "Net Return",
        "fd_drag_ratio": "Drag (%)",
        "fd_inefficient": "Inefficient",
        # Fee comparison (per-fund)
        "fee_comparison": "Fee Comparison by Fund",
        "fc_fund": "Fund",
        "fc_mgmt_fee": "Mgmt Fee",
        "fc_perf_fee": "Perf Fee",
        "fc_other_fee": "Other",
        "fc_total_fee": "Total",
        "fc_drag": "Drag",
        "fc_status": "Status",
        "fc_efficient": "Efficient",
        "fc_inefficient": "Inefficient",
        # ESG
        "esg_section": "ESG",
        "esg_placeholder": "ESG data will be incorporated when available.",
        # Disclaimer
        "disclaimer": (
            "This document is for the exclusive use of the intended recipient and "
            "contains confidential information. Past performance is not a guarantee "
            "of future results. Backtest data is simulated and may not reflect "
            "actual market conditions."
        ),
        # Commentary
        "manager_commentary": "Manager Commentary",
        # DD Report
        "dd_report_title": "Due Diligence Report",
        "dd_cover_subtitle": "Institutional Fund Analysis",
        "dd_disclaimer": (
            "This report was generated by artificial intelligence and validated by "
            "Netz's adversarial critic engine. The analyses do not constitute "
            "investment recommendations."
        ),
        # Content Production
        "investment_outlook_title": "Investment Outlook",
        "flash_report_title": "Market Flash Report",
        "manager_spotlight_title": "Manager Spotlight",
        "content_disclaimer": (
            "This content was generated by artificial intelligence and requires "
            "investment committee approval before distribution."
        ),
        "global_macro_summary": "Global Macro Summary",
        "regional_outlook": "Regional Outlook",
        "asset_class_views": "Asset Class Views",
        "portfolio_positioning": "Portfolio Positioning",
        "key_risks": "Key Risks",
        "market_event": "Market Event",
        "market_impact": "Market Impact",
        "recommended_actions": "Recommended Actions",
        "fund_overview": "Fund Overview",
        "quant_analysis": "Quantitative Analysis",
        "peer_comparison": "Peer Comparison",
    },
}


# ── Formatting helpers (no system locale dependency) ────────────────────────


def format_date(d: date, language: Language = "pt") -> str:
    """Format date per language convention.

    ``"pt"`` → ``dd/mm/yyyy``
    ``"en"`` → ``mm/dd/yyyy``
    """
    if language == "pt":
        return d.strftime("%d/%m/%Y")
    return d.strftime("%m/%d/%Y")


def format_number(value: float, decimals: int = 2, language: Language = "pt") -> str:
    """Format number with locale-appropriate separators.

    ``"pt"`` → ``1.234,56`` (dot thousands, comma decimal)
    ``"en"`` → ``1,234.56`` (comma thousands, dot decimal)
    """
    formatted = f"{value:,.{decimals}f}"
    if language == "pt":
        # Swap separators: comma→@, dot→comma, @→dot
        formatted = formatted.replace(",", "@").replace(".", ",").replace("@", ".")
    return formatted


def format_pct(value: float, decimals: int = 2, language: Language = "pt") -> str:
    """Format percentage value (already in percent, e.g. 12.5 for 12.5%)."""
    return f"{format_number(value, decimals, language)}%"


def format_bps(value: float, language: Language = "pt") -> str:
    """Format basis points."""
    return f"{format_number(value, 0, language)} bps"
