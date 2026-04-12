# Alternatives & Cash/MMF Scoring Engine -- Plano Completo

> **Problema de credibilidade:** O scoring model equity-centrico (6 componentes: Sharpe, return consistency, drawdown, IR, flows, fee) produz resultados absurdos para alternatives e cash. Um money market fund com vol ~0.5% produz Sharpe > 10 (numericamente instavel), e e descartado pelo guard `MIN_ANNUALIZED_VOL = 0.01` no screener -- ou seja, **zero Layer 3 score** para MMFs. Um REIT fund com correlacao negativa ao equity (diversification alpha) pontua mal porque drawdown_control mede drawdown absoluto, nao relativo ao benchmark VNQ. Para portfolios institucionais com 5-15% em alternatives e 2-5% em cash, isso contamina o ELITE ranking e o Portfolio Builder.

> [!IMPORTANT]
> **Arquitetura DB-First:** Igual ao FI plan. Nenhum calculo novo roda em user-facing request. Tudo pre-computa no worker `global_risk_metrics` (lock 900_071) e persiste em `fund_risk_metrics`. Rotas leem O(1). Scoring dispatch via `scoring_model` column.

---

## Taxonomia de Asset Classes e Dispatch

### Hierarquia de dispatch

```
asset_class (Instrument.asset_class)
  |
  +-- "equity"          --> scoring_model = "equity"     (existing)
  +-- "fixed_income"    --> scoring_model = "fixed_income" (FI plan)
  +-- "alternatives"    --> scoring_model = "alternatives"
  |     sub-dispatch by block_id:
  |       alt_real_estate  --> profile "reit"
  |       alt_commodities  --> profile "commodity"
  |       alt_gold         --> profile "gold"
  |       (unmatched)      --> profile "generic_alt"
  +-- "cash"            --> scoring_model = "cash"
  +-- "multi_asset"     --> scoring_model = "equity" (fallback -- multi-asset is closest to equity)
  +-- (other)           --> scoring_model = "equity" (safe fallback)
```

### Sub-strategy mapping (Alternatives)

O dispatch usa `block_id` do `block_mapping.py` (ja existente) como chave de profile. Nao cria novos scoring_model values para cada sub-estrategia -- mantem `scoring_model = "alternatives"` com config-driven differentiation via `ConfigService`.

Mapeamento strategy_label -> block_id (ja existe em `block_mapping.py`):

| strategy_label | block_id | Alt profile |
|---|---|---|
| Real Estate, Real Estate Fund | alt_real_estate | reit |
| Commodities Broad Basket, Natural Resources, Infrastructure | alt_commodities | commodity |
| Precious Metals | alt_gold | gold |
| Long/Short Equity, Multi-Strategy, Managed Futures | (need new blocks) | hedge |

**Gap identificado:** Hedge fund strategy_labels (Long/Short Equity, Multi-Strategy) atualmente mapeiam para `na_equity_large` no block_mapping -- INCORRETO para scoring. Precisam de novo block `alt_hedge_fund` com benchmark HFRI (proxy: HDG ou QAI ETF). Managed Futures precisa de `alt_managed_futures` com benchmark DBMF.

**Acao:** Adicionar ao block_mapping.py e blocks.yaml:

```yaml
alt_hedge_fund:
  geography: global
  asset_class: alternatives
  display_name: "Hedge Funds / Multi-Strategy"
  benchmark_ticker: QAI
  description: "Alternative multi-strategy exposure"

alt_managed_futures:
  geography: global
  asset_class: alternatives
  display_name: "Managed Futures / CTA"
  benchmark_ticker: DBMF
  description: "Trend-following CTA strategies"
```

Atualizar strategy_label mapping (ADDITIVE -- keep existing equity blocks for funds that appear in both):

```python
"Long/Short Equity": ["alt_hedge_fund", "na_equity_large"],  # Both: some are equity-style, some are alt
"Multi-Strategy": ["alt_hedge_fund"],
"Market Neutral": ["alt_hedge_fund"],
"Managed Futures": ["alt_managed_futures"],
```

**IMPORTANTE:** O `asset_class` na `instruments_universe` e o que determina o scoring model, NAO o block_mapping. Um fundo com `asset_class="equity"` e `strategy_label="Long/Short Equity"` sera scored pelo equity model. Um fundo com `asset_class="alternatives"` e `strategy_label="Long/Short Equity"` sera scored pelo alt model. O block mapping e para candidate discovery (portfolio builder), nao para scoring dispatch.

---

## Fase 1 -- Cash/MMF Scoring Model (Prioridade ALTA)

### Motivacao

Cash/MMF scoring e a correcao mais urgente: o `MIN_ANNUALIZED_VOL = 0.01` guard descarta MMFs do Layer 3 do screener. Alem disso, ja temos dados ricos em `sec_money_market_funds` (WAM, yield, liquidity) e `sec_mmf_metrics` (daily metrics) que NAO estao sendo usados no scoring.

### 1.1 Cash Scoring Components

5 componentes (sum = 1.0):

| Componente | Peso | Metrica | Fonte | Normalizacao |
|---|---|---|---|---|
| `yield_vs_risk_free` | 0.30 | `(seven_day_net_yield - DFF) / DFF` | sec_mmf_metrics.seven_day_net_yield vs macro_data.DFF | Range: -0.20 to +0.20. Score 100 = fund yields 20% more than fed funds. Score 50 = matches exactly. Score 0 = yields 20% less. |
| `nav_stability` | 0.25 | `1 - abs(shadow_nav - 1.0) * 1000` | Computed: if `seeks_stable_nav`, use `stable_nav_price` from sec_money_market_funds. Else compute vol from daily NAV. | Range: score 100 = perfect $1.00. Score 0 = deviation >= 0.1% ($0.999 or $1.001). This is the "break the buck" metric. |
| `liquidity_quality` | 0.20 | `pct_weekly_liquid_latest` | sec_money_market_funds | Range: 30% (regulatory min) to 100%. Score 0 at 30%, score 100 at 100%. SEC Rule 2a-7 requires 30% weekly liquid. |
| `maturity_discipline` | 0.15 | `1 - (WAM / 60)` | sec_money_market_funds.weighted_avg_maturity | Range: 0 to 60 days. Score 100 = WAM 0 (all overnight). Score 0 = WAM 60 (regulatory max). Lower WAM = less interest rate risk = better for cash vehicle. |
| `fee_efficiency` | 0.10 | Same formula as equity/FI | expense_ratio_pct from XBRL enrichment | Same normalization. More impactful for cash: at 5% yield, 0.50% ER eats 10% of return. |

**Formulas:**

