"""Pure-Python SVG chart builders for Netz PDF reports.

All functions return an SVG string ready for inline embedding in HTML.
No external dependencies — computed coordinates only.
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


def performance_line_chart(
    points: Sequence[NavPoint],
    *,
    width: int = 580,
    height: int = 180,
    portfolio_color: str = "#185FA5",
    benchmark_color: str = "#9ca3af",
) -> str:
    """Cumulative performance line chart (portfolio vs benchmark).

    Returns inline SVG string.
    """
    if not points:
        return f'<svg width="{width}" height="{height}"></svg>'

    pad_l, pad_r, pad_t, pad_b = 48, 60, 16, 28
    w = width - pad_l - pad_r
    h = height - pad_t - pad_b

    all_vals = [p.portfolio_nav for p in points]
    if any(p.benchmark_nav is not None for p in points):
        all_vals += [p.benchmark_nav for p in points if p.benchmark_nav is not None]

    min_v = min(all_vals)
    max_v = max(all_vals)
    rng = max_v - min_v or 0.01

    n = len(points)

    def x(i: int) -> float:
        return pad_l + (i / max(n - 1, 1)) * w

    def y(v: float) -> float:
        return pad_t + h - ((v - min_v) / rng) * h

    # Portfolio polyline
    p_pts = " ".join(f"{x(i):.1f},{y(pt.portfolio_nav):.1f}" for i, pt in enumerate(points))
    # Benchmark polyline
    bm_pts = " ".join(
        f"{x(i):.1f},{y(pt.benchmark_nav):.1f}"
        for i, pt in enumerate(points)
        if pt.benchmark_nav is not None
    )

    # Y-axis labels (3 ticks)
    ticks = [min_v, (min_v + max_v) / 2, max_v]
    tick_lines = ""
    for t in ticks:
        yy = y(t)
        pct = (t - 1.0) * 100  # assume rebased to 1.0
        label = f"{pct:+.1f}%"
        tick_lines += (
            f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{width - pad_r}" y2="{yy:.1f}" '
            f'stroke="#e5e7eb" stroke-width="0.5"/>'
            f'<text x="{pad_l - 4}" y="{yy + 4:.1f}" text-anchor="end" '
            f'font-size="9" fill="#9ca3af">{label}</text>'
        )

    # X-axis labels (first and last)
    x_labels = (
        f'<text x="{pad_l}" y="{height - 4}" font-size="9" fill="#9ca3af">'
        f'{points[0].nav_date.strftime("%b %Y")}</text>'
        f'<text x="{width - pad_r}" y="{height - 4}" text-anchor="end" '
        f'font-size="9" fill="#9ca3af">'
        f'{points[-1].nav_date.strftime("%b %Y")}</text>'
    )

    # End-of-line labels
    last_p = y(points[-1].portfolio_nav)
    p_label_val = (points[-1].portfolio_nav - 1.0) * 100
    end_labels = (
        f'<text x="{width - pad_r + 4}" y="{last_p + 4:.1f}" '
        f'font-size="9" font-weight="600" fill="{portfolio_color}">'
        f'{p_label_val:+.1f}%</text>'
    )
    if points[-1].benchmark_nav is not None:
        last_bm = y(points[-1].benchmark_nav)
        bm_val = (points[-1].benchmark_nav - 1.0) * 100
        end_labels += (
            f'<text x="{width - pad_r + 4}" y="{last_bm + 4:.1f}" '
            f'font-size="9" fill="{benchmark_color}">{bm_val:+.1f}%</text>'
        )

    bm_line = (
        f'<polyline fill="none" stroke="{benchmark_color}" stroke-width="1" '
        f'stroke-dasharray="4 3" stroke-linejoin="round" points="{bm_pts}"/>'
        if bm_pts
        else ""
    )

    return (
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
        f"{tick_lines}"
        f"{bm_line}"
        f'<polyline fill="none" stroke="{portfolio_color}" stroke-width="1.8" '
        f'stroke-linejoin="round" points="{p_pts}"/>'
        f"{x_labels}{end_labels}"
        f"</svg>"
    )


def drawdown_chart(
    points: Sequence[DrawdownPoint],
    *,
    width: int = 260,
    height: int = 140,
    line_color: str = "#185FA5",
) -> str:
    """Underwater/drawdown area chart. Returns inline SVG string."""
    if not points:
        return f'<svg width="{width}" height="{height}"></svg>'

    pad_l, pad_r, pad_t, pad_b = 4, 4, 8, 20
    w = width - pad_l - pad_r
    h = height - pad_t - pad_b

    min_dd = min(p.drawdown for p in points)  # most negative

    # Scale: 0 → pad_t, min_dd → pad_t + h
    def y(v: float) -> float:
        if min_dd == 0:
            return float(pad_t)
        return pad_t + (v / min_dd) * h

    def x(i: int) -> float:
        return pad_l + (i / max(len(points) - 1, 1)) * w

    poly_pts = " ".join(f"{x(i):.1f},{y(pt.drawdown):.1f}" for i, pt in enumerate(points))
    # Close area polygon
    area_pts = (
        f"{pad_l},{pad_t} "
        + poly_pts
        + f" {x(len(points) - 1):.1f},{pad_t}"
    )

    # Min annotation
    min_idx = min(range(len(points)), key=lambda i: points[i].drawdown)
    ann_x = x(min_idx)
    ann_y = y(points[min_idx].drawdown)
    ann_val = f"{points[min_idx].drawdown * 100:.2f}%"
    ann_date = points[min_idx].dd_date.strftime("%b '%y")

    return (
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
        f'<polygon points="{area_pts}" fill="{line_color}" fill-opacity="0.12"/>'
        f'<polyline fill="none" stroke="{line_color}" stroke-width="1.2" '
        f'stroke-linejoin="round" points="{poly_pts}"/>'
        f'<line x1="{ann_x:.1f}" y1="{ann_y:.1f}" x2="{ann_x:.1f}" y2="{pad_t + h}" '
        f'stroke="#d1d5db" stroke-width="0.5" stroke-dasharray="3 2"/>'
        f'<text x="{ann_x + 3:.1f}" y="{ann_y + 12:.1f}" font-size="8" fill="#6b7280">'
        f"{ann_val}</text>"
        f'<text x="{ann_x + 3:.1f}" y="{ann_y + 22:.1f}" font-size="8" fill="#6b7280">'
        f"{ann_date}</text>"
        f"</svg>"
    )


def allocation_bars(
    blocks: list[dict],  # [{"label": str, "weight": float, "color": str}]
    *,
    width: int = 240,
) -> str:
    """Horizontal allocation bar chart. Returns HTML string (not SVG)."""
    rows = ""
    for b in blocks:
        pct = b["weight"] * 100
        bar_w = int(b["weight"] * width)
        rows += (
            f'<div style="margin-bottom:6px">'
            f'<div style="display:flex;justify-content:space-between;'
            f'margin-bottom:3px;font-size:10px">'
            f'<span style="color:#6b7280">{b["label"]}</span>'
            f'<span style="font-weight:600">{pct:.0f}%</span></div>'
            f'<div style="height:4px;background:#e5e7eb;border-radius:2px">'
            f'<div style="height:4px;width:{bar_w}px;background:{b["color"]};'
            f'border-radius:2px"></div></div></div>'
        )
    return rows
