"""Frozen dataclasses for Monthly Client Report."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True, slots=True)
class MonthlyReturnRow:
    """Single month return data for trailing-12 table."""

    period_label: str  # "Apr '25", "May", ..., "Mar"
    portfolio_return: float
    benchmark_return: float
    active_bps: float
    is_current: bool = False  # Highlights the most recent month


@dataclass(frozen=True, slots=True)
class PortfolioActivity:
    """Trade activity item for the Portfolio Activity section."""

    ticker: str
    action: str  # "Added" | "Trimmed" | "Removed"
    narrative: str  # Why the change was made


@dataclass(frozen=True, slots=True)
class WatchItem:
    """Watchpoint item with urgency level."""

    text: str
    urgency: str  # "monitor" | "track"


@dataclass(frozen=True, slots=True)
class HoldingRow:
    """Single fund holding row for holdings table."""

    fund_name: str
    ticker: str
    strategy: str
    weight: float
    one_year_return: float | None
    expense_ratio: float | None
    status: str  # "Core" | "New" | "Reduced"


@dataclass(frozen=True, slots=True)
class AllocationBar:
    """Allocation block for bar chart rendering."""

    label: str
    weight: float
    color: str


@dataclass(frozen=True, slots=True)
class MonthlyReportData:
    """Complete data bundle for Monthly Client Report rendering."""

    portfolio_id: str
    portfolio_name: str
    profile: str
    report_month: str  # "March 2026"
    as_of: date
    regime: str

    # Cover performance strip
    month_return: float
    ytd_return: float
    inception_return: float
    month_bm_return: float
    ytd_bm_return: float
    inception_bm_return: float

    # Narrative sections (LLM-generated)
    manager_note: str
    macro_commentary: str
    portfolio_activity_intro: str
    forward_positioning: str

    # Structured sections
    portfolio_activities: list[PortfolioActivity] = field(default_factory=list)
    watch_items: list[WatchItem] = field(default_factory=list)
    allocations: list[AllocationBar] = field(default_factory=list)
    core_holdings: list[HoldingRow] = field(default_factory=list)

    # Performance page
    nav_series: list = field(default_factory=list)  # list[NavPoint] from svg_charts
    monthly_returns: list[MonthlyReturnRow] = field(default_factory=list)
    trailing_periods: dict = field(default_factory=dict)  # {"1m": {...}, "3m": {...}, ...}

    # Attribution page
    attribution_narrative: str = ""
    attribution_rows: list = field(default_factory=list)  # list[dict]
    attribution_total: dict = field(default_factory=dict)

    # Risk page
    risk_narrative: str = ""
    volatility: float | None = None
    sharpe: float | None = None
    max_drawdown: float | None = None
    cvar_95: float | None = None
    drawdown_series: list = field(default_factory=list)  # list[DrawdownPoint]
    stress_scenarios: list = field(default_factory=list)

    # Holdings page
    all_holdings: list[HoldingRow] = field(default_factory=list)
    watchpoints: list[WatchItem] = field(default_factory=list)

    # Sidebar
    snapshot_kv: dict = field(default_factory=dict)  # {"Instruments": "8", ...}

    # Metadata
    is_backtest: bool = True
    language: str = "en"
