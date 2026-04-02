"""Chart rendering for fact-sheet PDFs.

Renders matplotlib charts as in-memory PNG BytesIO buffers.
Uses Agg backend (no DISPLAY required).  Reuses Netz brand palette.
"""

from __future__ import annotations

import os as _os
from io import BytesIO
from typing import TYPE_CHECKING

_os.environ.setdefault("MPLBACKEND", "Agg")

if TYPE_CHECKING:
    from matplotlib.figure import Figure

    from vertical_engines.wealth.fact_sheet.i18n import Language
    from vertical_engines.wealth.fact_sheet.models import (
        AllocationBlock,
        NavPoint,
        RegimePoint,
    )

# ── Netz brand palette ──────────────────────────────────────────────────────
NETZ_NAVY = "#020F59"
NETZ_ORANGE = "#FF975A"
NETZ_GREY = "#E8EAF0"
NETZ_DARK = "#1A1A2E"
NETZ_WHITE = "#FCFDFD"
NETZ_GREEN = "#167832"
NETZ_RED = "#B41E1E"

# Chart dimensions matching existing chart_renderer.py
_CHART_WIDTH_IN = 6.3
_CHART_HEIGHT_IN = 3.2
_DPI = 150


def _fig_to_bytesio(fig: Figure) -> BytesIO:
    """Save matplotlib figure to in-memory PNG buffer."""
    import matplotlib.pyplot as plt

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight", facecolor=NETZ_WHITE)
    plt.close(fig)
    buf.seek(0)
    return buf


def render_nav_chart(
    nav_series: list[NavPoint],
    *,
    title: str = "NAV vs Benchmark",
    benchmark_label: str = "Benchmark",
    language: Language = "pt",
) -> BytesIO:
    """Line chart: portfolio NAV vs composite benchmark over time."""
    import matplotlib.pyplot as plt


    dates = [p.nav_date for p in nav_series]
    navs = [p.nav for p in nav_series]
    bench = [p.benchmark_nav for p in nav_series if p.benchmark_nav is not None]
    has_benchmark = len(bench) == len(nav_series)

    fig, ax = plt.subplots(figsize=(_CHART_WIDTH_IN, _CHART_HEIGHT_IN))
    fig.patch.set_facecolor(NETZ_WHITE)
    ax.set_facecolor(NETZ_WHITE)

    # Use rasterized for dense time series
    rasterized = len(dates) > 1000
    ax.plot(dates, navs, color=NETZ_NAVY, linewidth=1.5, label="Portfolio", rasterized=rasterized)  # type: ignore[arg-type]

    if has_benchmark:
        bench_navs: list[float | None] = [p.benchmark_nav for p in nav_series]
        ax.plot(dates, bench_navs, color=NETZ_ORANGE, linewidth=1.2,  # type: ignore[arg-type]
                label=benchmark_label, linestyle="--", rasterized=rasterized)
        ax.legend(fontsize=8, loc="upper left", frameon=False)

    ax.set_title(title, fontsize=10, color=NETZ_NAVY, fontweight="bold", pad=8)
    ax.tick_params(axis="both", labelsize=7, colors=NETZ_DARK)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(NETZ_GREY)
    ax.spines["bottom"].set_color(NETZ_GREY)
    ax.grid(axis="y", linestyle="--", linewidth=0.4, color=NETZ_GREY, alpha=0.7)

    # Format x-axis dates
    fig.autofmt_xdate(rotation=30, ha="right")

    fig.set_layout_engine("constrained")
    return _fig_to_bytesio(fig)


def render_allocation_pie(
    allocations: list[AllocationBlock],
    *,
    title: str = "Strategic Allocation",
) -> BytesIO:
    """Pie chart of allocation by block."""
    import matplotlib.pyplot as plt

    labels = [a.block_id.replace("_", " ").title() for a in allocations]
    weights = [a.weight * 100 for a in allocations]

    # Color palette — cycle through brand-adjacent colors
    palette = [NETZ_NAVY, NETZ_ORANGE, NETZ_GREEN, "#4A90D9", "#8B5CF6",
               "#EC4899", "#14B8A6", "#F59E0B", "#6366F1", "#EF4444"]
    colors = [palette[i % len(palette)] for i in range(len(allocations))]

    fig, ax = plt.subplots(figsize=(4.5, 3.5))
    fig.patch.set_facecolor(NETZ_WHITE)

    wedges, texts, autotexts = ax.pie(  # type: ignore[misc]
        weights, labels=labels, colors=colors, autopct="%1.1f%%",
        startangle=90, textprops={"fontsize": 7, "color": NETZ_DARK},
        pctdistance=0.75,
    )
    for t in autotexts:
        t.set_fontsize(7)
        t.set_fontweight("bold")

    ax.set_title(title, fontsize=10, color=NETZ_NAVY, fontweight="bold", pad=8)

    fig.set_layout_engine("constrained")
    return _fig_to_bytesio(fig)


def render_regime_overlay(
    nav_series: list[NavPoint],
    regimes: list[RegimePoint],
    *,
    title: str = "Economic Regimes",
) -> BytesIO:
    """NAV line chart with regime background shading."""
    import matplotlib.pyplot as plt
    from matplotlib.dates import date2num

    dates = [p.nav_date for p in nav_series]
    navs = [p.nav for p in nav_series]

    regime_colors = {
        "expansion": "#E8F5E9",   # light green
        "contraction": "#FFF3E0", # light orange
        "crisis": "#FFEBEE",      # light red
    }

    fig, ax = plt.subplots(figsize=(_CHART_WIDTH_IN, _CHART_HEIGHT_IN))
    fig.patch.set_facecolor(NETZ_WHITE)
    ax.set_facecolor(NETZ_WHITE)

    # Draw regime bands
    if regimes:
        sorted_regimes = sorted(regimes, key=lambda r: r.regime_date)
        for i, rp in enumerate(sorted_regimes):
            start = date2num(rp.regime_date)  # type: ignore[no-untyped-call]
            end = date2num(sorted_regimes[i + 1].regime_date) if i + 1 < len(sorted_regimes) else date2num(dates[-1])  # type: ignore[no-untyped-call]
            color = regime_colors.get(rp.regime, NETZ_GREY)
            ax.axvspan(start, end, facecolor=color, alpha=0.4)

    rasterized = len(dates) > 1000
    ax.plot(dates, navs, color=NETZ_NAVY, linewidth=1.5, rasterized=rasterized)  # type: ignore[arg-type]

    ax.set_title(title, fontsize=10, color=NETZ_NAVY, fontweight="bold", pad=8)
    ax.tick_params(axis="both", labelsize=7, colors=NETZ_DARK)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(NETZ_GREY)
    ax.spines["bottom"].set_color(NETZ_GREY)

    fig.autofmt_xdate(rotation=30, ha="right")
    fig.set_layout_engine("constrained")
    return _fig_to_bytesio(fig)