```python
def _compute_cash_score(
    cash_metrics: CashMetrics,
    config: dict[str, Any] | None,
    expense_ratio_pct: float | None,
    peer_medians: dict[str, float] | None,
) -> tuple[float, dict[str, float]]:
    pm = peer_medians or {}
    components: dict[str, float] = {}

    # yield_vs_risk_free: relative yield advantage over fed funds
    # seven_day_net_yield is in percent (e.g., 5.25).
    # fed_funds_rate is in percent (e.g., 5.33).
    if cash_metrics.seven_day_net_yield is not None and cash_metrics.fed_funds_rate is not None:
        ffr = cash_metrics.fed_funds_rate
        if ffr > 0:
            relative_yield = (cash_metrics.seven_day_net_yield - ffr) / ffr
        else:
            relative_yield = 0.10 if cash_metrics.seven_day_net_yield > 0 else 0.0
        components["yield_vs_risk_free"] = _normalize(relative_yield, -0.20, 0.20, pm.get("yield_vs_risk_free"))
    else:
        components["yield_vs_risk_free"] = pm.get("yield_vs_risk_free", 45.0) - 5.0

    # nav_stability: deviation from $1.00 par
    if cash_metrics.nav_per_share is not None:
        deviation = abs(cash_metrics.nav_per_share - 1.0)
        stability = max(0.0, 1.0 - deviation * 1000)  # 0.001 deviation = 0 score
        components["nav_stability"] = stability * 100
    else:
        components["nav_stability"] = pm.get("nav_stability", 45.0) - 5.0

    # liquidity_quality: weekly liquid assets %
    if cash_metrics.pct_weekly_liquid is not None:
        # Range 30% (regulatory min) to 100%
        components["liquidity_quality"] = _normalize(
            cash_metrics.pct_weekly_liquid, 30.0, 100.0, pm.get("liquidity_quality"),
        )
    else:
        components["liquidity_quality"] = pm.get("liquidity_quality", 45.0) - 5.0

    # maturity_discipline: lower WAM = better
    if cash_metrics.weighted_avg_maturity is not None:
        # 0 days = 100, 60 days = 0. Inverted scale.
        wam_score = max(0.0, (1.0 - cash_metrics.weighted_avg_maturity / 60.0)) * 100
        components["maturity_discipline"] = wam_score
    else:
        components["maturity_discipline"] = pm.get("maturity_discipline", 45.0) - 5.0

    # fee_efficiency: shared formula
    components["fee_efficiency"] = _compute_fee_efficiency(expense_ratio_pct, pm)

    weights = resolve_scoring_weights(config, asset_class="cash")
    score = sum(components.get(k, 50.0) * w for k, w in weights.items())
    return round(score, 2), {k: round(v, 2) for k, v in components.items()}
```

### 1.2 New Protocol and Defaults

```python
class CashMetrics(Protocol):
    """Protocol for cash/MMF metrics -- satisfied by FundRiskMetrics ORM or adapter."""
    seven_day_net_yield: Decimal | float | None
    fed_funds_rate: Decimal | float | None
    nav_per_share: Decimal | float | None
    pct_weekly_liquid: Decimal | float | None
    weighted_avg_maturity: int | float | None

_DEFAULT_CASH_SCORING_WEIGHTS: dict[str, float] = {
    "yield_vs_risk_free": 0.30,
    "nav_stability": 0.25,
    "liquidity_quality": 0.20,
    "maturity_discipline": 0.15,
    "fee_efficiency": 0.10,
}
```

### 1.3 New fund_risk_metrics Columns (Cash)

```sql
ALTER TABLE fund_risk_metrics
    ADD COLUMN seven_day_net_yield NUMERIC(8, 4),
    ADD COLUMN fed_funds_rate_at_calc NUMERIC(8, 4),
    ADD COLUMN nav_per_share NUMERIC(12, 6),
    ADD COLUMN pct_weekly_liquid NUMERIC(8, 4),
    ADD COLUMN weighted_avg_maturity INTEGER;
```

- `seven_day_net_yield`: From sec_mmf_metrics JOIN on class_id. 7-day net yield in percent (e.g., 5.25).
- `fed_funds_rate_at_calc`: DFF from macro_data at calc_date. Stored for audit trail -- lets us reconstruct the relative yield signal.
- `nav_per_share`: From sec_money_market_funds.stable_nav_price (for stable NAV funds) or computed from nav_timeseries.
- `pct_weekly_liquid`: From sec_money_market_funds.pct_weekly_liquid_latest.
- `weighted_avg_maturity`: From sec_money_market_funds.weighted_avg_maturity. Days.

### 1.4 Worker Integration (Cash Pass)

New pass in `risk_calc.py` global worker, inserted before scoring:

```python
# Pass 1.9: Cash/MMF analytics
# Only for funds with asset_class = 'cash' or scoring_model = 'cash'
cash_fund_ids = [str(f.instrument_id) for f, _ in computed if f.asset_class == "cash"]
if cash_fund_ids:
    # Batch fetch: latest DFF from macro_data
    fed_funds_rate = await _fetch_latest_macro_value(db, "DFF", as_of_date)
    
    # Batch fetch: MMF metadata from sec_money_market_funds
    # JOIN instruments_universe.attributes->>'sec_series_id' to sec_money_market_funds.series_id
    mmf_data = await _batch_fetch_mmf_data(db, cash_fund_ids)
    
    # Batch fetch: latest sec_mmf_metrics for 7-day yield
    mmf_yields = await _batch_fetch_mmf_yields(db, cash_fund_ids)
    
    for fund, metrics_dict in computed:
        if str(fund.instrument_id) not in cash_fund_ids:
            continue
        
        mmf_info = mmf_data.get(str(fund.instrument_id), {})
        yield_info = mmf_yields.get(str(fund.instrument_id), {})
        
        metrics_dict["seven_day_net_yield"] = yield_info.get("seven_day_net_yield")
        metrics_dict["fed_funds_rate_at_calc"] = fed_funds_rate
        metrics_dict["nav_per_share"] = mmf_info.get("stable_nav_price") or mmf_info.get("nav_per_share")
        metrics_dict["pct_weekly_liquid"] = mmf_info.get("pct_weekly_liquid_latest")
        metrics_dict["weighted_avg_maturity"] = mmf_info.get("weighted_avg_maturity")
        metrics_dict["scoring_model"] = "cash"
```

### 1.5 Screener Gate Extensions (Cash)

**Layer 1 -- Eliminatory (fund_cash):**

```json
{
  "fund_cash": {
    "min_pct_weekly_liquid": 30.0,
    "max_weighted_avg_maturity": 60,
    "min_net_assets": 100000000
  }
}
```

Compound gate logic (same pattern as fund_fixed_income):

```python
# In LayerEvaluator.evaluate_layer1():
if instrument_type == "fund" and attributes.get("asset_class") == "cash":
    cash_criteria = criteria.get("fund_cash", {})
    for criterion, expected in cash_criteria.items():
        result = self._evaluate_criterion(
            criterion, expected, attributes, "fund_cash", layer=1,
        )
        if result is not None:
            results.append(result)
```

**Layer 2 -- Mandate fit (cash block):**

```json
{
  "blocks": {
    "cash": {
      "criteria": {
        "max_weighted_avg_maturity": 60,
        "min_pct_weekly_liquid": 30.0,
        "allowed_mmf_category": ["Government", "Prime", "Tax-Exempt"]
      }
    }
  }
}
```

**Layer 3 -- Quant scoring:**

New `CashQuantMetrics` dataclass in `quant_metrics.py`:

```python
@dataclass(frozen=True, slots=True)
class CashQuantMetrics:
    """Cash/MMF screening metrics from fund_risk_metrics + sec_mmf data."""
    yield_vs_risk_free: float
    nav_stability: float
    liquidity_quality: float
    maturity_discipline: float
    fee_efficiency: float
    data_source: str  # mmf_filing | nav_proxy
```

