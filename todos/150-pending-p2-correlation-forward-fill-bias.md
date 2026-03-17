---
status: pending
priority: p2
issue_id: "150"
tags: [code-review, data-integrity, correlation, math, wealth]
dependencies: ["138"]
---

# Correlation — Forward-Fill Distorts Returns, Use Date Intersection

## Problem Statement

The correlation regime service loads NavTimeseries returns for multiple instruments
and handles missing dates with forward-fill. This is mathematically incorrect for
return series: forward-filling prices creates artificial zero-return days on dates
where an instrument has no data, which underestimates correlation between instruments
with different trading calendars (e.g., Brazilian funds vs US ETFs).

The review flagged todo 138 (SQL LIMIT bias) as a related finding, but the root cause
is the forward-fill strategy, not just the LIMIT clause.

## Findings

**Affected files:**
- `backend/app/domains/wealth/routes/correlation_regime.py`
- `backend/vertical_engines/wealth/correlation/service.py`

**The bug:**
```python
# WRONG — forward-fill creates zero returns on missing dates
returns_matrix = returns_df.ffill()

# Artificial zero return days look like independence from other instruments
# → underestimates true correlation
```

**Why it matters:** A fund that doesn't trade on a given day (Brazilian holiday, lock-up
period) shows return = 0 via forward-fill. When the market moved that day, the fund
appears uncorrelated — masking real portfolio concentration risk.

## Proposed Solutions

### Option A — Date Intersection (Recommended)

Use only dates where ALL instruments in the portfolio have data:

```python
# CORRECT — align on intersection of dates with data
returns_matrix = returns_df.dropna(how="any", axis=0)

# If intersection is too small (< min_observations), raise ValueError
# with message: "Insufficient overlapping dates for correlation (N days). 
# Minimum required: {min_observations}."
```

**Pros:** Mathematically correct. Simple. Already consistent with how
`quant_engine/correlation_regime_service.py` should work.
**Cons:** May reduce sample size significantly if instruments have very different
coverage periods. Needs minimum observation guard.

### Option B — Pairwise Intersection per Pair

Compute correlation for each (i, j) pair using only dates where both have data:

```python
# For each pair, use their specific intersection
for i, j in pairs:
    common_idx = returns_i.dropna().index.intersection(returns_j.dropna().index)
    corr_ij = returns_i[common_idx].corr(returns_j[common_idx])
```

**Pros:** Maximizes sample size per pair.
**Cons:** Correlation matrix may not be positive semi-definite — breaks eigenvalue
analysis downstream. Not recommended when Marchenko-Pastur denoising is applied.

### Recommended Action

Option A. The Marchenko-Pastur denoising requires a valid positive semi-definite
matrix, which pairwise computation (Option B) cannot guarantee. Use intersection
with a clear error when sample falls below `min_observations` (default: 45).

## Technical Details

**Fix location:** `vertical_engines/wealth/correlation/service.py`

```python
def _build_returns_matrix(
    self,
    returns_by_instrument: dict[str, list[float]],
    dates: list[date],
) -> np.ndarray:
    df = pd.DataFrame(returns_by_instrument, index=dates)
    
    # Use intersection — do NOT forward-fill
    df_clean = df.dropna(how="any", axis=0)
    
    if len(df_clean) < self._config.get("min_observations", 45):
        raise ValueError(
            f"Insufficient overlapping dates for correlation: {len(df_clean)} days. "
            f"Instruments may have mismatched trading calendars."
        )
    
    return df_clean.values  # shape: (T_intersection, N)
```

**Also update** the docstring in `quant_engine/correlation_regime_service.py` to
explicitly state: "returns_matrix must contain NO NaN values — caller is responsible
for alignment via date intersection before passing."

## Acceptance Criteria

- [ ] `dropna(how="any")` replaces any `ffill()` call in correlation data preparation
- [ ] `ValueError` raised with clear message when intersection < `min_observations`
- [ ] Unit test: two instruments with different missing dates → intersection used,
      not forward-fill
- [ ] Unit test: intersection < 45 days → raises ValueError with instrument count
- [ ] Docstring in `correlation_regime_service.py` updated to document NaN precondition

## Work Log

**2026-03-17 — Gap identified in review session (Sonnet/human):**

The `ce-review` agents flagged todo 138 (SQL LIMIT bias in correlation route) but
did not identify the forward-fill issue. This finding comes from a cross-session
design review where the decision was made explicitly:

> "When loading NavTimeseries for correlation, use INTERSECTION of dates where
> ALL instruments have data. Do NOT forward-fill returns — creates artificial
> zero-return days that underestimate correlation."
> — docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md (D9)

**Note to resolving agent:** Fix this BEFORE or ALONGSIDE todo 138. The LIMIT bias
in 138 and the forward-fill here are independent bugs but both affect correlation
correctness. Fix this one first — it changes the shape of the input matrix, which
may resolve some of the LIMIT behavior in 138.
