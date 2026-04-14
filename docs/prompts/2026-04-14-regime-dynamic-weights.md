# Regime Model Upgrade — Dynamic Weights + Econometric Rebalance

**Date:** 2026-04-14
**Branch:** `feat/regime-dynamic-weights`
**Sessions:** 3 (sequenced — each session depends on the previous)
**Priority:** HIGH — regime model is producing false-negative readings

---

## Problem

The regime classifier (`classify_regime_multi_signal` in `backend/quant_engine/regime_service.py`) uses static weights that:

1. **Over-weight VIX** (20%) — a structurally suppressed indicator (dealer gamma hedging, passive flows, vol-selling carry). With WTI at $114 (+84% in 3m), VIX at 19.5 is an anomaly, not a signal of calm.
2. **Under-weight real-economy signals** (45%) — econometric indicators (CFNAI, Sahm, energy, employment) are harder to manipulate and serve as leading indicators of stress.
3. **Use fixed weights** that can't adapt to signal amplitude — an energy shock at 100/100 contributes only 10 points to the composite regardless of magnitude.

Result: composite = 22.2/100, classified RISK_ON (Expansion) despite an extreme energy shock.

## Solution — Three Phases (Strict Sequence)

### Phase 1: Data Ingestion (Session A)
Add 3 new FRED series to macro_ingestion worker, populate historical data.

### Phase 2: Dynamic Weights + Profile A (Session B)
Implement the dynamic weight amplification mechanism and new signal weight profile. New signals use `None` gracefully until data is available.

### Phase 3: Backtest Validation (Session C)
Backtest both weight profiles against 2007-2008, 2020, 2022 macro data in the hypertable.