The `_compute_layer3_score()` in `ScreenerService` adds:

```python
if isinstance(quant_metrics, CashQuantMetrics):
    config_key = "fund_cash"
```

### 1.6 Benchmark Mapping (Cash)

Already exists: `cash` block -> `SHV` (iShares Short Treasury Bond ETF).

Adequate for relative performance. SHV tracks 1-12 month Treasury bills, which is the appropriate comparison for money market funds.

### 1.7 Data Availability (Cash)

| Metric | Source | Availability | Notes |
|---|---|---|---|
| seven_day_net_yield | sec_mmf_metrics | HIGH -- 20k daily rows, N-MFP filings | Class-level yield |
| fed_funds_rate | macro_data (DFF) | HIGH -- daily ingestion | Already ingested |
| nav_per_share | sec_money_market_funds.stable_nav_price | HIGH -- from N-MFP | Stable NAV funds report this directly |
| pct_weekly_liquid | sec_money_market_funds | HIGH -- from N-MFP | Required SEC disclosure |
| weighted_avg_maturity | sec_money_market_funds | HIGH -- from N-MFP | Required SEC disclosure, in days |
| expense_ratio_pct | sec_fund_classes XBRL | MODERATE -- 61% coverage for mutual funds | Missing for some MMFs |

**Key data join:** The link from `instruments_universe` to `sec_money_market_funds` goes through `attributes->>'sec_series_id'` (populated during import). The join to `sec_mmf_metrics` requires the class_id which is stored in `sec_fund_classes`.

---

## Fase 2 -- Alternatives Scoring Model (Core Infrastructure)

### 2.1 Alternatives Analytics Service

`backend/quant_engine/alternatives_analytics_service.py` [NEW]

Sync-pure module. Zero I/O. Config as parameter. Same architecture as `fixed_income_analytics_service.py`.

```python
"""Alternatives analytics -- correlation, downside capture, crisis alpha.

Sync-pure module: zero I/O, zero imports from app.* or vertical_engines.*.
Config is injected as parameter -- never reads YAML, never uses @lru_cache.
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True, slots=True)
class AltAnalyticsResult:
    """Result of alternatives fund analytics."""
    equity_correlation_252d: float | None    # Rolling 252-day correlation with SPY
    downside_capture_1y: float | None        # Down-market capture ratio
    upside_capture_1y: float | None          # Up-market capture ratio
    crisis_alpha_score: float | None         # Performance during equity drawdowns > 10%
    calmar_ratio_3y: float | None            # 3Y annualized return / max drawdown
    sortino_ratio_1y: float | None           # Return / downside deviation (already in fund_risk_metrics)
    inflation_beta: float | None             # Regression beta vs CPI changes (for commodities/REIT)
    inflation_beta_r2: float | None          # R^2 of inflation regression

@dataclass(frozen=True, slots=True)
class AltAnalyticsConfig:
    """Configuration for alternatives analytics."""
    min_observations: int = 120
    correlation_window_days: int = 252       # 1 year rolling
    crisis_drawdown_threshold: float = -0.10 # 10% drawdown = crisis period
    equity_benchmark_ticker: str = "SPY"     # For correlation + capture ratios
    inflation_series: str = "CPIAUCSL"       # For inflation beta regression
```

### 2.2 Core Analytics Functions

#### `compute_equity_correlation(fund_returns, benchmark_returns, window=252) -> float | None`

Rolling correlation with equity benchmark (SPY). This is THE fundamental metric for alternatives -- the whole point of alternatives is low/negative equity correlation.

```
corr = np.corrcoef(fund_returns[-252:], spy_returns[-252:])[0, 1]
```

- Guard: len(aligned) < 120 -> None.
- Returns correlation coefficient [-1.0, 1.0].
- For scoring: LOWER correlation = BETTER (inverted normalization).

#### `compute_capture_ratios(fund_returns, benchmark_returns) -> tuple[float | None, float | None]`

Downside capture = fund return in down months / benchmark return in down months.
Upside capture = fund return in up months / benchmark return in up months.

```python
def compute_capture_ratios(
    fund_monthly: np.ndarray, bench_monthly: np.ndarray,
) -> tuple[float | None, float | None]:
    down_mask = bench_monthly < 0
    up_mask = bench_monthly > 0
    
    downside_capture = None
    if down_mask.sum() >= 3:
        downside_capture = float(fund_monthly[down_mask].mean() / bench_monthly[down_mask].mean())
    
    upside_capture = None
    if up_mask.sum() >= 3:
        upside_capture = float(fund_monthly[up_mask].mean() / bench_monthly[up_mask].mean())
    
    return downside_capture, upside_capture
```

Institutional interpretation:
- Downside capture < 1.0 = fund loses LESS than benchmark in down months = GOOD.
- Upside capture > 1.0 = fund gains MORE than benchmark in up months = GOOD.
- Ideal alternatives fund: downside_capture = 0.3, upside_capture = 0.7 (protects in drawdowns, participates in rallies).

#### `compute_crisis_alpha(fund_returns, benchmark_returns, threshold=-0.10) -> float | None`

Performance of the fund during periods when the equity benchmark is in a drawdown > 10%.

```python
def compute_crisis_alpha(
    fund_daily: np.ndarray, bench_daily: np.ndarray, dates: np.ndarray,
    threshold: float = -0.10,
) -> float | None:
    # Compute benchmark cumulative drawdown
    bench_cum = np.cumprod(1 + bench_daily)
    bench_peak = np.maximum.accumulate(bench_cum)
    bench_dd = (bench_cum - bench_peak) / bench_peak
    
    crisis_mask = bench_dd < threshold  # Periods where benchmark is down > 10%
    
    if crisis_mask.sum() < 20:  # Need at least 20 crisis days
        return None
    
    # Fund return during crisis vs benchmark return during crisis
    fund_crisis_return = float(np.prod(1 + fund_daily[crisis_mask]) - 1)
    bench_crisis_return = float(np.prod(1 + bench_daily[crisis_mask]) - 1)
    
    # Crisis alpha = fund return - benchmark return during crisis periods
    # Positive = fund outperformed during crisis = diversification value
    return fund_crisis_return - bench_crisis_return
```

#### `compute_calmar_ratio(return_3y_ann, max_drawdown_3y) -> float | None`

```python
def compute_calmar_ratio(return_3y_ann: float | None, max_drawdown_3y: float | None) -> float | None:
    if return_3y_ann is None or max_drawdown_3y is None:
        return None
    if max_drawdown_3y >= 0:  # No drawdown or positive (data error)
        return None
    return return_3y_ann / abs(max_drawdown_3y)
```

Calmar already uses data in `fund_risk_metrics` (return_3y_ann, max_drawdown_3y) -- no new data needed.

#### `compute_inflation_beta(fund_returns, cpi_changes, config) -> tuple[float | None, float | None]`

Same OLS approach as FI's credit_beta, but regressing against monthly CPI changes.

```
R_fund(t) = alpha + beta * delta_CPI(t) + epsilon(t)
inflation_beta = beta
```

