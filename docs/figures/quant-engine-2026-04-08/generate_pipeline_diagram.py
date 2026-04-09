"""Eleven-Stage Portfolio Construction Pipeline diagram (vector).

Generates SVG + PDF (true vector text via matplotlib mathtext) and a
high-resolution PNG preview. Reproducible with `python <this file>`.

Output: docs/figures/quant-engine-2026-04-08/11_stage_portfolio_pipeline.{pdf,svg,png}
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Ellipse, FancyArrowPatch, Polygon, Rectangle  # noqa: E402

# ---------------------------------------------------------------------------
# Style — sober academic palette, true vector text in SVG/PDF
# ---------------------------------------------------------------------------
plt.rcParams.update(
    {
        "font.family": "serif",
        "font.size": 9,
        "mathtext.fontset": "dejavuserif",
        "mathtext.default": "regular",
        "svg.fonttype": "none",  # keep <text> elements as real text in SVG
        "pdf.fonttype": 42,  # TrueType embedded — vector + searchable
        "ps.fonttype": 42,
        "axes.unicode_minus": False,
    }
)

ACCENT = "#1f3864"          # deep institutional blue (main path)
ACCENT_FILL = "#eef2fa"     # very light blue tint (cascade phases)
GRAY_DARK = "#262626"
GRAY_MED = "#5a5a5a"
GRAY_VLIGHT = "#f3f3f3"
FAIL = "#7a1f1f"            # deep red, reserved for cascade failure arrows
CASCADE_EDGE = "#3a3a3a"

# ---------------------------------------------------------------------------
# Canvas
# ---------------------------------------------------------------------------
W, H = 11.0, 16.5
fig = plt.figure(figsize=(W, H))
ax = fig.add_axes([0.02, 0.01, 0.96, 0.98])
ax.set_xlim(0, 100)
ax.set_ylim(0, 150)
ax.set_aspect("equal")
ax.axis("off")

CX = 38       # main column centre
PCAX = 78     # parallel branch centre
COL_W = 40    # main process box width


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
def proc(cx, cy, w, h, title, sub=None, accent=False, fill="white"):
    ec = ACCENT if accent else "black"
    lw = 1.0 if accent else 0.7
    f = ACCENT_FILL if accent else fill
    ax.add_patch(
        Rectangle(
            (cx - w / 2, cy - h / 2),
            w,
            h,
            facecolor=f,
            edgecolor=ec,
            linewidth=lw,
            zorder=3,
        )
    )
    if sub:
        ax.text(cx, cy + 0.85, title, ha="center", va="center", fontsize=8.7, weight="bold", zorder=4)
        ax.text(
            cx,
            cy - 1.2,
            sub,
            ha="center",
            va="center",
            fontsize=7.0,
            color=GRAY_DARK,
            style="italic",
            zorder=4,
        )
    else:
        ax.text(cx, cy, title, ha="center", va="center", fontsize=8.7, weight="bold", zorder=4)


def diam(cx, cy, w, h, label):
    pts = [(cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2), (cx - w / 2, cy)]
    ax.add_patch(
        Polygon(pts, facecolor="white", edgecolor="black", linewidth=0.7, zorder=3)
    )
    ax.text(cx, cy, label, ha="center", va="center", fontsize=6.5, zorder=4)


def cyl(cx, cy, w, h, label, sub=None):
    rh = h * 0.34
    ax.add_patch(
        Rectangle(
            (cx - w / 2, cy - h / 2 + rh / 2),
            w,
            h - rh,
            facecolor=GRAY_VLIGHT,
            edgecolor="none",
            zorder=2,
        )
    )
    ax.plot(
        [cx - w / 2, cx - w / 2],
        [cy - h / 2 + rh / 2, cy + h / 2 - rh / 2],
        color="black",
        lw=0.7,
        zorder=3,
    )
    ax.plot(
        [cx + w / 2, cx + w / 2],
        [cy - h / 2 + rh / 2, cy + h / 2 - rh / 2],
        color="black",
        lw=0.7,
        zorder=3,
    )
    ax.add_patch(
        Ellipse(
            (cx, cy - h / 2 + rh / 2),
            w,
            rh,
            facecolor=GRAY_VLIGHT,
            edgecolor="black",
            linewidth=0.7,
            zorder=2,
        )
    )
    ax.add_patch(
        Ellipse(
            (cx, cy + h / 2 - rh / 2),
            w,
            rh,
            facecolor=GRAY_VLIGHT,
            edgecolor="black",
            linewidth=0.7,
            zorder=4,
        )
    )
    ax.text(
        cx,
        cy + (0.6 if sub else 0),
        label,
        ha="center",
        va="center",
        fontsize=8.4,
        weight="bold",
        zorder=5,
    )
    if sub:
        ax.text(
            cx,
            cy - 1.4,
            sub,
            ha="center",
            va="center",
            fontsize=6.5,
            color=GRAY_MED,
            style="italic",
            zorder=5,
        )


def arr(x1, y1, x2, y2, color=ACCENT, lw=1.1, style="-", label=None, lab_dx=0, lab_dy=0):
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1),
            (x2, y2),
            arrowstyle="-|>",
            mutation_scale=11,
            color=color,
            lw=lw,
            linestyle=style,
            shrinkA=0,
            shrinkB=0,
            zorder=2,
        )
    )
    if label:
        mx = (x1 + x2) / 2 + lab_dx
        my = (y1 + y2) / 2 + lab_dy
        ax.text(
            mx,
            my,
            label,
            fontsize=6.4,
            color=color,
            style="italic",
            ha="center",
            va="center",
            bbox=dict(boxstyle="round,pad=0.18", facecolor="white", edgecolor="none"),
            zorder=5,
        )


def num(cx, cy, n):
    ax.add_patch(
        mpatches.Circle((cx, cy), 1.7, facecolor=ACCENT, edgecolor=ACCENT, zorder=5)
    )
    ax.text(
        cx,
        cy,
        str(n),
        ha="center",
        va="center",
        fontsize=6.6,
        color="white",
        weight="bold",
        zorder=6,
    )


# ---------------------------------------------------------------------------
# Title bar
# ---------------------------------------------------------------------------
ax.text(
    50,
    144.5,
    "Eleven-Stage Portfolio Construction Pipeline",
    ha="center",
    va="center",
    fontsize=14.5,
    weight="bold",
)
ax.text(
    50,
    141,
    r"Netz Analysis Engine $\cdot$ Quant Core $\cdot$ CLARABEL Optimizer Cascade",
    ha="center",
    va="center",
    fontsize=9.2,
    style="italic",
    color=GRAY_MED,
)
ax.plot([8, 92], [138, 138], color="black", lw=0.4)

# ---------------------------------------------------------------------------
# Stage 1 — Data ingestion (TimescaleDB cylinder)
# ---------------------------------------------------------------------------
# Stage 1 is the combined "Data Ingestion & Universe" group: the
# TimescaleDB cylinder + the admissibility filter share a single badge.
cyl(
    CX,
    131,
    34,
    5.5,
    "TimescaleDB hypertables",
    "macro_data, nav_timeseries, fund_risk_metrics",
)

# ---------------------------------------------------------------------------
# Stage 1 — instruments_universe admissibility filter
# ---------------------------------------------------------------------------
proc(
    CX,
    122,
    COL_W,
    6,
    "instruments_universe",
    r"admissibility filter   $|r_{t,t-1}|\,\leq\,0.5$   (MAX_DAILY_RETURN_ABS)",
)
arr(CX, 128.25, CX, 125)
num(CX - 23, 126.5, 1)  # badge spans the cylinder + filter group

# ---------------------------------------------------------------------------
# Stage 2 — Regime Identification (HMM tactical + Composite Stress strategic)
# ---------------------------------------------------------------------------
proc(
    CX,
    113,
    COL_W,
    7,
    "Regime Identification",
    r"HMM($\log\mathrm{VIX}$) tactical   $\bigoplus$   composite stress score (9 signals) strategic",
)
arr(CX, 119, CX, 116.5)
num(CX - 23, 113, 2)

# ---------------------------------------------------------------------------
# Stage 3 — Risk & Covariance Matrix
# ---------------------------------------------------------------------------
proc(
    CX,
    103,
    COL_W,
    6,
    "Risk & Covariance Matrix",
    r"Ledoit–Wolf shrinkage   $\bullet$   Marchenko–Pastur denoising",
)
arr(CX, 109.5, CX, 106)
num(CX - 23, 103, 3)

# ---------------------------------------------------------------------------
# Stage 4 — Expected Returns (Black–Litterman)
# ---------------------------------------------------------------------------
proc(
    CX,
    93,
    COL_W,
    6,
    "Expected Returns",
    r"Black–Litterman posterior   $\mu_{\mathrm{BL}}=[(\tau\Sigma)^{-1}+P^\top\Omega^{-1}P]^{-1}[\,\cdot\,]$",
)
arr(CX, 100, CX, 96)
num(CX - 23, 93, 4)

# ---------------------------------------------------------------------------
# Stage 9 — Factor Decomposition (PCA, parallel branch)
# ---------------------------------------------------------------------------
proc(
    PCAX,
    93,
    36,
    6,
    "Factor Decomposition",
    r"PCA exposures   $X = U\,\Sigma\,V^\top$    (parallel branch)",
)
num(PCAX - 21, 93, 9)
arr(CX + COL_W / 2, 93, PCAX - 18, 93, color=GRAY_MED, lw=0.8, style=(0, (3, 2)))

# ---------------------------------------------------------------------------
# CLARABEL Optimizer Cascade (Stages 6, 7, 7.5, 8)
# ---------------------------------------------------------------------------
casc_top, casc_bot = 87, 22
ax.add_patch(
    Rectangle(
        (CX - 30, casc_bot),
        60,
        casc_top - casc_bot,
        facecolor="#fbfbfb",
        edgecolor=CASCADE_EDGE,
        linewidth=0.7,
        linestyle=(0, (2, 2)),
        zorder=1,
    )
)
ax.text(
    CX,
    casc_top - 2,
    "CLARABEL OPTIMIZER CASCADE",
    ha="center",
    va="center",
    fontsize=10,
    weight="bold",
    color=CASCADE_EDGE,
    zorder=2,
)
ax.text(
    CX,
    casc_top - 4.2,
    r"first feasible solution exits the cascade  $\,\cdot\,$  SCS solver fallback at every phase",
    ha="center",
    va="center",
    fontsize=7,
    color=GRAY_MED,
    style="italic",
    zorder=2,
)

# Entry from Expected Returns into the cascade
arr(CX, 90, CX, 80.9)

# Cascade phase y-coordinates (delta = 7 for breathing room)
Y_P1, Y_D1 = 78.0, 71.0
Y_P15, Y_D2 = 64.0, 57.0
Y_P2, Y_D3 = 50.0, 43.0
Y_P3 = 36.0
PHASE_H = 5.8
DIAM_H = 4.6


def cascade_fail_label(y_arrow_mid, text):
    """Place a 'fail' label to the LEFT of the short fall-through arrow."""
    ax.text(
        CX - 11,
        y_arrow_mid,
        text,
        fontsize=6.4,
        color=FAIL,
        style="italic",
        ha="right",
        va="center",
    )


# Phase 1
proc(
    CX,
    Y_P1,
    38,
    PHASE_H,
    r"Phase 1   $\cdot$   Mean–Variance Programme",
    r"$\max_{w}\;\mu^\top w \,-\, \frac{\lambda}{2}\, w^\top\Sigma w$",
    accent=True,
)
num(CX + 22, Y_P1, 5)

# Phase 1 → Diamond 1
arr(CX, Y_P1 - PHASE_H / 2, CX, Y_D1 + DIAM_H / 2)

# Diamond 1
diam(CX, Y_D1, 18, DIAM_H, "numerical / feasible?")

# Diamond 1 → Phase 1.5  (FAIL path)
arr(
    CX,
    Y_D1 - DIAM_H / 2,
    CX,
    Y_P15 + PHASE_H / 2,
    color=FAIL,
    style=(0, (4, 2)),
)
cascade_fail_label((Y_D1 - DIAM_H / 2 + Y_P15 + PHASE_H / 2) / 2, "infeasible")

# Phase 1.5
proc(
    CX,
    Y_P15,
    38,
    PHASE_H,
    r"Phase 1.5   $\cdot$   Robust SOCP",
    r"ellipsoidal $\mathcal{U}_\mu = \{\mu_0 + A\,u\;:\;\|u\|_2 \leq 1\}$",
    accent=True,
)
num(CX + 22, Y_P15, 6)

# Phase 1.5 → Diamond 2
arr(CX, Y_P15 - PHASE_H / 2, CX, Y_D2 + DIAM_H / 2)

# Diamond 2
diam(CX, Y_D2, 18, DIAM_H, "CVaR budget honoured?")

# Diamond 2 → Phase 2  (FAIL path)
arr(
    CX,
    Y_D2 - DIAM_H / 2,
    CX,
    Y_P2 + PHASE_H / 2,
    color=FAIL,
    style=(0, (4, 2)),
)
cascade_fail_label((Y_D2 - DIAM_H / 2 + Y_P2 + PHASE_H / 2) / 2, "CVaR breach")

# Phase 2
proc(
    CX,
    Y_P2,
    38,
    PHASE_H,
    r"Phase 2   $\cdot$   Hard Variance Ceiling",
    r"Cornish–Fisher CVaR inversion   $w^\top\Sigma w \leq \sigma_{\max}^2$",
    accent=True,
)
num(CX + 22, Y_P2, 7)

# Phase 2 → Diamond 3
arr(CX, Y_P2 - PHASE_H / 2, CX, Y_D3 + DIAM_H / 2)

# Diamond 3
diam(CX, Y_D3, 18, DIAM_H, r"feasible region $\neq \emptyset$?")

# Diamond 3 → Phase 3  (FAIL path)
arr(
    CX,
    Y_D3 - DIAM_H / 2,
    CX,
    Y_P3 + PHASE_H / 2,
    color=FAIL,
    style=(0, (4, 2)),
)
cascade_fail_label((Y_D3 - DIAM_H / 2 + Y_P3 + PHASE_H / 2) / 2, "infeasible")

# Phase 3 (final fallback — no diamond)
proc(
    CX,
    Y_P3,
    38,
    PHASE_H,
    r"Phase 3   $\cdot$   Minimum Variance",
    r"$\min_{w}\; w^\top\Sigma w$    final feasibility fallback",
    accent=True,
)
num(CX + 22, Y_P3, 8)

# Cascade exit: single long arrow from Phase 3 bottom to cascade box bottom,
# with the "first feasible solution" annotation placed to the right.
arr(CX, Y_P3 - PHASE_H / 2, CX, casc_bot)
ax.text(
    CX + 12,
    27.5,
    r"$\Rightarrow$  first feasible $w^{\!*}$",
    ha="left",
    va="center",
    fontsize=7.5,
    color=CASCADE_EDGE,
    weight="bold",
    style="italic",
)

# ---------------------------------------------------------------------------
# Stage 10 — Stress Validation
# ---------------------------------------------------------------------------
proc(
    CX,
    16,
    COL_W + 4,
    6,
    "Stress Validation",
    r"regime CVaR multipliers   RISK_OFF $\times\,0.85$    CRISIS $\times\,0.70$",
)
arr(CX, 22, CX, 19)
num(CX - 25, 16, 10)

# Curved branch from PCA → Stress Validation (factor loadings consumed in stress)
ax.plot(
    [PCAX, PCAX],
    [90, 16.0],
    color=GRAY_MED,
    lw=0.8,
    linestyle=(0, (3, 2)),
    zorder=2,
)
arr(PCAX, 16, CX + COL_W / 2 + 2, 16, color=GRAY_MED, lw=0.8, style=(0, (3, 2)))
ax.text(
    PCAX + 1,
    55,
    "factor loadings",
    rotation=-90,
    fontsize=6.5,
    color=GRAY_MED,
    style="italic",
    ha="left",
    va="center",
)

# ---------------------------------------------------------------------------
# Stage 11 — Activation: persisted into fund_risk_metrics
# ---------------------------------------------------------------------------
cyl(
    CX,
    7,
    38,
    6,
    "fund_risk_metrics",
    r"persisted: $w^*$, $\mathrm{CVaR}_{95}$, factor exposures, regime tag",
)
arr(CX, 13, CX, 10)
num(CX - 22.5, 7, 11)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
ax.text(
    50,
    1.0,
    r"Generated 2026-04-08  $\cdot$  matplotlib mathtext (vector)  $\cdot$  source: backend/quant_engine/optimizer.py",
    ha="center",
    va="center",
    fontsize=6.4,
    color=GRAY_MED,
    style="italic",
)

# ---------------------------------------------------------------------------
# Save vector + raster outputs
# ---------------------------------------------------------------------------
out_dir = Path(__file__).parent
base = out_dir / "11_stage_portfolio_pipeline"
fig.savefig(base.with_suffix(".pdf"))
fig.savefig(base.with_suffix(".svg"))
fig.savefig(base.with_suffix(".png"), dpi=300)
print(f"wrote {base.with_suffix('.pdf')}")
print(f"wrote {base.with_suffix('.svg')}")
print(f"wrote {base.with_suffix('.png')}")