**CRITICAL SEQUENCING:** Phase 2 must handle missing signals gracefully (they'll be `None` until Phase 1 ingestion runs). The existing renormalization logic already handles missing signals — when a signal is `None`, it's excluded from the signals list and weights are renormalized over available signals. Phase 2 code must follow this same pattern for the 3 new signals.

---

## Session A — Data Ingestion (3 New FRED Series)

**Branch:** `feat/regime-dynamic-weights`
**Scope:** Backend only — macro_ingestion worker + regime_service inputs

### 1. Add series to macro_ingestion worker

File: `backend/app/domains/wealth/workers/macro_ingestion.py`

Add these 3 series to the ingestion list (wherever the FRED series IDs are defined):

| Series ID | Name | Frequency | Category |
|---|---|---|---|
| `ICSA` | Initial Jobless Claims | Weekly | Employment leading |
| `TOTBKCR` | Total Bank Credit, All Commercial Banks | Weekly | Credit cycle |
| `PERMIT` | New Private Housing Units Authorized (Building Permits) | Monthly | Housing leading |

These series are free FRED data, same API as all existing series. The ingestion worker already handles weekly and monthly frequencies — no special handling needed.

### 2. Add staleness thresholds

File: `backend/quant_engine/regime_service.py`

Find `REGIME_SERIES_STALENESS` dict and add:

```python
"ICSA": 14,        # Weekly — stale after 2 weeks
"TOTBKCR": 14,     # Weekly — stale after 2 weeks
"PERMIT": 45,      # Monthly — stale after 45 days
```

### 3. Add computation helpers in regime_service.py

Add 3 new `_compute_*` async helpers near the existing ones (around `_compute_series_zscore`, `_compute_series_roc`):

```python
async def _compute_icsa_zscore(
    db: AsyncSession,
    *,
    as_of_date: date | None = None,
) -> float | None:
    """Z-score of 4-week MA of initial claims vs 52-week rolling stats.

    ICSA is weekly. Compute:
    1. 4-week moving average of ICSA (smooth weekly noise)
    2. Mean and stddev of the 4wk MA over the trailing 52 weeks
    3. Z-score = (current_4wk_ma - mean_52wk) / std_52wk
    """
    effective_date = as_of_date or date.today()

    stmt = (
        select(MacroData.obs_date, MacroData.value)
        .where(
            MacroData.series_id == "ICSA",
            MacroData.obs_date > effective_date - timedelta(days=400),
            MacroData.obs_date <= effective_date,
        )
        .order_by(MacroData.obs_date.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    if len(rows) < 8:  # Need at least 8 weeks for meaningful z-score
        return None

    values = [float(r.value) for r in rows]

    # 4-week moving average
    ma4 = []
    for i in range(3, len(values)):
        ma4.append(sum(values[i-3:i+1]) / 4.0)

    if len(ma4) < 26:  # Need at least 26 weeks of MA for stats
        return None

    current_ma = ma4[-1]
    # Use trailing 52 4wk-MA values (or all available if less)
    lookback = ma4[-52:] if len(ma4) >= 52 else ma4
    mean_val = sum(lookback) / len(lookback)
    variance = sum((x - mean_val) ** 2 for x in lookback) / len(lookback)
    std_val = variance ** 0.5

    if std_val < 1.0:  # Avoid division by near-zero
        return None

    return (current_ma - mean_val) / std_val


async def _compute_credit_impulse(
    db: AsyncSession,
    *,
    as_of_date: date | None = None,
) -> float | None:
    """Credit impulse: 6-month rate-of-change of total bank credit.

    Falling credit impulse (negative RoC) = credit contraction = stress.
    Uses TOTBKCR (Total Bank Credit, All Commercial Banks, Weekly).

    Returns percentage change over 6 months. Negative = contraction.
    """
    effective_date = as_of_date or date.today()

    # Get latest value
    stmt_latest = (
        select(MacroData.value)
        .where(
            MacroData.series_id == "TOTBKCR",
            MacroData.obs_date <= effective_date,
        )
        .order_by(MacroData.obs_date.desc())
        .limit(1)
    )
    result_latest = await db.execute(stmt_latest)
    latest = result_latest.scalar_one_or_none()
    if latest is None:
        return None

    # Get value ~6 months ago
    target_date = effective_date - timedelta(days=180)
    stmt_old = (
        select(MacroData.value)
        .where(
            MacroData.series_id == "TOTBKCR",
            MacroData.obs_date <= target_date,
        )
        .order_by(MacroData.obs_date.desc())
        .limit(1)
    )
    result_old = await db.execute(stmt_old)
    old = result_old.scalar_one_or_none()
    if old is None or float(old) == 0:
        return None

    return ((float(latest) - float(old)) / float(old)) * 100.0


async def _compute_permits_roc(
    db: AsyncSession,
    *,
    months: int = 6,
    as_of_date: date | None = None,
) -> float | None:
    """6-month rate-of-change of building permits (PERMIT).

    Falling permits = leading recession indicator (9-12 month lead).
    Returns percentage change. Negative = declining permits.
    """
    return await _compute_series_roc(
        db, "PERMIT", months=months, as_of_date=as_of_date,
    )
```

Note: `_compute_series_roc` already exists in the file — reuse it for PERMIT. ICSA and TOTBKCR need custom helpers because they require specific transformations (4-week MA for ICSA, 6-month credit impulse for TOTBKCR).

### 4. Extend `build_regime_inputs()` to include new signals

In `build_regime_inputs()` (line ~827), add computation of the 3 new signals. Find where the existing signals are computed (around the `_compute_series_zscore` and `_compute_series_roc` calls) and add:

```python
# ── Initial Jobless Claims Z-score ──
icsa_zscore = await _compute_icsa_zscore(db, as_of_date=effective_date)

# ── Credit Impulse ──
credit_impulse = await _compute_credit_impulse(db, as_of_date=effective_date)

# ── Building Permits 6m RoC ──
permits_roc = await _compute_permits_roc(db, as_of_date=effective_date)
```

Add to the return dict:

```python
return {
    # ... existing keys ...
    "icsa_zscore": icsa_zscore,
    "credit_impulse": credit_impulse,
    "permits_roc": permits_roc,
}
```

### 5. Add new kwargs to `classify_regime_multi_signal()`

Add 3 new optional parameters to the function signature:

```python
def classify_regime_multi_signal(
    # ... existing params ...
    icsa_zscore: float | None = None,
    credit_impulse: float | None = None,
    permits_roc: float | None = None,
) -> tuple[str, dict[str, str]]:
```

Add signal entries (using Profile A weights — Session B will make these configurable):

```python
# Initial Jobless Claims Z-score (8%): weekly frequency, leads Sahm by 4-8 weeks
if icsa_zscore is not None:
    s = _ramp(icsa_zscore, calm=0.5, panic=2.5)
    signals.append(("icsa", s, 0.08, f"ICSA_z={icsa_zscore:+.2f}\u03c3 (stress={s:.0f}/100)"))

# Credit Impulse (5%): 6m RoC of bank credit. Negative = contraction = stress.
# Inverted: we ramp on the negative side.
if credit_impulse is not None:
    s = _ramp(-credit_impulse, calm=-0.5, panic=2.0)
    signals.append(("credit_impulse", s, 0.05, f"CreditImpulse={credit_impulse:+.1f}% (stress={s:.0f}/100)"))

# Building Permits 6m RoC (4%): longest-lead recession indicator (9-12 months).
# Falling permits = stress. Inverted.
if permits_roc is not None:
    s = _ramp(-permits_roc, calm=-5.0, panic=20.0)
    signals.append(("permits", s, 0.04, f"Permits_\u03946m={permits_roc:+.1f}% (stress={s:.0f}/100)"))
```

### 6. Wire new signals through `get_current_regime()`

In `get_current_regime()` (line ~923), where `classify_regime_multi_signal` is called with `inputs.get(...)`, add:

```python
icsa_zscore=inputs.get("icsa_zscore"),
credit_impulse=inputs.get("credit_impulse"),
permits_roc=inputs.get("permits_roc"),
```

Similarly in `run_global_regime_detection()` in `risk_calc.py` — find where `classify_regime_multi_signal` is called and add the same 3 kwargs.

### 7. Run ingestion to populate historical data

After deploying the worker changes, run the macro ingestion worker to backfill historical data for the 3 new series:

```bash
python -m app.domains.wealth.workers.macro_ingestion
```

FRED API returns up to 10 years of history by default. This populates the `macro_data` hypertable with ICSA, TOTBKCR, and PERMIT data.

### 8. Tests

Add tests for the 3 new computation helpers:

File: `backend/tests/quant_engine/test_regime_new_signals.py`

```python
"""Tests for new regime signals: ICSA z-score, credit impulse, building permits."""

import pytest
from quant_engine.regime_service import classify_regime_multi_signal


class TestIcsaSignal:
    def test_calm_icsa_produces_low_stress(self):
        """ICSA z-score below calm threshold produces zero stress."""
        _, reasons = classify_regime_multi_signal(
            vix=20.0, icsa_zscore=0.3,
        )
        assert "icsa" not in reasons or "stress=0" in reasons.get("icsa", "")

    def test_extreme_icsa_produces_high_stress(self):
        """ICSA z-score at panic level produces high stress."""
        _, reasons = classify_regime_multi_signal(
            vix=20.0, icsa_zscore=3.0,
        )
        assert "icsa" in {k for k in reasons if k.startswith("icsa") or "ICSA" in reasons.get(k, "")}


class TestCreditImpulseSignal:
    def test_positive_impulse_low_stress(self):
        """Positive credit growth produces low stress."""
        _, reasons = classify_regime_multi_signal(
            vix=20.0, credit_impulse=2.0,
        )
        # Positive impulse → inverted ramp → low stress
        assert any("CreditImpulse" in v and "stress=0" in v for v in reasons.values())

    def test_negative_impulse_high_stress(self):
        """Credit contraction produces high stress."""
        _, reasons = classify_regime_multi_signal(
            vix=20.0, credit_impulse=-3.0,
        )
        assert any("CreditImpulse" in v for v in reasons.values())


class TestPermitsSignal:
    def test_growing_permits_low_stress(self):
        """Rising building permits produce low stress."""
        _, reasons = classify_regime_multi_signal(
            vix=20.0, permits_roc=10.0,
        )
        assert any("Permits" in v and "stress=0" in v for v in reasons.values())

    def test_falling_permits_high_stress(self):
        """Sharply falling permits produce high stress."""
        _, reasons = classify_regime_multi_signal(
            vix=20.0, permits_roc=-25.0,
        )
        assert any("Permits" in v for v in reasons.values())
```

### Verification (Session A)

1. `make test` passes.
2. `make lint` passes (on changed files).
3. The 3 new series appear in `macro_data` after running ingestion.
4. `build_regime_inputs()` returns non-None values for `icsa_zscore`, `credit_impulse`, `permits_roc`.
5. `classify_regime_multi_signal()` accepts and processes the 3 new kwargs.
6. When new signals are `None` (data not yet ingested), behavior is identical to before — they're simply excluded from the signals list.

---

## Session B — Dynamic Weight Amplification + Profile A

**Branch:** same `feat/regime-dynamic-weights`
**Depends on:** Session A committed
**Scope:** `regime_service.py` only — mechanism + weight rebalance

### 1. Add `_amplify_weights()` helper

Add this function near the top of `regime_service.py`, after the existing helpers (`_ramp`, `_validate_plausibility`):

```python
def _amplify_weights(
    signals: list[tuple[str, float, float, str]],
    alpha: float = 2.0,
    gamma: float = 2.0,
    w_max: float = 0.35,
) -> list[tuple[str, float, float, str]]:
    """Compute dynamic weights based on signal amplitude.

    Extreme signals get amplified weights via convex scaling.
    Calm signals are nearly transparent to the amplification.

    Formula: w_eff_i = w_base_i * (1 + alpha * (s_i / 100)^gamma)
    Then renormalize to unit sum, cap at w_max with redistribution.

    Args:
        signals: List of (label, score, weight, reason) tuples.
        alpha: Max amplification multiplier. 2.0 means a maxed signal
               gets 3x its base weight before renormalization.
        gamma: Convexity exponent. 2.0 (quadratic) means score=50 gets
               25% of max amplification, score=80 gets 64%.
        w_max: Hard cap on any single signal's final weight. Prevents
               single-factor tyranny.

    Returns:
        New signals list with adjusted weights summing to ~1.0.
    """
    if not signals:
        return signals

    # Step 1: amplify
    amplified: list[tuple[str, float, float, str]] = []
    for label, score, weight, reason in signals:
        amp = weight * (1.0 + alpha * (score / 100.0) ** gamma)
        amplified.append((label, score, amp, reason))

    # Step 2: normalize to unit sum
    total = sum(w for _, _, w, _ in amplified)
    if total <= 0:
        return signals

    normalized = [
        (label, score, w / total, reason)
        for label, score, w, reason in amplified
    ]

    # Step 3: enforce w_max cap with redistribution
    for _ in range(5):  # Max 5 iterations to converge
        excess = 0.0
        uncapped_total = 0.0
        has_capped = False
        result: list[tuple[str, float, float, str]] = []

        for label, score, w, reason in normalized:
            if w > w_max:
                excess += w - w_max
                result.append((label, score, w_max, reason))
                has_capped = True
            else:
                uncapped_total += w
                result.append((label, score, w, reason))

        if not has_capped or excess <= 0 or uncapped_total <= 0:
            normalized = result
            break

        # Redistribute excess proportionally among uncapped signals
        normalized = [
            (
                label, score,
                w + (excess * w / uncapped_total) if w < w_max else w,
                reason,
            )
            for label, score, w, reason in result
        ]

    return normalized
```

### 2. Update base weights to Profile A (40/60)

In `classify_regime_multi_signal()`, update the weight values in each `signals.append(...)` call:

| Signal | Old weight | New weight (Profile A) |
|---|---|---|
| VIX | 0.15 | **0.10** |
| HY OAS | 0.15 | **0.12** |
| BAA-10Y | 0.10 | **0.05** |
| Yield Curve | 0.10 | **0.05** |
| DXY | 0.05 | **0.08** |
| Energy Shock | 0.10 | **0.12** |
| CFNAI | 0.15 | **0.18** |
| Sahm Rule | 0.10 | **0.08** |
| Fed Funds ROC | 0.05 | **0.05** |
| ICSA (new) | — | **0.08** |
| Credit Impulse (new) | — | **0.05** |
| Building Permits (new) | — | **0.04** |

**Sum = 1.00** (verify this).

### 3. Replace static composite with dynamic composite

In `classify_regime_multi_signal()`, find the composite score computation (around line 279-282 after the prompt's regime unification changes). Replace:

```python
# CURRENT (static weighted sum with renormalization):
raw_score = sum(s * w for _, s, w, _ in signals)
weight_sum = sum(w for _, _, w, _ in signals)
stress_score = raw_score / weight_sum if weight_sum > 0 else 50.0
```

With:

```python
# Step 1: renormalize base weights for available signals
weight_sum = sum(w for _, _, w, _ in signals)
if weight_sum > 0 and abs(weight_sum - 1.0) > 0.001:
    signals = [(l, s, w / weight_sum, r) for l, s, w, r in signals]

# Step 2: resolve amplification config
amp_config: dict[str, Any] = {}
if config:
    amp_config = config.get("regime_amplification", {})
amp_alpha = float(amp_config.get("alpha", 2.0))
amp_gamma = float(amp_config.get("gamma", 2.0))
amp_w_max = float(amp_config.get("w_max", 0.35))

# Step 3: apply dynamic weight amplification
base_signals = list(signals)  # snapshot before amplification
signals = _amplify_weights(signals, alpha=amp_alpha, gamma=amp_gamma, w_max=amp_w_max)

# Step 4: log weight changes for audit trail
for (label, _, w_final, _), (_, _, w_base, _) in zip(signals, base_signals):
    if abs(w_final - w_base) > 0.005:
        reasons[f"w_dyn_{label}"] = f"{w_base:.3f}\u2192{w_final:.3f}"

reasons["amplification"] = f"alpha={amp_alpha}, gamma={amp_gamma}, w_max={amp_w_max}"

# Step 5: compute composite
stress_score = sum(s * w for _, s, w, _ in signals)
```

Note: the `reasons` dict already exists in the function. The `config` parameter already exists. No signature changes needed for this part.

### 4. ConfigService integration

The amplification parameters are configurable per-org via the existing config mechanism. The default values (alpha=2.0, gamma=2.0, w_max=0.35) are used when no config override exists.

Config path: `ConfigService.get("liquid_funds", "calibration", org_id)` → `config["regime_amplification"]`.

Example YAML seed (for `calibration/` seed data — NOT used at runtime, just documentation):

```yaml
regime_amplification:
  alpha: 2.0      # max amplification factor (2.0 = up to 3x base)
  gamma: 2.0      # convexity exponent (2.0 = quadratic)
  w_max: 0.35     # hard cap per signal (35%)
```

### 5. Update `signal_details` in snapshot

The `signal_details` dict persisted in `macro_regime_snapshot` should include the effective weights so the frontend can display them. The existing `reasons` dict already captures this via the `w_dyn_*` keys and the `amplification` key added above. No additional changes needed — the snapshot persistence in `run_global_regime_detection()` already writes the full `reasons` dict to `signal_details`.

### 6. Tests

File: `backend/tests/quant_engine/test_regime_dynamic_weights.py`

```python
"""Tests for dynamic weight amplification in regime classification."""

import pytest
from quant_engine.regime_service import _amplify_weights, classify_regime_multi_signal


class TestAmplifyWeights:
    def test_calm_signals_unchanged(self):
        """When all signals are calm, weights barely change."""
        signals = [
            ("a", 5.0, 0.5, ""),
            ("b", 3.0, 0.5, ""),
        ]
        result = _amplify_weights(signals)
        w_a = next(w for l, _, w, _ in result if l == "a")
        w_b = next(w for l, _, w, _ in result if l == "b")
        # Both calm → nearly equal amplification → weights ~unchanged
        assert abs(w_a - 0.5) < 0.02
        assert abs(w_b - 0.5) < 0.02

    def test_extreme_signal_amplified(self):
        """A maxed-out signal gets amplified weight."""
        signals = [
            ("extreme", 100.0, 0.10, ""),
            ("calm1", 5.0, 0.30, ""),
            ("calm2", 5.0, 0.30, ""),
            ("calm3", 5.0, 0.30, ""),
        ]
        result = _amplify_weights(signals)
        w_extreme = next(w for l, _, w, _ in result if l == "extreme")
        # 0.10 * 3.0 = 0.30 before renorm; after renorm ~0.24
        assert w_extreme > 0.20  # significantly above base 0.10

    def test_w_max_cap_enforced(self):
        """No signal exceeds w_max after amplification."""
        signals = [
            ("extreme", 100.0, 0.30, ""),  # 0.30 * 3.0 = 0.90 pre-norm
            ("calm", 5.0, 0.70, ""),
        ]
        result = _amplify_weights(signals, w_max=0.35)
        w_extreme = next(w for l, _, w, _ in result if l == "extreme")
        assert w_extreme <= 0.35 + 0.001

    def test_weights_sum_to_one(self):
        """Weights always sum to ~1.0 after amplification."""
        signals = [
            ("a", 100.0, 0.20, ""),
            ("b", 50.0, 0.30, ""),
            ("c", 10.0, 0.25, ""),
            ("d", 0.0, 0.25, ""),
        ]
        result = _amplify_weights(signals)
        total = sum(w for _, _, w, _ in result)
        assert abs(total - 1.0) < 0.001

    def test_empty_signals(self):
        """Empty signal list returns empty."""
        assert _amplify_weights([]) == []

    def test_single_signal(self):
        """Single signal gets weight 1.0 regardless."""
        signals = [("only", 80.0, 0.15, "")]
        result = _amplify_weights(signals)
        assert len(result) == 1
        assert abs(result[0][2] - 1.0) < 0.001


class TestProfileAWeights:
    def test_energy_shock_crosses_risk_off(self):
        """With Profile A weights + dynamic amplification,
        energy=100 and calm markets should produce RISK_OFF."""
        regime, reasons = classify_regime_multi_signal(
            vix=19.5,
            hy_oas=2.90,
            baa_spread=1.73,
            energy_shock=100.0,
            cfnai=-0.11,
            sahm_rule=0.20,
            fed_funds_delta_6m=-0.46,
            dxy_zscore=0.03,
        )
        # With dynamic weights, energy at 100/100 should push
        # composite above 25 → RISK_OFF
        assert regime in ("RISK_OFF", "CRISIS")

    def test_all_calm_still_risk_on(self):
        """When all signals are calm, dynamic weights don't change regime."""
        regime, _ = classify_regime_multi_signal(
            vix=15.0,
            hy_oas=2.0,
            baa_spread=1.0,
            energy_shock=5.0,
            cfnai=0.10,
            sahm_rule=0.05,
            fed_funds_delta_6m=0.0,
            dxy_zscore=0.0,
        )
        assert regime == "RISK_ON"

    def test_multi_extreme_produces_crisis(self):
        """Multiple extreme signals should produce CRISIS."""
        regime, _ = classify_regime_multi_signal(
            vix=45.0,
            hy_oas=8.0,
            baa_spread=3.0,
            energy_shock=100.0,
            cfnai=-0.80,
            sahm_rule=0.60,
            fed_funds_delta_6m=2.0,
            dxy_zscore=2.5,
        )
        assert regime == "CRISIS"
```

### Verification (Session B)

1. `make test` passes (including new test file).
2. `make lint` passes.
3. Run `regime_detection` worker → snapshot shows dynamic weight audit trail in `signal_details`:
   - `w_dyn_energy_shock: "0.126→0.258"` (or similar)
   - `amplification: "alpha=2.0, gamma=2.0, w_max=0.35"`
4. With current data (energy=100, VIX=19.5), regime should be **RISK_OFF** (not RISK_ON).
5. With all-calm data, regime remains RISK_ON (dynamic weights are transparent).

---

## Session C — Backtest Validation

**Branch:** same `feat/regime-dynamic-weights`
**Depends on:** Sessions A + B committed, macro_data populated with historical ICSA/TOTBKCR/PERMIT
**Scope:** New backtest script + analysis

### 1. Create backtest script

File: `backend/scripts/backtest_regime_weights.py`

This script should:

1. Query `macro_data` for historical values of all regime signals
2. For each month in the backtest period, call `classify_regime_multi_signal()` with:
   - **Static weights** (old 55/45 split, no dynamic amplification)
   - **Profile A** (40/60 split, with dynamic amplification)
   - **Profile B** (25/75 split, with dynamic amplification)
3. Output a CSV or structured JSON with columns:
   - `date`, `static_regime`, `static_score`, `profile_a_regime`, `profile_a_score`, `profile_b_regime`, `profile_b_score`
4. Highlight regime transitions and divergences between profiles

### 2. Backtest periods

| Period | Event | Key Signal | Expected Behavior |
|---|---|---|---|
| 2007-06 to 2009-06 | GFC | HY OAS blowout, oil spike then crash, CFNAI collapse | All profiles should detect CRISIS by Q4 2007 |
| 2019-09 to 2020-06 | COVID | VIX spike, credit blowout, Sahm spike | Market-heavy profiles detect faster |
| 2022-01 to 2022-12 | Ukraine/Energy | WTI +60%, moderate VIX, credit widening | **Discriminating test** — Profile A/B should detect RISK_OFF earlier than static |
| 2014-06 to 2015-06 | Oil crash | WTI -60%, VIX calm, economy OK | **False-positive test** — falling oil shouldn't trigger stress (current energy shock is upward-only) |

### 3. Analysis output

For each period, report:
- **Lead time**: how many weeks before NBER recession onset (or market drawdown >10%) did each profile trigger RISK_OFF or CRISIS?
- **False positives**: how many months of RISK_OFF/CRISIS occurred when no recession or >10% drawdown followed within 6 months?
- **Regime accuracy**: what was the regime at the market trough?

### 4. Calibration adjustment (if needed)

If backtesting reveals:
- Profile A too aggressive (many false positives) → lower alpha to 1.5 or raise gamma to 2.5
- Profile A too conservative (misses 2022 Ukraine) → raise alpha to 2.5 or lower gamma to 1.5
- Thresholds need adjustment → propose new thresholds but DO NOT change them without separate approval

Document findings in `docs/reference/regime-backtest-results.md`.

### Verification (Session C)

1. Backtest script runs successfully against historical data in `macro_data`.
2. Profile A detects 2022 Ukraine energy crisis as RISK_OFF (static model shows RISK_ON).
3. No significant increase in false positives for Profile A vs static.
4. Results documented in `docs/reference/regime-backtest-results.md`.
5. Final parameter recommendations (alpha, gamma, w_max) documented.

---

## Constraints

- Do NOT change regime thresholds (25/50) — calibrate weights/amplification against them.
- Do NOT change `_ramp()` helper — it's used across the codebase.
- Do NOT change `macro_regime_snapshot` table schema — the `signal_details` JSONB column accommodates the new audit data.
- Do NOT change `GET /macro/regime` or `GET /allocation/regime` routes — they read from the snapshot.
- Do NOT change `run_global_regime_detection()` worker interface — only the internal call to `classify_regime_multi_signal` gains new kwargs.
- The 3 new signals must be **None-safe** — when data is missing, they're excluded from the signals list and weights renormalize over available signals. This is the existing pattern.
- All changes must pass `make check` (lint + typecheck + test).

## Anti-Patterns

- Do NOT hardcode weight profiles in the function body. The base weights in the `signals.append()` calls ARE the Profile A defaults. Profile B can be activated via ConfigService override of the base weights — but this is a future config feature, not part of this PR.
- Do NOT add a separate "weight profile" parameter to `classify_regime_multi_signal()`. The weights are in the code (defaults) and overridable via config. Keep it simple.
- Do NOT create a separate "dynamic regime" function. The dynamic amplification is an enhancement of the existing function, not a parallel path.
- Do NOT change the `RegimeResult` or `RegimeRead` schemas. The dynamic weights are internal to the computation; the output (regime label + stress score + signal details) is unchanged.
- Do NOT run the backtest in Session B. Backtest requires historical data that needs ingestion (Session A) to have run first. Session C is explicitly for backtesting.
