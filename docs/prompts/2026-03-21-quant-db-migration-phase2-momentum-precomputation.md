# Phase 2 — Momentum Pre-computation in risk_calc Worker

**Status:** Ready
**Estimated scope:** ~150 lines changed + migration
**Risk:** Low (additive — new columns, worker extension, route simplification)

---

## Context

The `GET /funds/scoring` route (in `backend/app/domains/wealth/routes/funds.py`, lines 56-181) currently computes momentum signals **in-request**:

1. Fetches latest 50 NAV points per fund via window function query
2. Calls `compute_momentum_signals_talib(close)` → RSI(14), Bollinger(20,2σ), momentum_score
3. Calls `compute_flow_momentum(close, net_flows)` → OBV slope
4. Calls `normalize_flow_momentum(slope)` → 0-100 score
5. Blends: `0.5 * nav_score + 0.5 * flow_score`

With 500+ instruments, this adds 5+ seconds to the route. The `risk_calc` worker already runs daily, computing CVaR, Sharpe, drift, etc. Momentum should be pre-computed there.

**Goal:** Add momentum columns to `FundRiskMetrics`, compute them in `risk_calc` worker, simplify the scoring route to a pure DB read.

---

## Step 1: Migration — Add Momentum Columns to fund_risk_metrics

Create migration `backend/app/core/db/migrations/versions/0035_fund_risk_metrics_momentum.py`:

```python
"""Add momentum signal columns to fund_risk_metrics."""

from alembic import op
import sqlalchemy as sa

revision = "0035"
down_revision = "0034"  # verify current head
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("fund_risk_metrics", sa.Column("rsi_14", sa.Numeric(5, 2), nullable=True))
    op.add_column("fund_risk_metrics", sa.Column("bb_position", sa.Numeric(5, 2), nullable=True))
    op.add_column("fund_risk_metrics", sa.Column("nav_momentum_score", sa.Numeric(5, 2), nullable=True))
    op.add_column("fund_risk_metrics", sa.Column("flow_momentum_score", sa.Numeric(5, 2), nullable=True))
    op.add_column("fund_risk_metrics", sa.Column("blended_momentum_score", sa.Numeric(5, 2), nullable=True))

def downgrade() -> None:
    op.drop_column("fund_risk_metrics", "blended_momentum_score")
    op.drop_column("fund_risk_metrics", "flow_momentum_score")
    op.drop_column("fund_risk_metrics", "nav_momentum_score")
    op.drop_column("fund_risk_metrics", "bb_position")
    op.drop_column("fund_risk_metrics", "rsi_14")
```

## Step 2: Update FundRiskMetrics Model

File: `backend/app/domains/wealth/models/risk.py`

Add the new columns to the ORM model:

```python
# Momentum signals (pre-computed by risk_calc worker)
rsi_14: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
bb_position: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
nav_momentum_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
flow_momentum_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
blended_momentum_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
```

## Step 3: Compute Momentum in risk_calc Worker

File: `backend/app/domains/wealth/workers/risk_calc.py`

In the `_compute_metrics_from_returns()` function (currently lines 225-271), add momentum computation AFTER the existing risk metrics:

```python
# At the top of the file, add imports:
from quant_engine.talib_momentum_service import (
    compute_momentum_signals_talib,
    compute_flow_momentum,
    normalize_flow_momentum,
)
```

The challenge: `compute_momentum_signals_talib()` needs NAV prices (not returns), and `compute_flow_momentum()` needs AUM data. The current batch fetch only gets returns.

**Approach:** Add a new batch fetch for NAV prices + AUM in `run_risk_calc()`:

```python
async def _batch_fetch_nav_prices(
    db: AsyncSession,
    fund_ids: list[uuid.UUID],
    as_of_date: date,
    lookback_days: int = 80,  # ~50 trading days + buffer for weekends
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Batch-fetch latest NAV prices and AUM for momentum computation.

    Returns dict mapping fund_id (str) → (nav_prices, aum_values) as numpy arrays.
    """
    start_date = as_of_date - timedelta(days=lookback_days)
    stmt = (
        select(
            NavTimeseries.instrument_id,
            NavTimeseries.nav,
            NavTimeseries.aum_usd,
        )
        .where(
            NavTimeseries.instrument_id.in_(fund_ids),
            NavTimeseries.nav_date >= start_date,
            NavTimeseries.nav_date <= as_of_date,
            NavTimeseries.nav.is_not(None),
        )
        .order_by(NavTimeseries.instrument_id, NavTimeseries.nav_date)
    )
    result = await db.execute(stmt)

    by_fund: dict[str, tuple[list[float], list[float]]] = {}
    for row_id, nav, aum in result.all():
        fid = str(row_id)
        if fid not in by_fund:
            by_fund[fid] = ([], [])
        by_fund[fid][0].append(float(nav))
        by_fund[fid][1].append(float(aum) if aum is not None else 0.0)

    return {
        fid: (np.array(navs[-50:]), np.array(aums[-50:]))
        for fid, (navs, aums) in by_fund.items()
    }
```

