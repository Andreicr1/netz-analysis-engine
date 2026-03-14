"""Chart rendering module for IC Memo PDF generation.

Renders data-driven charts as in-memory PNG BytesIO buffers for embedding in
institutional PDFs.  All render functions accept validated data dicts and return
seeked-to-zero BytesIO objects.  No temporary files are created on disk.

Charts supported:
  - waterfall  : horizontal waterfall for return attribution (ch08)
  - radar      : spider / radar chart for risk profile (ch11)
  - heatmap    : colour-coded sensitivity matrix (ch08, ch09)

Non-interactive Agg backend is set at module import time — safe in server contexts
(no DISPLAY environment variable required).
"""
from __future__ import annotations

import json
import logging
import os as _os
import re
from io import BytesIO
from typing import Any

_os.environ.setdefault("MPLBACKEND", "Agg")  # Set before any matplotlib import

logger = logging.getLogger(__name__)

# ── Netz brand palette ──────────────────────────────────────────────────────
NETZ_NAVY   = "#020F59"
NETZ_ORANGE = "#FF975A"
NETZ_GREY   = "#E8EAF0"
NETZ_DARK   = "#1A1A2E"
NETZ_WHITE  = "#FCFDFD"

# A4 body width in inches (16 cm) at 150 DPI
_CHART_WIDTH_IN  = 6.3   # ≈ 16 cm
_CHART_HEIGHT_IN = 3.2   # standard chart height
_DPI = 150

def _fig_to_bytesio(fig: Any) -> BytesIO:
    """Save a matplotlib figure to an in-memory PNG buffer and return it seeked to 0."""
    import matplotlib.pyplot as plt  # lazy — MPLBACKEND env var already set
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight", facecolor=NETZ_WHITE)
    plt.close(fig)
    buf.seek(0)
    return buf


def _validate_required(data: dict, fields: list[str], chart_type: str) -> None:
    """Raise ValueError if any required field is missing or None."""
    missing = [f for f in fields if data.get(f) is None]
    if missing:
        raise ValueError(
            f"chart_renderer.{chart_type}: missing required fields: {missing}",
        )


# ── Waterfall chart ─────────────────────────────────────────────────────────

def render_waterfall(data: dict[str, Any]) -> BytesIO:
    """Horizontal waterfall chart for return attribution.

    Required keys:
        base_yield  (float) — gross coupon or base yield %
        total_irr   (float) — net total IRR %
    Optional keys:
        fee_income  (float, default 0) — origination/exit fee annualised %
        pik         (float, default 0) — PIK component %
        label       (str)              — subtitle (e.g. "Base Case")

    Returns:
        BytesIO containing a PNG image, seeked to position 0.

    Raises:
        ValueError if required fields are missing or values are implausible.

    """
    import matplotlib.pyplot as plt  # lazy — ensures MPLBACKEND env var is already set

    _validate_required(data, ["base_yield", "total_irr"], "waterfall")

    base_yield  = float(data["base_yield"])
    fee_income  = float(data.get("fee_income") or 0)
    pik         = float(data.get("pik") or 0)
    total_irr   = float(data["total_irr"])
    label       = data.get("label", "")

    # Build bars: each component is a horizontal segment
    components = [
        ("Base Yield", base_yield),
    ]
    if fee_income:
        components.append(("Fee Income", fee_income))
    if pik:
        components.append(("PIK Accrual", pik))
    components.append(("Net IRR", total_irr))

    names   = [c[0] for c in components]
    values  = [c[1] for c in components]
    colours = [NETZ_NAVY] * (len(components) - 1) + [NETZ_ORANGE]

    fig, ax = plt.subplots(figsize=(_CHART_WIDTH_IN, max(2.5, len(components) * 0.7)))
    fig.patch.set_facecolor(NETZ_WHITE)
    ax.set_facecolor(NETZ_WHITE)

    bars = ax.barh(names, values, color=colours, height=0.55, edgecolor="white", linewidth=0.5)

    # Value labels
    for bar, val in zip(bars, values, strict=False):
        ax.text(
            bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2,
            f"{val:.1f}%", va="center", ha="left",
            fontsize=9, color=NETZ_DARK, fontweight="bold",
        )

    ax.set_xlabel("Return (%)", fontsize=9, color=NETZ_DARK)
    title = "Return Attribution"
    if label:
        title += f" — {label}"
    ax.set_title(title, fontsize=10, color=NETZ_NAVY, fontweight="bold", pad=8)
    ax.tick_params(axis="both", labelsize=8, colors=NETZ_DARK)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(NETZ_GREY)
    ax.spines["bottom"].set_color(NETZ_GREY)
    ax.set_xlim(0, max(values) * 1.2)
    ax.grid(axis="x", linestyle="--", linewidth=0.4, color=NETZ_GREY, alpha=0.7)
    ax.invert_yaxis()

    fig.tight_layout()
    return _fig_to_bytesio(fig)