- CPI is monthly (CPIAUCSL from macro_data). Convert fund returns to monthly before regression.
- Positive inflation_beta = fund returns go up with inflation = inflation hedge = GOOD for REIT/commodities.
- Guard: R^2 < 0.02 -> None (no meaningful inflation sensitivity).

**Data availability:** CPIAUCSL is already ingested monthly by `macro_ingestion` worker. No new external data needed.

### 2.3 Scoring Components per Alternative Profile

All profiles share 5 components (sum = 1.0) but with DIFFERENT weights and normalization ranges:

#### Profile: REIT (`alt_real_estate`)

| Componente | Peso | Metrica | Normalizacao |
|---|---|---|---|
| `income_generation` | 0.25 | yield_proxy_12m (reuse FI metric) | Range: 0% to 10%. REITs are yield vehicles -- income stability is primary. |
| `diversification_value` | 0.25 | 1 - abs(equity_correlation_252d) | Range: 0 to 1. Lower equity correlation = higher diversification. Score 100 at corr=0, score 50 at corr=0.5, score 0 at corr=1.0. |
| `downside_protection` | 0.20 | 1 - downside_capture_1y | Range: 0 to 2. Score 100 at capture=0 (no downside), score 50 at capture=1.0, score 0 at capture >= 2.0. |
| `inflation_hedge` | 0.20 | inflation_beta | Range: -2.0 to 4.0. Score 100 at beta=4 (strong inflation hedge), score 50 at beta=1, score 0 at beta <= -2. |
| `fee_efficiency` | 0.10 | Same formula | Same |

```python
_DEFAULT_ALT_REIT_WEIGHTS: dict[str, float] = {
    "income_generation": 0.25,
    "diversification_value": 0.25,
    "downside_protection": 0.20,
    "inflation_hedge": 0.20,
    "fee_efficiency": 0.10,
}
```

#### Profile: Commodity (`alt_commodities`)

| Componente | Peso | Metrica | Normalizacao |
|---|---|---|---|
| `inflation_hedge` | 0.30 | inflation_beta | Range: -2.0 to 4.0. THE primary reason to hold commodities. |
| `diversification_value` | 0.25 | 1 - abs(equity_correlation_252d) | Same as REIT. |
| `crisis_alpha` | 0.20 | crisis_alpha_score | Range: -0.20 to 0.30. Score 100 = outperforms SPY by 30% in crises. Score 50 = neutral. Score 0 = underperforms by 20%. |
| `drawdown_control` | 0.15 | calmar_ratio_3y | Range: 0 to 2.0. Score 100 at Calmar 2.0, score 50 at 1.0, score 0 at 0. |
| `fee_efficiency` | 0.10 | Same | Same |

```python
_DEFAULT_ALT_COMMODITY_WEIGHTS: dict[str, float] = {
    "inflation_hedge": 0.30,
    "diversification_value": 0.25,
    "crisis_alpha": 0.20,
    "drawdown_control": 0.15,
    "fee_efficiency": 0.10,
}
```

#### Profile: Gold (`alt_gold`)

| Componente | Peso | Metrica | Normalizacao |
|---|---|---|---|
| `crisis_alpha` | 0.30 | crisis_alpha_score | Range: -0.20 to 0.30. Gold's primary value is crisis hedge. |
| `diversification_value` | 0.30 | 1 - abs(equity_correlation_252d) | Gold should be near-zero equity correlation. |
| `inflation_hedge` | 0.20 | inflation_beta | Gold as real asset. |
| `tracking_efficiency` | 0.10 | Tracking error vs GLD benchmark. Lower = better (for passive gold exposure). | Range: 0 to 5% TE. Score 100 at TE=0, score 0 at TE >= 5%. |
| `fee_efficiency` | 0.10 | Same | Same |

```python
_DEFAULT_ALT_GOLD_WEIGHTS: dict[str, float] = {
    "crisis_alpha": 0.30,
    "diversification_value": 0.30,
    "inflation_hedge": 0.20,
    "tracking_efficiency": 0.10,
    "fee_efficiency": 0.10,
}
```

#### Profile: Hedge Fund (`alt_hedge_fund`) [NEW BLOCK]

| Componente | Peso | Metrica | Normalizacao |
|---|---|---|---|
| `alpha_generation` | 0.30 | sortino_1y (not Sharpe -- Sharpe penalizes upside vol) | Range: -1.0 to 3.0. Sortino isolates downside risk. |
| `downside_protection` | 0.25 | 1 - downside_capture_1y | Same as REIT. |
| `diversification_value` | 0.20 | 1 - abs(equity_correlation_252d) | Market-neutral should have near-zero. Long/short should have 0.3-0.6. |
| `crisis_alpha` | 0.15 | crisis_alpha_score | Hedge funds should protect in stress. |
| `fee_efficiency` | 0.10 | Same | Particularly important for HFs with 2/20. |

```python
_DEFAULT_ALT_HEDGE_WEIGHTS: dict[str, float] = {
    "alpha_generation": 0.30,
    "downside_protection": 0.25,
    "diversification_value": 0.20,
    "crisis_alpha": 0.15,
    "fee_efficiency": 0.10,
}
```

#### Profile: Managed Futures / CTA (`alt_managed_futures`) [NEW BLOCK]

| Componente | Peso | Metrica | Normalizacao |
|---|---|---|---|
| `crisis_alpha` | 0.35 | crisis_alpha_score | THE defining characteristic of trend-followers. 2008 GFC: managed futures +20% when equity -38%. |
| `diversification_value` | 0.25 | 1 - abs(equity_correlation_252d) | CTAs should be near-zero or negative correlation. |
| `risk_adjusted_return` | 0.20 | calmar_ratio_3y | CTAs have volatile P&L; Calmar penalizes large drawdowns relative to return. |
| `fee_efficiency` | 0.10 | Same | CTA fees are high (1.5/20 typical). |
```python
_DEFAULT_ALT_CTA_WEIGHTS: dict[str, float] = {
    "crisis_alpha": 0.40,
    "diversification_value": 0.25,
    "risk_adjusted_return": 0.25,
    "fee_efficiency": 0.10,
}
```

**Nota:** `trend_capture` foi removido -- usar `sortino_1y` como proxy causaria double-counting com `alpha_generation` (mesmo metric subjacente). O peso de 0.10 foi redistribuido para `crisis_alpha` (+0.05) e `risk_adjusted_return` (+0.05), ambos com metricas independentes (crisis excess return e Calmar 3Y, respectivamente).

#### Profile: Generic Alt (unclassified alternatives)

For alternatives that don't match any specific block, use a balanced profile:

```python
_DEFAULT_ALT_GENERIC_WEIGHTS: dict[str, float] = {
    "diversification_value": 0.30,
    "downside_protection": 0.25,
    "risk_adjusted_return": 0.20,
    "crisis_alpha": 0.15,
    "fee_efficiency": 0.10,
}
```

### 2.4 New fund_risk_metrics Columns (Alternatives)

