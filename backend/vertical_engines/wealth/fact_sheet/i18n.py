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
        "allocation": "Alocação Estratégica",
        # Holdings
        "top_holdings": "Maiores Posições",
        "fund_name": "Fundo",
        "strategy": "Estratégia",
        "weight": "Peso",
        # Risk metrics
        "risk_metrics": "Métricas de Risco",
        "annualized_return": "Retorno Anualizado",
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
        "asset_class": "Classe de Ativos",
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
        # Fee Analysis
        "fee_drag_analysis": "Análise de Custos",
        "fd_instruments": "Instrumentos",
        "fd_gross_return": "Retorno Bruto",
        "fd_net_return": "Retorno Líquido",
        # Fee comparison (per-fund) — client-facing columns only
        "fee_comparison": "Estrutura de Taxas por Fundo",
        "fc_fund": "Fundo",
        "fc_mgmt_fee": "Taxa Gestão",
        "fc_perf_fee": "Taxa Perf.",
        "fc_other_fee": "Outras",
        "fc_total_fee": "Total",
        # Deprecated (kept for ReportLab backward compat)
        "fd_drag_ratio": "Arrasto (%)",
        "fd_inefficient": "Ineficientes",
        "fc_drag": "Arrasto",
        "fc_status": "Status",
        "fc_efficient": "Eficiente",
        "fc_inefficient": "Ineficiente",
        # Monthly returns
        "monthly_returns": "Retornos Mensais Desde o Início",
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
            "Este relatório é produzido pela plataforma InvestIntell. As análises são "
            "derivadas de registros regulatórios oficiais (SEC EDGAR, Formulário ADV, "
            "N-PORT, 13F) e modelos quantitativos proprietários. Não constitui "
            "recomendação de investimento."
        ),
        "dd_prepared_by": "Prepared by InvestIntell Research Platform",
        # Content Production
        "investment_outlook_title": "Perspectiva de Investimento",
        "flash_report_title": "Relatório Flash de Mercado",
        "manager_spotlight_title": "Destaque do Gestor",
        "content_disclaimer": (
            "Este relatório é produzido pela plataforma InvestIntell. Todas as análises, "
            "métricas de risco e dados de performance são derivados de fontes regulatórias "
            "oficiais e modelos quantitativos proprietários. O conteúdo narrativo foi "
            "revisado pela equipe de gestão antes da distribuição. Este documento não "
            "constitui recomendação de investimento. Rentabilidade passada não é garantia "
            "de resultados futuros."
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
        "external_disclaimer": "",
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
        "allocation": "Strategic Allocation",
        # Holdings
        "top_holdings": "Top Holdings",
        "fund_name": "Fund",
        "strategy": "Strategy",
        "weight": "Weight",
        # Risk metrics
        "risk_metrics": "Risk Metrics",
        "annualized_return": "Annualized Return",
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
        "asset_class": "Asset Class",
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
        # Fee Analysis
        "fee_drag_analysis": "Cost Analysis",
        "fd_instruments": "Instruments",
        "fd_gross_return": "Gross Return",
        "fd_net_return": "Net Return",
        # Fee comparison (per-fund) — client-facing columns only
        "fee_comparison": "Fee Structure by Fund",
        "fc_fund": "Fund",
        "fc_mgmt_fee": "Mgmt Fee",
        "fc_perf_fee": "Perf Fee",
        "fc_other_fee": "Other",
        "fc_total_fee": "Total",
        # Deprecated (kept for ReportLab backward compat)
        "fd_drag_ratio": "Drag (%)",
        "fd_inefficient": "Inefficient",
        "fc_drag": "Drag",
        "fc_status": "Status",
        "fc_efficient": "Efficient",
        "fc_inefficient": "Inefficient",
        # Monthly returns
        "monthly_returns": "Monthly Returns Since Inception",
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
            "This report is produced by the InvestIntell research platform. All analyses "
            "are derived from official regulatory filings (SEC EDGAR Form ADV, N-PORT, 13F) "
            "and proprietary quantitative models. This does not constitute investment advice."
        ),
        "dd_prepared_by": "Prepared by InvestIntell Research Platform",
        # Content Production
        "investment_outlook_title": "Investment Outlook",
        "flash_report_title": "Market Flash Report",
        "manager_spotlight_title": "Manager Spotlight",
        "content_disclaimer": (
            "This report is produced by the InvestIntell research platform. All analytics, "
            "risk metrics, and performance data are derived from official regulatory filings "
            "and proprietary quantitative models. Narrative content has been reviewed by the "
            "investment team prior to distribution. This document does not constitute "
            "investment advice. Past performance is not indicative of future results."
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
        "external_disclaimer": "",
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


# ── Strategy / block ID formatting ────────────────────────────────────────

_UPPER_WORDS = frozenset({"us", "em", "uk", "eu", "esg", "etf", "reit", "bdc"})


def fmt_strategy(raw: str) -> str:
    """Format a snake_case block_id into institutional Title Case.

    ``"us_equity"`` → ``"US Equity"``
    ``"private_credit"`` → ``"Private Credit"``
    ``"fixed_income_em"`` → ``"Fixed Income EM"``
    """
    parts = raw.split("_")
    return " ".join(
        p.upper() if p.lower() in _UPPER_WORDS else p.capitalize()
        for p in parts
    )


# ── Month abbreviations for returns matrix ────────────────────────────────

MONTHS_SHORT: dict[str, list[str]] = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "pt": ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
           "Jul", "Ago", "Set", "Out", "Nov", "Dez"],
}