# ── Radar / spider chart ────────────────────────────────────────────────────

def render_radar(data: dict[str, Any]) -> BytesIO:
    """Radar / spider chart for risk profile scoring.

    Required keys:
        axes    (list[str], len 6)   — axis labels
        scores  (list[float], len 6) — risk scores 0–10

    Optional keys:
        label   (str) — chart subtitle

    Returns:
        BytesIO containing a PNG image, seeked to position 0.

    Raises:
        ValueError if axes/scores length != 6 or any score is outside [0, 10].

    """
    import matplotlib.pyplot as plt  # lazy import
    import numpy as np

    _validate_required(data, ["axes", "scores"], "radar")

    axes   = list(data["axes"])
    scores = [float(s) for s in data["scores"]]
    label  = data.get("label", "Risk Profile")

    if len(axes) != 6 or len(scores) != 6:
        raise ValueError(
            f"chart_renderer.radar: axes and scores must each have exactly 6 elements "
            f"(got axes={len(axes)}, scores={len(scores)})",
        )
    if any(s < 0 or s > 10 for s in scores):
        raise ValueError(
            f"chart_renderer.radar: all scores must be in [0, 10] (got {scores})",
        )

    # Polar coordinates
    n = len(axes)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    angles += angles[:1]   # close the polygon
    scores_plot = scores + scores[:1]

    fig, ax = plt.subplots(figsize=(4.5, 4.5), subplot_kw={"polar": True})
    fig.patch.set_facecolor(NETZ_WHITE)
    ax.set_facecolor(NETZ_WHITE)

    # Background rings
    for level in [2, 4, 6, 8, 10]:
        ring = [level] * (n + 1)
        ax.plot(angles, ring, color=NETZ_GREY, linewidth=0.5, linestyle="--")

    # Risk polygon
    ax.fill(angles, scores_plot, color=NETZ_NAVY, alpha=0.20)
    ax.plot(angles, scores_plot, color=NETZ_NAVY, linewidth=2)
    ax.scatter(angles[:-1], scores, color=NETZ_ORANGE, s=50, zorder=5)

    # Score labels
    for angle, score in zip(angles[:-1], scores, strict=False):
        ax.annotate(
            f"{score:.1f}",
            xy=(angle, score),
            xytext=(angle, score + 0.8),
            ha="center", va="center",
            fontsize=8, color=NETZ_DARK, fontweight="bold",
        )

    # Axis labels
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(axes, size=8, color=NETZ_DARK)
    ax.set_ylim(0, 10)
    ax.set_yticks([2, 4, 6, 8, 10])
    ax.set_yticklabels(["2", "4", "6", "8", "10"], size=7, color="#999")
    ax.yaxis.set_tick_params(pad=2)
    ax.set_title(label, fontsize=10, color=NETZ_NAVY, fontweight="bold", pad=14)
    ax.spines["polar"].set_color(NETZ_GREY)
    ax.grid(color=NETZ_GREY, linewidth=0.4)

    fig.tight_layout()
    return _fig_to_bytesio(fig)


# ── Heat map ────────────────────────────────────────────────────────────────