```sql
ALTER TABLE fund_risk_metrics
    ADD COLUMN equity_correlation_252d NUMERIC(6, 4),
    ADD COLUMN downside_capture_1y NUMERIC(8, 4),
    ADD COLUMN upside_capture_1y NUMERIC(8, 4),
    ADD COLUMN crisis_alpha_score NUMERIC(10, 6),
    ADD COLUMN calmar_ratio_3y NUMERIC(8, 4),
    ADD COLUMN inflation_beta NUMERIC(8, 4),
    ADD COLUMN inflation_beta_r2 NUMERIC(6, 4);
```

- `equity_correlation_252d`: rolling 252-day Pearson correlation with SPY. Range [-1, 1].
- `downside_capture_1y`: ratio of fund down-month return / SPY down-month return. Range [0, 3+].
- `upside_capture_1y`: ratio of fund up-month return / SPY up-month return. Range [0, 3+].
- `crisis_alpha_score`: cumulative excess return vs SPY during SPY drawdowns > 10%. Decimal.
- `calmar_ratio_3y`: 3Y annualized return / abs(max_drawdown_3y). Higher = better risk-adjusted return.
- `inflation_beta`: OLS beta of monthly returns vs monthly CPI changes.
- `inflation_beta_r2`: R^2 of the inflation regression.

**Note:** `sortino_1y` already exists in fund_risk_metrics. No new column needed.

### 2.5 Protocol

```python
class AltMetrics(Protocol):
    """Protocol for alternatives metrics -- satisfied by FundRiskMetrics ORM or adapter."""
    equity_correlation_252d: Decimal | float | None
    downside_capture_1y: Decimal | float | None
    upside_capture_1y: Decimal | float | None
    crisis_alpha_score: Decimal | float | None
    calmar_ratio_3y: Decimal | float | None
    sortino_1y: Decimal | float | None
    inflation_beta: Decimal | float | None
    yield_proxy_12m: Decimal | float | None  # Reused from FI (for REIT income)
    tracking_error_1y: Decimal | float | None  # Already exists (for gold tracking)
```

### 2.6 Worker Integration (Alternatives Pass)

New pass in `risk_calc.py`, after FI analytics (Pass 1.8) and before scoring (Pass 1.9):

```python
# Pass 1.85: Alternatives analytics (correlation, capture, crisis alpha, inflation beta)
# For funds with asset_class = 'alternatives'
alt_fund_ids = [str(f.instrument_id) for f, _ in computed if f.asset_class == "alternatives"]
if alt_fund_ids:
    # Batch fetch: SPY returns from benchmark_nav (already available)
    spy_returns = await _fetch_benchmark_returns(db, "SPY", start_date, as_of_date)
    
    # Batch fetch: monthly CPI changes from macro_data
    cpi_changes = await _fetch_monthly_macro_changes(db, "CPIAUCSL", start_date, as_of_date)
    
    for fund, metrics_dict in computed:
        if str(fund.instrument_id) not in alt_fund_ids:
            continue
        
        fund_returns = dated_returns_by_fund.get(str(fund.instrument_id), [])
        if not fund_returns:
            metrics_dict["scoring_model"] = "alternatives"
            continue
        
        alt_result = compute_alt_analytics(
            fund_dated_returns=fund_returns,
            benchmark_returns=spy_returns,
            cpi_monthly_changes=cpi_changes,
            return_3y_ann=metrics_dict.get("return_3y_ann"),
            max_drawdown_3y=metrics_dict.get("max_drawdown_3y"),
            config=alt_config,
        )
        
        metrics_dict["equity_correlation_252d"] = alt_result.equity_correlation_252d
        metrics_dict["downside_capture_1y"] = alt_result.downside_capture_1y
        metrics_dict["upside_capture_1y"] = alt_result.upside_capture_1y
        metrics_dict["crisis_alpha_score"] = alt_result.crisis_alpha_score
        metrics_dict["calmar_ratio_3y"] = alt_result.calmar_ratio_3y
        metrics_dict["inflation_beta"] = alt_result.inflation_beta
        metrics_dict["inflation_beta_r2"] = alt_result.inflation_beta_r2
        metrics_dict["scoring_model"] = "alternatives"
```

### 2.7 Screener Gate Extensions (Alternatives)

**Layer 1 -- Eliminatory (fund_alternatives):**

```json
{
  "fund_alternatives": {
    "min_aum_usd": 50000000,
    "min_track_record_years": 3
  }
}
```

Compound gate in `LayerEvaluator.evaluate_layer1()`:

```python
if instrument_type == "fund" and attributes.get("asset_class") == "alternatives":
    alt_criteria = criteria.get("fund_alternatives", {})
    for criterion, expected in alt_criteria.items():
        result = self._evaluate_criterion(
            criterion, expected, attributes, "fund_alternatives", layer=1,
        )
        if result is not None:
            results.append(result)
```

**Layer 2 -- Block-specific mandate fit:**

```json
{
  "blocks": {
    "alt_real_estate": {
      "criteria": {
        "max_equity_correlation_252d": 0.80,
        "min_yield_proxy_12m": 0.02
      }
    },
    "alt_commodities": {
      "criteria": {
        "max_equity_correlation_252d": 0.60
      }
    },
    "alt_gold": {
      "criteria": {
        "max_equity_correlation_252d": 0.30,
        "max_tracking_error_1y": 0.05
      }
    },
    "alt_hedge_fund": {
      "criteria": {
        "max_equity_correlation_252d": 0.70,
        "min_sortino_1y": -0.5
      }
    },
    "alt_managed_futures": {
      "criteria": {
        "max_equity_correlation_252d": 0.40
      }
    }
  }
}
```

**Layer 3 -- Quant scoring:**

New `AltQuantMetrics` dataclass in `quant_metrics.py`:

```python
@dataclass(frozen=True, slots=True)
class AltQuantMetrics:
    """Alternatives fund screening metrics from fund_risk_metrics."""
    equity_correlation_252d: float
    downside_capture_1y: float
    crisis_alpha_score: float
    calmar_ratio_3y: float
    inflation_beta: float
    sortino_1y: float
    yield_proxy_12m: float | None
    tracking_error_1y: float | None
    annual_return_pct: float
    data_period_days: int
    alt_profile: str  # reit | commodity | gold | hedge | cta | generic
    data_quality_flag: str | None = None
```

### 2.8 Benchmark Mapping (Alternatives)

| Block | Benchmark Ticker | Already Ingested? | Action |
|---|---|---|---|
| alt_real_estate | VNQ | YES (blocks.yaml) | None |
| alt_commodities | DJP | YES (blocks.yaml) | None |
| alt_gold | GLD | YES (blocks.yaml) | None |
| alt_hedge_fund | QAI | NO -- NEW | Add to blocks.yaml + seed migration |
| alt_managed_futures | DBMF | NO -- NEW | Add to blocks.yaml + seed migration |

QAI (IQ Hedge Multi-Strategy Tracker ETF) and DBMF (iMGP DBi Managed Futures Strategy ETF) are the best liquid proxies for hedge fund and CTA benchmarks. Both have 5+ years of history and are available on Yahoo Finance.

---

## Fase 3 -- Scoring Dispatch Refactor

### 3.1 Unified Dispatch in `scoring_service.py`

Extend `resolve_scoring_weights()`:

```python
def resolve_scoring_weights(
    config: dict[str, Any] | None = None,
    asset_class: str = "equity",
    alt_profile: str | None = None,  # NEW
) -> dict[str, float]:
    defaults = {
        "equity": _DEFAULT_SCORING_WEIGHTS,
        "fixed_income": _DEFAULT_FI_SCORING_WEIGHTS,
        "cash": _DEFAULT_CASH_SCORING_WEIGHTS,
        "alternatives": _resolve_alt_defaults(alt_profile),
    }
    default = defaults.get(asset_class, _DEFAULT_SCORING_WEIGHTS)
    if config is None:
        return default
    try:
        weights = config.get("scoring_weights", config)
        if isinstance(weights, dict) and weights:
            return {k: float(v) for k, v in weights.items()}
        return default
    except (TypeError, ValueError):
        return default


def _resolve_alt_defaults(alt_profile: str | None) -> dict[str, float]:
    profile_defaults = {
        "reit": _DEFAULT_ALT_REIT_WEIGHTS,
        "commodity": _DEFAULT_ALT_COMMODITY_WEIGHTS,
        "gold": _DEFAULT_ALT_GOLD_WEIGHTS,
        "hedge": _DEFAULT_ALT_HEDGE_WEIGHTS,
        "cta": _DEFAULT_ALT_CTA_WEIGHTS,
    }
    return profile_defaults.get(alt_profile or "", _DEFAULT_ALT_GENERIC_WEIGHTS)
```

### 3.2 Unified `compute_fund_score()` Dispatch

```python
def compute_fund_score(
    metrics: RiskMetrics,
    flows_momentum_score: float = 50.0,
    config: dict[str, Any] | None = None,
    expense_ratio_pct: float | None = None,
    insider_sentiment_score: float | None = None,
    peer_medians: dict[str, float] | None = None,
    asset_class: str = "equity",
    fi_metrics: FIMetrics | None = None,
    alt_metrics: AltMetrics | None = None,     # NEW
    alt_profile: str | None = None,             # NEW
    cash_metrics: CashMetrics | None = None,    # NEW
) -> tuple[float, dict[str, float]]:
    # Dispatch chain (most specific first)
    if asset_class == "cash" and cash_metrics is not None:
        return _compute_cash_score(cash_metrics, config, expense_ratio_pct, peer_medians)
    
    if asset_class == "fixed_income" and fi_metrics is not None:
        return _compute_fi_score(fi_metrics, config, expense_ratio_pct, peer_medians)
    
    if asset_class == "alternatives" and alt_metrics is not None:
        return _compute_alt_score(alt_metrics, config, expense_ratio_pct, peer_medians, alt_profile)
    
    # Default: equity scoring (also handles multi_asset and unknown)
    # ... existing equity path ...
```

### 3.3 Alternatives Score Computation

```python
def _compute_alt_score(
    alt: AltMetrics,
    config: dict[str, Any] | None,
    expense_ratio_pct: float | None,
    peer_medians: dict[str, float] | None,
    alt_profile: str | None = None,
) -> tuple[float, dict[str, float]]:
    pm = peer_medians or {}
    components: dict[str, float] = {}
    
    # diversification_value: 1 - |correlation with equity|
    # Lower correlation = better diversification
    corr = float(alt.equity_correlation_252d) if alt.equity_correlation_252d is not None else None
    if corr is not None:
        div_value = 1.0 - abs(corr)
        components["diversification_value"] = div_value * 100
    else:
        components["diversification_value"] = pm.get("diversification_value", 45.0) - 5.0
    
    # downside_protection: 1 - downside_capture (lower capture = better protection)
    dc = float(alt.downside_capture_1y) if alt.downside_capture_1y is not None else None
    if dc is not None:
        # Capture 0 = perfect (100), capture 1.0 = neutral (50), capture >= 2.0 = terrible (0)
        components["downside_protection"] = _normalize(1.0 - dc, -1.0, 1.0, pm.get("downside_protection"))
    else:
        components["downside_protection"] = pm.get("downside_protection", 45.0) - 5.0
    
    # crisis_alpha: excess return during equity drawdowns
    ca = float(alt.crisis_alpha_score) if alt.crisis_alpha_score is not None else None
    components["crisis_alpha"] = _normalize(ca, -0.20, 0.30, pm.get("crisis_alpha"))
    
    # inflation_hedge: inflation beta
    ib = float(alt.inflation_beta) if alt.inflation_beta is not None else None
    components["inflation_hedge"] = _normalize(ib, -2.0, 4.0, pm.get("inflation_hedge"))
    
    # income_generation: yield proxy (for REIT profile)
    yp = float(alt.yield_proxy_12m) if alt.yield_proxy_12m is not None else None
    components["income_generation"] = _normalize(yp, 0.0, 0.10, pm.get("income_generation"))
    
    # alpha_generation: Sortino ratio (for hedge fund profile)
    sort = float(alt.sortino_1y) if alt.sortino_1y is not None else None
    components["alpha_generation"] = _normalize(sort, -1.0, 3.0, pm.get("alpha_generation"))
    
    # risk_adjusted_return: Calmar ratio (for CTA/commodity profiles)
    calm = float(alt.calmar_ratio_3y) if alt.calmar_ratio_3y is not None else None
    components["risk_adjusted_return"] = _normalize(calm, 0.0, 2.0, pm.get("risk_adjusted_return"))
    
    # drawdown_control: Calmar (for commodity profile)
    components["drawdown_control"] = components.get("risk_adjusted_return", 50.0)
    
    # tracking_efficiency: tracking error vs benchmark (for gold profile)
    te = float(alt.tracking_error_1y) if alt.tracking_error_1y is not None else None
    if te is not None:
        # Lower TE = better tracking. 0% = 100, 5% = 0.
        components["tracking_efficiency"] = max(0.0, (1.0 - te / 0.05) * 100)
    else:
        components["tracking_efficiency"] = pm.get("tracking_efficiency", 45.0) - 5.0
    
    # fee_efficiency: shared
    components["fee_efficiency"] = _compute_fee_efficiency(expense_ratio_pct, pm)
    
    weights = resolve_scoring_weights(config, asset_class="alternatives", alt_profile=alt_profile)
    
    score = sum(components.get(k, 50.0) * w for k, w in weights.items())
    
    # Filter to only include components that carry weight in this profile.
    # Prevents nonsensical display (e.g., "Income Generation: 38" on a CTA fund).
    active_components = {k: round(v, 2) for k, v in components.items() if weights.get(k, 0) > 0}
    return round(score, 2), active_components
```

Key design decision: ALL components are computed for ALL alternatives funds, but WEIGHTS determine which ones matter. A REIT fund gets scored on income_generation (0.25) but a CTA gets 0.0 weight on income_generation. This means we don't need separate scoring functions per profile -- just different weight vectors.

---

## Fase 4 -- Migration Plan

### Migration 1: `add_cash_scoring_columns` (Cash)

```sql
ALTER TABLE fund_risk_metrics
    ADD COLUMN seven_day_net_yield NUMERIC(8, 4),
    ADD COLUMN fed_funds_rate_at_calc NUMERIC(8, 4),
    ADD COLUMN nav_per_share_mmf NUMERIC(12, 6),
    ADD COLUMN pct_weekly_liquid NUMERIC(8, 4),
    ADD COLUMN weighted_avg_maturity_days INTEGER;
```