Then in `run_risk_calc()`, after Pass 1 (compute standard metrics), add:

```python
# Pass 1.5: Compute momentum signals from NAV prices (single batch query)
nav_price_map = await _batch_fetch_nav_prices(db, all_fund_ids, eval_date)

for fund, metrics in computed:
    fid_str = str(fund.fund_id)
    nav_data = nav_price_map.get(fid_str)
    if nav_data is None or len(nav_data[0]) < 30:
        # Insufficient data for momentum
        metrics["rsi_14"] = None
        metrics["bb_position"] = None
        metrics["nav_momentum_score"] = None
        metrics["flow_momentum_score"] = None
        metrics["blended_momentum_score"] = None
        continue

    close, aum = nav_data
    signals = compute_momentum_signals_talib(close)
    nav_score = signals.get("momentum_score", 50.0)

    metrics["rsi_14"] = _round_or_none(signals.get("rsi_norm", None) and signals["rsi_norm"] * 100, 2)
    metrics["bb_position"] = _round_or_none(signals.get("bb_pos", None) and signals["bb_pos"] * 100, 2)
    metrics["nav_momentum_score"] = _round_or_none(nav_score, 2)

    # Flow momentum (OBV-based)
    if aum.any():
        slope = compute_flow_momentum(close, aum)
        flow_score = normalize_flow_momentum(slope)
        metrics["flow_momentum_score"] = _round_or_none(flow_score, 2)
        metrics["blended_momentum_score"] = _round_or_none(0.5 * nav_score + 0.5 * flow_score, 2)
    else:
        metrics["flow_momentum_score"] = None
        metrics["blended_momentum_score"] = _round_or_none(nav_score, 2)
```

## Step 4: Simplify Scoring Route

File: `backend/app/domains/wealth/routes/funds.py`

The scoring endpoint (lines ~95-152) currently has a conditional block `if settings.feature_momentum_signals:` that fetches NAV and computes momentum. Replace this entire block with a simple read from `FundRiskMetrics`:

```python
# BEFORE (lines 95-152): ~60 lines of NAV fetch + momentum computation

# AFTER: ~3 lines
for fund in funds:
    fid = fund.fund_id
    risk = risk_map.get(fid)
    momentum = float(risk.blended_momentum_score) if risk and risk.blended_momentum_score else 50.0
    momentum_map[fid] = momentum
```

Remove the `feature_momentum_signals` feature flag check — momentum is always available from pre-computation.

Remove imports: `compute_momentum_signals_talib`, `compute_flow_momentum`, `normalize_flow_momentum` from the route file.

## Step 5: Update FundScoreRead Schema

File: `backend/app/domains/wealth/schemas/risk.py`

If `FundScoreRead` exposes momentum components, ensure it maps from the pre-computed columns.

## Step 6: Tests

- `make test ARGS="-k risk_calc"` — verify worker computes momentum
- `make test ARGS="-k scoring"` — verify route reads pre-computed values
- Add test: `test_momentum_precomputed_in_risk_metrics` — seed NAV data, run worker, verify columns populated

## Validation

```bash
make check  # All tests pass
```

After running `risk_calc` worker, the scoring route should respond in <100ms instead of 5+ seconds.

---

## Files to Modify

| File | Action |
|---|---|
| `backend/app/core/db/migrations/versions/0035_*.py` | New migration — add 5 momentum columns |
| `backend/app/domains/wealth/models/risk.py` | Add 5 Mapped columns |
| `backend/app/domains/wealth/workers/risk_calc.py` | Add `_batch_fetch_nav_prices()`, compute momentum in Pass 1.5 |
| `backend/app/domains/wealth/routes/funds.py` | Remove in-request momentum computation, read from risk_map |
| `backend/app/domains/wealth/schemas/risk.py` | Verify schema includes momentum fields |
