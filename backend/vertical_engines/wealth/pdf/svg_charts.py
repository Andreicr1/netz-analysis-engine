"""Pure-Python SVG chart builders for Netz PDF reports.

All functions return an SVG string ready for inline embedding in HTML.
No external dependencies — computed coordinates only.

Design: Institutional-grade area charts with regime overlay bands,
translucent gradient fills, and Tufte-inspired minimal gridlines.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence


@dataclass
class NavPoint:
    nav_date: date
    portfolio_nav: float
    benchmark_nav: float | None = None


@dataclass
class DrawdownPoint:
    dd_date: date
    drawdown: float  # negative float, e.g. -0.0845


@dataclass
class RegimeSpan:
    """A contiguous regime period for background shading."""

    start_idx: int
    end_idx: int
    regime: str  # "expansion", "contraction", "crisis", "risk_off"


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

_PORTFOLIO_COLOR = "#0A192F"  # deep navy
_PORTFOLIO_FILL = "#0A192F"
_BENCHMARK_COLOR = "#B48608"  # copper/gold accent
_GRID_COLOR = "#E2E8F0"
_LABEL_COLOR = "#64748B"  # slate-500
_AXIS_COLOR = "#94A3B8"  # slate-400

_REGIME_FILLS: dict[str, str] = {
    "expansion": "rgba(15, 23, 42, 0.00)",  # invisible — normal state
    "contraction": "rgba(180, 134, 8, 0.08)",  # faint copper wash
    "crisis": "rgba(139, 0, 0, 0.10)",  # faint burgundy wash
    "risk_off": "rgba(180, 134, 8, 0.06)",  # very faint copper
}


# ---------------------------------------------------------------------------
# Performance area chart
# ---------------------------------------------------------------------------


def performance_line_chart(
    points: Sequence[NavPoint],
    *,
    width: int = 580,
    height: int = 180,
    portfolio_color: str = _PORTFOLIO_COLOR,
    benchmark_color: str = _BENCHMARK_COLOR,
    regimes: Sequence[RegimeSpan] | None = None,
) -> str:
    """Cumulative performance area chart (portfolio vs benchmark).

    Portfolio rendered as solid line with translucent gradient fill below.
    Benchmark rendered as fine dashed line with copper/gold accent.
    Optional regime bands painted as very faint vertical rectangles.

    Returns inline SVG string.
    """
    if not points:
        return f'<svg width="{width}" height="{height}"></svg>'

    pad_l, pad_r, pad_t, pad_b = 50, 62, 18, 30
    w = width - pad_l - pad_r
    h = height - pad_t - pad_b

    all_vals = [p.portfolio_nav for p in points]
    if any(p.benchmark_nav is not None for p in points):
        all_vals += [p.benchmark_nav for p in points if p.benchmark_nav is not None]

    min_v = min(all_vals)
    max_v = max(all_vals)
    rng = max_v - min_v or 0.01
    # Add 5% padding to Y range for breathing room
    min_v -= rng * 0.05
    max_v += rng * 0.05
    rng = max_v - min_v

    n = len(points)

    def x(i: int) -> float:
        return pad_l + (i / max(n - 1, 1)) * w

    def y(v: float) -> float:
        return pad_t + h - ((v - min_v) / rng) * h

    chart_id = f"perf_{id(points) % 10000}"
    parts: list[str] = []

    # --- Defs: gradient for area fill ---
    parts.append(
        f'<defs>'
        f'<linearGradient id="areaGrad_{chart_id}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{portfolio_color}" stop-opacity="0.18"/>'
        f'<stop offset="100%" stop-color="{portfolio_color}" stop-opacity="0.02"/>'
        f'</linearGradient>'
        f'</defs>'
    )

    # --- Regime bands (background Z) ---
    if regimes:
        for span in regimes:
            fill = _REGIME_FILLS.get(span.regime, "rgba(0,0,0,0)")
            if span.regime == "expansion":
                continue  # don't paint normal periods
            rx1 = x(span.start_idx)
            rx2 = x(min(span.end_idx, n - 1))
            parts.append(
                f'<rect x="{rx1:.1f}" y="{pad_t}" width="{rx2 - rx1:.1f}" '
                f'height="{h}" fill="{fill}"/>'
            )

    # --- Y-axis gridlines (4 ticks, Tufte: light, no vertical grid) ---
    num_ticks = 4
    for i in range(num_ticks + 1):
        t = min_v + (rng * i / num_ticks)
        yy = y(t)
        pct = (t - 1.0) * 100  # rebased to 1.0
        label = f"{pct:+.1f}%"
        parts.append(
            f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{width - pad_r}" y2="{yy:.1f}" '
            f'stroke="{_GRID_COLOR}" stroke-width="0.5"/>'
        )
        parts.append(
            f'<text x="{pad_l - 6}" y="{yy + 3:.1f}" text-anchor="end" '
            f'font-family="Inter, sans-serif" font-size="8" '
            f'fill="{_AXIS_COLOR}" font-variant-numeric="tabular-nums">{label}</text>'
        )

    # --- X-axis labels (first, middle, last) ---
    mid_idx = n // 2
    for idx, anchor in [(0, "start"), (mid_idx, "middle"), (n - 1, "end")]:
        parts.append(
            f'<text x="{x(idx):.1f}" y="{height - 6}" text-anchor="{anchor}" '
            f'font-family="Inter, sans-serif" font-size="8" fill="{_AXIS_COLOR}">'
            f'{points[idx].nav_date.strftime("%b %Y")}</text>'
        )

    # --- Benchmark dashed line ---
    bm_pts = " ".join(
        f"{x(i):.1f},{y(pt.benchmark_nav):.1f}"
        for i, pt in enumerate(points)
        if pt.benchmark_nav is not None
    )
    if bm_pts:
        parts.append(
            f'<polyline fill="none" stroke="{benchmark_color}" stroke-width="1" '
            f'stroke-dasharray="5 3" stroke-linejoin="round" '
            f'stroke-linecap="round" points="{bm_pts}"/>'
        )

    # --- Portfolio area fill ---
    p_line_pts = " ".join(
        f"{x(i):.1f},{y(pt.portfolio_nav):.1f}" for i, pt in enumerate(points)
    )
    area_pts = (
        f"{x(0):.1f},{pad_t + h} "
        + p_line_pts
        + f" {x(n - 1):.1f},{pad_t + h}"
    )
    parts.append(
        f'<polygon points="{area_pts}" fill="url(#areaGrad_{chart_id})"/>'
    )

    # --- Portfolio solid line ---
    parts.append(
        f'<polyline fill="none" stroke="{portfolio_color}" stroke-width="1.8" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{p_line_pts}"/>'
    )

    # --- End-of-line value labels ---
    last_p_y = y(points[-1].portfolio_nav)
    p_label_val = (points[-1].portfolio_nav - 1.0) * 100
    parts.append(
        f'<text x="{width - pad_r + 5}" y="{last_p_y + 3:.1f}" '
        f'font-family="Inter, sans-serif" font-size="9" font-weight="600" '
        f'font-variant-numeric="tabular-nums" fill="{portfolio_color}">'
        f'{p_label_val:+.1f}%</text>'
    )
    if points[-1].benchmark_nav is not None:
        last_bm_y = y(points[-1].benchmark_nav)
        bm_val = (points[-1].benchmark_nav - 1.0) * 100
        parts.append(
            f'<text x="{width - pad_r + 5}" y="{last_bm_y + 3:.1f}" '
            f'font-family="Inter, sans-serif" font-size="9" '
            f'font-variant-numeric="tabular-nums" fill="{benchmark_color}">'
            f'{bm_val:+.1f}%</text>'
        )

    return (
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="font-family:Inter,sans-serif">'
        f"{''.join(parts)}"
        f"</svg>"
    )


def drawdown_chart(
    points: Sequence[DrawdownPoint],
    *,
    width: int = 260,
    height: int = 140,
    line_color: str = "#8B0000",
) -> str:
    """Underwater/drawdown area chart. Returns inline SVG string.

    Uses burgundy tones instead of bright red — institutional palette.
    """
    if not points:
        return f'<svg width="{width}" height="{height}"></svg>'

    pad_l, pad_r, pad_t, pad_b = 6, 6, 10, 22
    w = width - pad_l - pad_r
    h = height - pad_t - pad_b

    min_dd = min(p.drawdown for p in points)  # most negative

    def y(v: float) -> float:
        if min_dd == 0:
            return float(pad_t)
        return pad_t + (v / min_dd) * h

    def x(i: int) -> float:
        return pad_l + (i / max(len(points) - 1, 1)) * w

    poly_pts = " ".join(
        f"{x(i):.1f},{y(pt.drawdown):.1f}" for i, pt in enumerate(points)
    )
    area_pts = (
        f"{pad_l},{pad_t} "
        + poly_pts
        + f" {x(len(points) - 1):.1f},{pad_t}"
    )

    # Zero line
    zero_line = (
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l + w}" y2="{pad_t}" '
        f'stroke="{_GRID_COLOR}" stroke-width="0.5"/>'
    )

    # Min annotation
    min_idx = min(range(len(points)), key=lambda i: points[i].drawdown)
    ann_x = x(min_idx)
    ann_y = y(points[min_idx].drawdown)
    ann_val = f"{points[min_idx].drawdown * 100:.2f}%"
    ann_date = points[min_idx].dd_date.strftime("%b '%y")

    chart_id = f"dd_{id(points) % 10000}"

    return (
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="font-family:Inter,sans-serif">'
        f'<defs>'
        f'<linearGradient id="ddGrad_{chart_id}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{line_color}" stop-opacity="0.04"/>'
        f'<stop offset="100%" stop-color="{line_color}" stop-opacity="0.15"/>'
        f'</linearGradient>'
        f'</defs>'
        f'{zero_line}'
        f'<polygon points="{area_pts}" fill="url(#ddGrad_{chart_id})"/>'
        f'<polyline fill="none" stroke="{line_color}" stroke-width="1.2" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{poly_pts}"/>'
        f'<line x1="{ann_x:.1f}" y1="{ann_y:.1f}" x2="{ann_x:.1f}" y2="{pad_t + h}" '
        f'stroke="{_AXIS_COLOR}" stroke-width="0.5" stroke-dasharray="3 2"/>'
        f'<text x="{ann_x + 4:.1f}" y="{ann_y + 11:.1f}" '
        f'font-size="8" font-weight="600" fill="{line_color}" '
        f'font-variant-numeric="tabular-nums">{ann_val}</text>'
        f'<text x="{ann_x + 4:.1f}" y="{ann_y + 21:.1f}" '
        f'font-size="7" fill="{_AXIS_COLOR}">{ann_date}</text>'
        f"</svg>"
    )


def allocation_bars(
    blocks: list[dict],  # [{"label": str, "weight": float, "color": str}]
    *,
    width: int = 240,
) -> str:
    """Horizontal allocation bar chart. Returns HTML string (not SVG).

    Slim, achatadas bars with institutional palette.
    """
    rows = ""
    for b in blocks:
        pct = b["weight"] * 100
        bar_w = max(int(b["weight"] * width), 2)
        rows += (
            f'<div style="margin-bottom:8px">'
            f'<div style="display:flex;justify-content:space-between;'
            f'margin-bottom:2px;font-size:9px;font-family:Inter,sans-serif">'
            f'<span style="color:#64748B;letter-spacing:0.01em">{b["label"]}</span>'
            f'<span style="font-weight:600;color:#0F172A;'
            f'font-variant-numeric:tabular-nums">{pct:.1f}%</span></div>'
            f'<div style="height:3px;background:#F1F5F9;border-radius:1.5px">'
            f'<div style="height:3px;width:{bar_w}px;background:{b["color"]};'
            f'border-radius:1.5px"></div></div></div>'
        )
    return rows