Named `nav_per_share_mmf` to avoid collision with any future generic NAV column.

### Migration 2: `add_alternatives_scoring_columns` (Alternatives)

```sql
ALTER TABLE fund_risk_metrics
    ADD COLUMN equity_correlation_252d NUMERIC(6, 4),
    ADD COLUMN downside_capture_1y NUMERIC(8, 4),
    ADD COLUMN upside_capture_1y NUMERIC(8, 4),
    ADD COLUMN crisis_alpha_score NUMERIC(10, 6),
    ADD COLUMN calmar_ratio_3y NUMERIC(8, 4),
    ADD COLUMN inflation_beta NUMERIC(8, 4),
    ADD COLUMN inflation_beta_r2 NUMERIC(6, 4);
```

### Migration 3: `add_alt_benchmark_blocks` (New blocks)

```sql
INSERT INTO allocation_blocks (block_id, asset_class, geography, display_name, benchmark_ticker, is_active)
VALUES
    ('alt_hedge_fund', 'alternatives', 'global', 'Hedge Funds / Multi-Strategy', 'QAI', true),
    ('alt_managed_futures', 'alternatives', 'global', 'Managed Futures / CTA', 'DBMF', true)
ON CONFLICT (block_id) DO NOTHING;
```

### Materialized View Updates

`mv_unified_funds` and `mv_unified_assets` may need refresh after new instruments get proper alt profiles. No schema change needed -- the scoring_model column already exists.

---

## Fase 5 -- Scoring Model in Worker (Dispatch Logic)

### Determining `scoring_model` in `_score_metrics()`

```python
def _score_metrics(
    metrics: dict,
    scoring_config: dict | None = None,
    expense_ratio_pct: float | None = None,
    asset_class: str = "equity",
    block_id: str | None = None,  # NEW -- for alt profile resolution
) -> None:
    adapter = _MetricsAdapter(metrics)
    flows = float(metrics.get("blended_momentum_score") or 50.0)
    
    # Determine scoring model and build appropriate adapter
    if asset_class == "cash":
        cash_adapter = _CashMetricsAdapter(metrics)
        score_val, components = compute_fund_score(
            adapter,
            config=scoring_config,
            expense_ratio_pct=expense_ratio_pct,
            asset_class="cash",
            cash_metrics=cash_adapter,
        )
    elif asset_class == "fixed_income":
        fi_adapter = _FIMetricsAdapter(metrics)
        score_val, components = compute_fund_score(
            adapter,
            flows_momentum_score=flows,
            config=scoring_config,
            expense_ratio_pct=expense_ratio_pct,
            asset_class="fixed_income",
            fi_metrics=fi_adapter,
        )
    elif asset_class == "alternatives":
        alt_adapter = _AltMetricsAdapter(metrics)
        # Global worker (900_071): resolve from strategy_label (no block_id available).
        # Org worker (900_007): resolve from block_id if available, else strategy_label.
        if block_id:
            alt_profile = _resolve_alt_profile(block_id)
        else:
            alt_profile = _resolve_alt_profile_from_strategy_label(
                metrics.get("_strategy_label"),  # injected earlier from instrument attributes
            )
        score_val, components = compute_fund_score(
            adapter,
            config=scoring_config,
            expense_ratio_pct=expense_ratio_pct,
            asset_class="alternatives",
            alt_metrics=alt_adapter,
            alt_profile=alt_profile,
        )
    else:
        # Equity path (default)
        score_val, components = compute_fund_score(
            adapter,
            flows_momentum_score=flows,
            config=scoring_config,
            expense_ratio_pct=expense_ratio_pct,
            asset_class="equity",
        )
    
    metrics["manager_score"] = round(score_val, 2)
    metrics["score_components"] = components


_BLOCK_TO_ALT_PROFILE = {
    "alt_real_estate": "reit",
    "alt_commodities": "commodity",
    "alt_gold": "gold",
    "alt_hedge_fund": "hedge",
    "alt_managed_futures": "cta",
}

def _resolve_alt_profile(block_id: str | None) -> str:
    """Resolve alt profile from block_id. Used in org-scoped worker (has block_id)."""
    if not block_id:
        return "generic"
    return _BLOCK_TO_ALT_PROFILE.get(block_id, "generic")


def _resolve_alt_profile_from_strategy_label(strategy_label: str | None) -> str:
    """Resolve alt profile from strategy_label via block_mapping.
    
    Used in GLOBAL worker (lock 900_071) where block_id is NOT available
    (block assignment is org-scoped via instruments_org).
    Chain: strategy_label -> blocks_for_strategy_label() -> first block -> profile.
    """
    if not strategy_label:
        return "generic"
    from vertical_engines.wealth.model_portfolio.block_mapping import blocks_for_strategy_label
    blocks = blocks_for_strategy_label(strategy_label)
    for b in blocks:
        if b in _BLOCK_TO_ALT_PROFILE:
            return _BLOCK_TO_ALT_PROFILE[b]
    return "generic"
```

---

## Fase 6 -- Tests

### Unit Tests

#### `test_scoring_service.py` (extend)

1. **Cash scoring -- high yield MMF:** seven_day_net_yield=5.5%, DFF=5.33%, WAM=15, weekly_liquid=80%, ER=0.15% -> score > 75.
2. **Cash scoring -- poor MMF:** seven_day_net_yield=4.0%, DFF=5.33%, WAM=55, weekly_liquid=32% -> score < 40.
3. **Cash scoring -- nav_stability edge case:** nav_per_share=0.9998 (2bp deviation) -> nav_stability ~80. nav_per_share=0.9970 (30bp break the buck) -> nav_stability = 0.
4. **Cash vs equity -- MMF should not get equity scored:** verify scoring_model="cash" when asset_class="cash" and cash_metrics provided.
5. **Alt REIT -- income + low correlation:** yield_proxy=0.06, equity_corr=0.3, downside_capture=0.5, inflation_beta=1.5 -> score > 70 on reit profile.
6. **Alt REIT -- high correlation (bad diversifier):** equity_corr=0.85 -> diversification_value < 20.
7. **Alt CTA -- crisis alpha:** crisis_alpha=0.15 (outperformed SPY by 15% in crises), equity_corr=-0.1 -> score > 75 on cta profile.
8. **Alt Hedge -- alpha generation:** sortino=2.0, downside_capture=0.4, equity_corr=0.3 -> score > 70 on hedge profile.
9. **Alt Gold -- tracking efficiency:** tracking_error=0.01 (1% TE) -> tracking_efficiency = 80. tracking_error=0.05 -> tracking_efficiency = 0.
10. **Profile weight verification:** same metrics scored with reit vs cta profile -> different scores (income matters for REIT, crisis_alpha matters for CTA).

#### `test_alternatives_analytics_service.py` (new)