def render_heatmap(data: dict[str, Any]) -> BytesIO:
    """Colour-coded sensitivity heat map (IRR or recovery vs. two variables).

    Required keys:
        row_label   (str)                   — y-axis label
        col_label   (str)                   — x-axis label
        row_values  (list[float], len ≥ 2)  — y-axis tick values
        col_values  (list[float], len ≥ 2)  — x-axis tick values
        matrix      (list[list[float]])     — values[row][col], shape must match

    Optional keys:
        title (str) — chart title
        unit  (str) — value unit label, e.g. "%" or "x" (default "")

    Returns:
        BytesIO containing a PNG image, seeked to position 0.

    Raises:
        ValueError if matrix shape doesn't match row_values × col_values.

    """
    import matplotlib.pyplot as plt  # lazy import
    import numpy as np

    _validate_required(
        data, ["row_label", "col_label", "row_values", "col_values", "matrix"], "heatmap",
    )

    row_label  = str(data["row_label"])
    col_label  = str(data["col_label"])
    row_values = [float(v) for v in data["row_values"]]
    col_values = [float(v) for v in data["col_values"]]
    matrix     = [[float(v) for v in row] for row in data["matrix"]]
    title      = data.get("title", "Sensitivity Analysis")
    unit       = data.get("unit", "")

    n_rows = len(row_values)
    n_cols = len(col_values)

    if len(matrix) != n_rows or any(len(r) != n_cols for r in matrix):
        raise ValueError(
            f"chart_renderer.heatmap: matrix shape must be "
            f"{n_rows}×{n_cols} (row_values × col_values) — got {len(matrix)} rows",
        )

    mat = np.array(matrix)

    fig, ax = plt.subplots(figsize=(_CHART_WIDTH_IN, max(2.5, n_rows * 0.55 + 1)))
    fig.patch.set_facecolor(NETZ_WHITE)

    # Diverging colourmap: low=red, mid=yellow, high=green (good for IRR / recovery)
    im = ax.imshow(mat, cmap="RdYlGn", aspect="auto",
                   vmin=mat.min() * 0.9, vmax=mat.max() * 1.05)

    # Cell labels
    for r in range(n_rows):
        for c in range(n_cols):
            val = mat[r, c]
            text = f"{val:.1f}{unit}"
            # Choose white or dark text based on cell brightness
            norm = (val - mat.min()) / max(mat.max() - mat.min(), 1e-9)
            txt_color = "white" if norm < 0.35 or norm > 0.75 else NETZ_DARK
            ax.text(c, r, text, ha="center", va="center",
                    fontsize=8, color=txt_color, fontweight="bold")

    ax.set_xticks(range(n_cols))
    ax.set_xticklabels([f"{v}" for v in col_values], fontsize=8, color=NETZ_DARK)
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels([f"{v}" for v in row_values], fontsize=8, color=NETZ_DARK)
    ax.set_xlabel(col_label, fontsize=9, color=NETZ_DARK)
    ax.set_ylabel(row_label, fontsize=9, color=NETZ_DARK)
    ax.set_title(title, fontsize=10, color=NETZ_NAVY, fontweight="bold", pad=8)

    fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02).ax.tick_params(labelsize=7)
    fig.tight_layout()
    return _fig_to_bytesio(fig)


# ── Dispatch ────────────────────────────────────────────────────────────────

_RENDER_FN = {
    "waterfall": render_waterfall,
    "radar":     render_radar,
    "heatmap":   render_heatmap,
}


def render_chart(chart_type: str, data: dict[str, Any]) -> BytesIO:
    """Dispatch to the appropriate render function by chart type.

    Raises:
        ValueError: if chart_type is unknown or data is invalid.

    """
    fn = _RENDER_FN.get(chart_type)
    if fn is None:
        raise ValueError(
            f"chart_renderer: unknown chart type '{chart_type}'. "
            f"Supported: {list(_RENDER_FN.keys())}",
        )
    return fn(data)


# ── CHARTDATA embedding helpers ──────────────────────────────────────────────

CHART_MARKER_RE = r"<!--\s*CHART:(?P<type>waterfall|radar|heatmap):(?P<title>[^>]+?)\s*-->"
CHARTDATA_RE    = r"<!--\s*CHARTDATA:(?P<json>\{[^\n]+\})\s*-->"


def inject_chart_data_into_text(section_text: str, charts: list[dict]) -> str:
    """Embed CHARTDATA comments after each matching CHART marker in section_text.

    This makes chart data self-contained in the stored markdown so that PDFs
    can be regenerated from cached chapters without re-running the LLM.

    Example — before:
        <!-- CHART:waterfall:Return Attribution — Base Case -->

    After:
        <!-- CHART:waterfall:Return Attribution — Base Case -->
        <!-- CHARTDATA:{"type":"waterfall","title":"Return Attribution — Base Case","data":{...}} -->
    """
    if not charts:
        return section_text

    chart_map = {c["title"]: c for c in charts if c.get("title")}

    pattern = re.compile(CHART_MARKER_RE)

    def _replace(m: re.Match) -> str:
        title = m.group("title").strip()
        original = m.group(0)
        if title in chart_map:
            try:
                chart_json = json.dumps(chart_map[title], ensure_ascii=False, separators=(",", ":"))
                return f"{original}\n<!-- CHARTDATA:{chart_json} -->"
            except (TypeError, ValueError) as exc:
                logger.warning("inject_chart_data: could not serialise chart '%s': %s", title, exc)
        return original

    return pattern.sub(_replace, section_text)


def extract_chart_index(text: str) -> dict[str, dict]:
    """Parse CHARTDATA comments from markdown text into a title→chart_entry dict.

    Used by the PDF renderer to rebuild chart data from stored chapter markdown.
    """
    index: dict[str, dict] = {}
    for m in re.finditer(CHARTDATA_RE, text):
        try:
            entry = json.loads(m.group("json"))
            title = entry.get("title", "")
            if title:
                index[title] = entry
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("extract_chart_index: could not parse CHARTDATA: %s", exc)
    return index
