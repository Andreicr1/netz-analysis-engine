# Wealth Math Conventions

Pinned conventions for institutional wealth analytics.
Audit reference: `docs/audits/2026-04-30-wealth-math-audit-meta-jury-gpt55.md`.

---

## Sterling Ratio Denominator (WMJ-022)

**Convention adopted:** Original Sterling (Kestner 1996).

```
Sterling = ann_return / |avg_max_dd − 0.10|
```

`avg_max_dd` is **negative** (drawdowns are negative by sign convention in this codebase). The subtraction of 0.10 therefore *increases* the denominator magnitude:

| avg_max_dd | denominator | interpretation |
|------------|-------------|----------------|
| −0.05      | \|−0.05 − 0.10\| = 0.15 | low-DD fund, cushioned |
| −0.20      | \|−0.20 − 0.10\| = 0.30 | moderate DD |
| −0.40      | \|−0.40 − 0.10\| = 0.50 | high DD |

The alternative "modified Sterling" convention (`|DD| − 10%`, i.e. `abs(avg_max_dd) − 0.10`) was **not adopted** because it produces negative or near-zero denominators for low-drawdown funds (e.g. money market, short-duration bond), making the ratio undefined or explosive.

**Implementation:** `backend/quant_engine/return_statistics_service.py` → `_compute_sterling_ratio()`.

**Annualization:** Geometric (cumulative return raised to 252/n power), matching the F08 convention for all return annualization in the engine.

---

## Cash Residual Return Convention (WMJ-024)

**Convention adopted:** `r_cash = 0.0` (zero return).

When portfolio or benchmark weights do not sum to 1.0, the attribution service injects a `cash_residual` sleeve to absorb the gap. Both the portfolio and benchmark cash sleeves are assigned **zero return**.

This is standard Brinson-Fachler practice: cash is the numeraire with no excess contribution. The allocation effect of the cash sleeve captures whether the portfolio is over- or under-invested relative to the benchmark.

If IC policy requires overnight/SOFR attribution for the cash sleeve, `0.0` should be replaced with the period overnight rate at the injection site.

**Implementation:** `backend/vertical_engines/wealth/attribution/service.py` → `_CASH_LABEL = "cash_residual"`, lines 243–244.

---

## Drawdown Sign Convention

Drawdowns are **negative** throughout the codebase (`compute_drawdown_series` returns values ≤ 0). `max_drawdown` is the most negative value in the series (i.e. `np.min(dd_series)`).

This convention is consistent across:
- `quant_engine/drawdown_service.py`
- `quant_engine/return_statistics_service.py` (Sterling, Calmar)
- `quant_engine/cvar_service.py`
- `vertical_engines/wealth/model_portfolio/validation_gate.py`