1. **Equity correlation:** Fund with returns = 0.8 * SPY + noise -> correlation ~0.8.
2. **Zero correlation:** Fund with random returns independent of SPY -> correlation ~0.
3. **Capture ratios:** Fund that drops 50% of SPY drop in down months -> downside_capture ~0.5.
4. **Crisis alpha:** Fund that is flat during 15% SPY drawdown -> crisis_alpha ~+0.15.
5. **Inflation beta -- REIT with CPI sensitivity:** Fund returns = 2.0 * CPI_change + noise -> inflation_beta ~2.0.
6. **Calmar ratio:** return_3y=0.10, max_dd=-0.05 -> calmar=2.0.
7. **Insufficient data:** < 120 observations -> all None.

#### `test_screener_cash_gates.py` (new)

1. **Layer 1 fund_cash gate:** WAM=70 (> max 60) -> FAIL at layer 1.
2. **Layer 1 fund_cash gate:** weekly_liquid=25% (< min 30%) -> FAIL.
3. **Layer 2 cash block:** mmf_category="Prime" with allowed list -> PASS.
4. **Layer 3 CashQuantMetrics:** composite score via percentile rank.

---

## Fase 7 -- Phase Sequencing

### Implementacao Order

| Seq | Fase | Deps | Parallelizavel? | Estimativa |
|---|---|---|---|---|
| 1 | Migration 1 (cash columns) | None | YES with 2 | 30min |
| 2 | Migration 2 (alt columns) | None | YES with 1 | 30min |
| 3 | Migration 3 (new blocks) | None | YES with 1,2 | 20min |
| 4 | `alternatives_analytics_service.py` | None | YES with 1-3 | 2h |
| 5 | Cash scoring in `scoring_service.py` | Migration 1 | After 1 | 1.5h |
| 6 | Alt scoring in `scoring_service.py` | Migration 2, service | After 2,4 | 2h |
| 7 | Screener gates (cash + alt) | Scoring done | After 5,6 | 1.5h |
| 8 | Worker: cash pass | Migration 1, scoring | After 5 | 2h |
| 9 | Worker: alt pass | Migration 2, service | After 6 | 2h |
| 10 | Block mapping updates | Migration 3 | After 3 | 30min |
| 11 | Unit tests | All above | After each phase | Continuous |
| 12 | Integration test (full worker run) | All above | After 8,9 | 1h |

**Critical path:** Migrations -> analytics service -> scoring service -> worker integration -> tests.

**Parallelizable:** Migrations 1-3 are independent. Cash scoring (5) and alt analytics service (4) are independent. Worker passes (8, 9) depend on scoring but are independent of each other.

### Recommended Execution Order

**Sprint 1 -- Cash/MMF (simpler, most impactful):**
1. Migration 1 (cash columns)
2. Cash defaults + CashMetrics protocol in scoring_service.py
3. `_compute_cash_score()` function
4. Cash pass in risk_calc worker
5. Layer 1/2/3 cash gates in screener
6. Tests

**Sprint 2 -- Alternatives Core (infrastructure):**
1. Migration 2 (alt columns) + Migration 3 (new blocks)
2. `alternatives_analytics_service.py` (pure functions)
3. Tests for analytics service
4. Alt defaults + AltMetrics protocol in scoring_service.py
5. `_compute_alt_score()` with profile-based weights

**Sprint 3 -- Alternatives Integration (worker + screener):**
1. Block mapping updates
2. Alt analytics pass in risk_calc worker
3. Alt profile resolution in `_score_metrics()`
4. Layer 1/2/3 alt gates in screener
5. AltQuantMetrics in screener quant_metrics
6. Integration tests

---

## Data Availability Reality Check

### What We CAN Compute from Existing Data

| Metric | Data Source | Available? | Notes |
|---|---|---|---|
| equity_correlation_252d | nav_timeseries + benchmark_nav (SPY) | YES | Both already ingested daily |
| downside_capture_1y | nav_timeseries + benchmark_nav (SPY) | YES | Monthly returns from daily NAV |
| upside_capture_1y | nav_timeseries + benchmark_nav (SPY) | YES | Same as above |
| crisis_alpha_score | nav_timeseries + benchmark_nav (SPY) | YES | Need to identify crisis periods from SPY drawdowns |
| calmar_ratio_3y | fund_risk_metrics (return_3y_ann, max_drawdown_3y) | YES | Already pre-computed columns |
| sortino_1y | fund_risk_metrics | YES | Already exists |
| inflation_beta | nav_timeseries + macro_data (CPIAUCSL) | YES | CPI already ingested monthly |
| tracking_error_1y | fund_risk_metrics | YES | Already exists |
| yield_proxy_12m | nav_timeseries | YES | Same FI computation (reuse) |
| seven_day_net_yield | sec_mmf_metrics | YES | 20k daily rows |
| fed_funds_rate | macro_data (DFF) | YES | Daily |
| nav_per_share (MMF) | sec_money_market_funds.stable_nav_price | YES | From N-MFP |
| pct_weekly_liquid | sec_money_market_funds | YES | From N-MFP |
| weighted_avg_maturity | sec_money_market_funds | YES | From N-MFP |

### What We CANNOT Compute (Would Need New Data Sources)

| Metric | Would Need | Priority | Workaround |
|---|---|---|---|
| Real occupancy rates (REITs) | REIT 10-K filings | LOW | Use returns vs VNQ as proxy |
| Actual roll yield (commodities) | Commodity futures curve data | LOW | Use DJP tracking error as proxy |
| Hedge fund AUM flows | HFR/Preqin database | LOW | Use NAV-based flow proxy (existing) |
| Daily NAV for shadow pricing (MMF) | Institutional NAV feed | MEDIUM | Use stable_nav_price from N-MFP |

**Conclusion:** Every metric in the plan is computable from existing data sources. No new external data integrations needed.

---

## Audit & Provenance

- `scoring_model` column already exists in fund_risk_metrics -- extend values to include "alternatives" and "cash".
- `score_components` JSONB stores the actual component scores. Consumers (frontend, fact sheet) use `scoring_model` to interpret keys.
- Worker sets `scoring_model` before calling `_score_metrics()` -- audit trail is clear.
- All analytics regressions store R^2 values (`inflation_beta_r2`) for confidence auditing.
- ConfigService overrides are tenant-specific -- if a tenant wants different alt weights, they override via ConfigService without affecting global scoring.

## Frontend Implications

- Score composition panel (`ScoreCompositionPanel.svelte`) needs to handle new component keys. The panel already reads `score_components` JSONB dynamically.
- `scoring_model` label should translate to institutional vocabulary:
  - "equity" -> "Equity Score"
  - "fixed_income" -> "Fixed Income Score"  
  - "alternatives" -> "Alternatives Score"
  - "cash" -> "Cash/MMF Score"
- Alternatives sub-profile (REIT, commodity, etc.) shown as subtitle: "Alternatives Score (Real Estate)".
- NO quant jargon in UI: "crisis_alpha" -> "Stress Protection", "inflation_beta" -> "Inflation Sensitivity", "downside_capture" -> "Downside Protection".
- **Zero-weight component filtering:** `_compute_alt_score` computes ALL components regardless of profile, but only some carry weight. The backend MUST filter `score_components` JSONB to only include components with weight > 0 before persisting. Otherwise a CTA fund would show "Income Generation: 38.5" in the ScoreCompositionPanel, which is nonsensical. Implementation: `components = {k: v for k, v in components.items() if weights.get(k, 0) > 0}` before returning from `_compute_alt_score`.
