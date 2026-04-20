---
title: EDHEC Quant Gap Closure — Quant Math Spec
date: 2026-04-19
author: wealth-portfolio-quant-architect (design round 1)
status: approved
scope: G1 Robust Sharpe, G2 ENB Meucci, G3 math (returns-based + Brinson-Fachler), G4 EVT, G5 IPCA
---

# Spec Técnico-Matemático — Gaps Quânticos EDHEC vs Netz

**Autor:** wealth-portfolio-quant-architect
**Audience:** senior engineer translating this into Opus execution prompts
**Stack:** scipy.stats, numpy, pandas, cvxpy (CLARABEL+SCS), arch, statsmodels, pyarrow; `bkelly-lab/ipca` (new, for G5)

---

## 1. G1 — Robust Sharpe Ratio

### 1.1 Fundamentos

Sharpe tradicional assume retornos i.i.d. normais. Fundos de hedge, private credit e estruturas com carry têm skewness negativa e kurtose excedente — o Sharpe amostral superestima performance. Duas correções:

**Sharpe tradicional (anualizado, mensal):**

$$SR = \frac{\bar{r} - r_f}{\sigma} \cdot \sqrt{12}$$

**Cornish-Fisher adjusted Sharpe** (Favre & Galeano 2002, operacionalizado Gregoriou & Gueyie 2003):

Seja $z = \Phi^{-1}(\alpha)$ (quantil normal), $S$ = skewness amostral, $K$ = excess kurtosis. O quantil modificado é:

$$z_{CF} = z + \tfrac{1}{6}(z^2 - 1)S + \tfrac{1}{24}(z^3 - 3z)K - \tfrac{1}{36}(2z^3 - 5z)S^2$$

Para Sharpe robusto, aplicamos Cornish-Fisher ao **denominador** via VaR-modificado:

$$\sigma_{CF} = -\frac{z_{CF}}{z} \cdot \sigma$$
$$SR_{CF} = \frac{\bar{r} - r_f}{\sigma_{CF}} \cdot \sqrt{12}$$

com $\alpha = 0.05$ (convenção). Quando $S = K = 0$, $SR_{CF} \equiv SR$.

**Opdyke 95% CI** (Opdyke 2007, JFIM): variância assintótica de $SR$ com retornos não-i.i.d.:

$$\text{Var}(\widehat{SR}) \approx \frac{1}{T}\left(1 + \tfrac{1}{2}SR^2 - S \cdot SR + \tfrac{K-3}{4}SR^2\right)$$

**Recomendação:** forma fechada IID + correção S/K como método padrão; jackknife se $T < 60$ ou $|S| > 1.5$; bootstrap opt-in via parâmetro `ci_method`.

### 1.2 API

```python
@dataclass(frozen=True)
class RobustSharpeResult:
    sharpe_traditional: float
    sharpe_cornish_fisher: float
    ci_lower_95: float
    ci_upper_95: float
    skewness: float
    excess_kurtosis: float
    n_observations: int
    ci_method: Literal["closed_form", "jackknife"]
    degraded: bool
    degraded_reason: str | None

def robust_sharpe(
    returns: np.ndarray,
    rf_rate: float | None,
    ci_method: str = "closed_form",
    alpha_cf: float = 0.05,
) -> RobustSharpeResult: ...
```

### 1.3 Edge cases

- **T < 36**: `degraded=True`, só traditional preenchido, CF/CI = NaN
- **rf_rate None**: assume 0 (não inferir da FRED)
- **NaNs**: strip; se sobra < T mínimo, degraded
- **σ = 0**: SR=inf com sinal, degraded=True, reason="zero_volatility"
- **$z_{CF}$ positivo** (skew extrema): clampa em -0.01, degraded, reason="cornish_fisher_non_monotonic"

### 1.4 Integração `scoring_service.py`

1. `risk_adjusted_return` continua default usando Sharpe tradicional
2. ConfigService key: `wealth.scoring.use_robust_sharpe` (bool, default false)
3. `ScoringConfig` ganha `use_robust_sharpe: bool`; resolvido no entry async, passado stateless
4. Flag OFF: lê `fund_risk_metrics.sharpe_ratio` (existente)
5. Flag ON: lê `fund_risk_metrics.sharpe_cf`; fallback `sharpe_ratio` com WARN se NULL
6. `global_risk_metrics` worker (lock 900_071) popula `sharpe_cf` SEMPRE (independente da flag)
7. Migration adiciona `fund_risk_metrics.sharpe_cf`, `sharpe_cf_skew`, `sharpe_cf_kurt`, `sharpe_cf_ci_lower`, `sharpe_cf_ci_upper` (5 colunas FLOAT nullable)

**Backfill timing (crítico):** worker full-mode roda ANTES do flag flip. Sequência: merge PR com flag OFF → migration → `global_risk_metrics` full backfill (1-2h para ~10k instrumentos) → validar `COUNT(*) WHERE sharpe_cf IS NULL = 0` para instrumentos ativos → flip flag em staging → smoke → prod.

### 1.5 Validação

- **Golden 1:** série gaussiana T=240, μ=0.01, σ=0.04 → $|SR_{CF} - SR| < 0.02$
- **Golden 2:** skew=-1.5, kurt=3 → $SR_{CF} < SR$ estrito
- **Property:** invariante a escala $(r, r_f) \to (\lambda r, \lambda r_f)$
- **Ground truth:** R `PerformanceAnalytics::SharpeRatio.modified` (Favre-Galeano), tol 1e-4
- **Edge:** T=12, T=35, all NaNs → degraded flags corretas

---

## 2. G2 — Effective Number of Bets (Meucci)

### 2.1 Fórmula

Dado $w \in \mathbb{R}^N$, $B \in \mathbb{R}^{N \times K}$, $\Sigma_f \in \mathbb{R}^{K \times K}$:

$$p_f = B^T w, \quad \sigma_P^2 = p_f^T \Sigma_f p_f$$

$$RC_k = \frac{p_{f,k} \cdot (\Sigma_f p_f)_k}{\sigma_P^2}, \quad \sum_k RC_k = 1$$

**Meucci 2009 ENB:**

$$N_{\text{ent}} = \exp\left(-\sum_{k=1}^K RC_k \log RC_k\right)$$

Interpretação: uniforme → $N_{\text{ent}} = K$; concentrado → $\to 1$.

### 2.2 Minimum Torsion Bets (Meucci 2013)

PCA-based ENB é instável quando fatores correlacionados. MT resolve rotação ortogonal minimizando $\|\tilde{B} - B\|_F$ s.a. $\tilde{B}^T \Sigma_f \tilde{B} = I$. ~10x mais estável, mais caro (QP/Schur).

**Recomendação:** shipar ambos. Default: `enb_method="entropy"` para scoring; `enb_method="minimum_torsion"` para DD report.

### 2.3 API

```python
@dataclass(frozen=True)
class ENBResult:
    enb_entropy: float
    enb_minimum_torsion: float | None
    risk_contributions: np.ndarray
    factor_exposures: np.ndarray
    method: Literal["entropy", "minimum_torsion", "both"]
    n_factors: int
    degraded: bool

def effective_number_of_bets(
    weights: np.ndarray,
    factor_loadings: np.ndarray,     # N x K
    factor_cov: np.ndarray,          # K x K, PSD
    method: str = "both",
) -> ENBResult: ...
```

### 2.4 Compat

`factor_model_service.decompose_portfolio()` retorna `loadings` (N×K) e `factor_returns` (T×K). Covariância derivável ex-post: `np.cov(factor_returns.T)`. G2 não modifica `factor_model_service.py` — deriva internamente em `diversification_service.meucci_decomposition()`. **Zero conflito com PR-Q1.**

### 2.5 Linguagem sanitizada (DD ch.5)

Backend retorna `enb_entropy: 3.42`. Frontend: "Este portfólio expressa risco equivalente a **3,4 apostas independentes** sobre 7 fatores disponíveis, indicando **concentração moderada** (diversificação ideal: 7,0)."

Scale: ≥0.7·K = "bem diversificado"; 0.4-0.7·K = "moderado"; <0.4·K = "concentrado". Recalibrar após 50 portfolios reais.

---

## 3. G3 — Fase Matemática (Attribution)

### 3.1 Returns-Based Style Analysis (Sharpe 1992)

$$\min_{w \in \mathbb{R}^M} \left\| r_{\text{fund}} - \sum_{i=1}^M w_i r_{\text{style}_i} \right\|^2 \quad \text{s.t.} \quad \sum_i w_i = 1, \; w_i \geq 0$$

**Solver:** `cvxpy` com CLARABEL (já dependency). QP padrão, 5-15 styles, <50ms.

**Outputs:**
- `style_exposures: dict[str, float]`
- `r_squared: float`
- `tracking_error_annualized: float` = $\sqrt{12} \cdot \text{std}(r_{\text{fund}} - \hat{r})$
- `confidence: float` = $\max(0, R^2)$

**Rolling window:** 36m, step 1m. R² < 0.60 flag "não-informativo". Lasso $\lambda = 0.001$ opcional se cond(matriz) > 1e6.

Módulo: `vertical_engines/wealth/attribution/returns_based.py`. Styles default: SPY, IWM, EFA, EEM, AGG, HYG, LQD (todos em `benchmark_nav`).

### 3.2 Brinson-Fachler refatorado

Notação $i$ = setor:
- **Allocation:** $A_i = (w_i^P - w_i^B)(r_i^B - r^B)$
- **Selection:** $S_i = w_i^B (r_i^P - r_i^B)$
- **Interaction:** $I_i = (w_i^P - w_i^B)(r_i^P - r_i^B)$

Soma: $R^P - R^B = \sum_i (A_i + S_i + I_i)$

**Agregação:** GICS Sector (11 setores). CUSIP→GICS via `sec_nport_holdings.industry_sector` (Cenário A) ou JOIN com `sic_gics_mapping` (Cenário B). Cenário C: degrada para `issuer_category × country`.

**Setor ausente no benchmark** ($w_i^B = 0$): força $r_i^B = r^B$; contribuição cai em allocation.

**Confidence por via:**

| Via | Confidence |
|-----|------------|
| Holdings-based (N-PORT) | `nport_coverage_pct` = AUM coberto / AUM fund; <80% degrade para returns-based |
| Returns-based | clamp(R², 0, 1); <0.60 degrade para proxy |
| Proxy | fixo 0.40 |
| IPCA (G5) | OOS explained variance; typically 0.5-0.8 |

---

## 4. G4 — Extreme Value Theory (POT + GPD)

### 4.1 Por que POT

Block Maxima (GEV) desperdiça dados. POT usa todos os excessos acima de threshold $u$; Pickands-Balkema-de Haan garante convergência para GPD. 120 meses históricos → 6-12 obs úteis POT vs 10 block maxima.

### 4.2 Fit GPD

$$F_{\xi,\beta}(y) = 1 - \left(1 + \frac{\xi y}{\beta}\right)^{-1/\xi}, \quad y \geq 0, \; \beta > 0$$

MLE via `scipy.stats.genpareto.fit(excesses, floc=0)`. Fallback L-moments (`lmoments3` lib) se MLE não converge ou CI de $\xi$ cruza 1.

### 4.3 Threshold selection automática

- Primário: quantil 90% fixo
- Sanity check: Hill estimator topo 10% — se $|\xi_{\text{Hill}} - \xi_{\text{MLE}}| > 2x$, degrade
- Excedentes mínimos: <20 → usar 85%; <15 → degraded, fallback parametric

Mean excess plot vai para endpoint separado `/analytics/evt-diagnostic`.

### 4.4 Extreme VaR/CVaR

Dado $u, n_u, N, \hat{\xi}, \hat{\beta}$:

$$\widehat{\text{VaR}}_q = u + \frac{\hat{\beta}}{\hat{\xi}}\left[\left(\frac{N}{n_u}(1-q)\right)^{-\hat{\xi}} - 1\right]$$

$$\widehat{\text{CVaR}}_q = \frac{\widehat{\text{VaR}}_q}{1-\hat{\xi}} + \frac{\hat{\beta} - \hat{\xi}u}{1-\hat{\xi}}, \quad \xi < 1$$

Reportar $q \in \{0.99, 0.995, 0.999\}$.

### 4.5 Estabilidade

- $\hat{\xi} \geq 1$: cauda sem média → NaN + degraded, reason="infinite_mean_tail"
- $\hat{\xi} < 0$: cauda limitada (raro); OK, flag
- MLE não converge: L-moments fallback; se ainda falha → parametric normal com flag

### 4.6 Integração `cvar_service.py`

```python
def compute_cvar(
    returns, alpha,
    method: Literal["historical", "parametric", "evt_pot"] = "historical",
    evt_config: EVTConfig | None = None,
) -> CVaRResult: ...
```

Campos novos: `evt_xi`, `evt_beta`, `evt_threshold`, `evt_n_exceedances`. `fund_risk_metrics` ganha `cvar_99_evt`, `cvar_999_evt` (nullable), populadas por `global_risk_metrics` worker.

---

## 5. G5 — IPCA (Kelly-Pruitt-Su 2019)

### 5.1 Modelo

$$r_{i,t+1} = \alpha_i(z_{i,t}) + \beta_i(z_{i,t})' f_{t+1} + \varepsilon_{i,t+1}$$

com $\alpha_i(z) = z_i'\Gamma_\alpha$, $\beta_i(z) = \Gamma_\beta' z_i$, $z_i \in \mathbb{R}^L$, $f_t \in \mathbb{R}^K$ latent.

Fit ALS: fixo $\Gamma$, estima $f_t$; fixo $f$, estima $\Gamma$. Tolerância $10^{-6}$ ou 200 iter.

Identificação: $\Gamma_\beta'\Gamma_\beta = I_K$, $f$ ortogonais.

### 5.2 Biblioteca

**Adote `bkelly-lab/ipca`**. Código dos autores; ALS testado; unrestricted + restricted + bootstrap included. Não-async (OK — worker-only, nunca hot path).

### 5.3 Panel (Option A, 6 chars via Tiingo)

- **Universe:** 500 largest US equities por market cap estável 2015-2025
- **Characteristics (z):** log-size, book-to-market, momentum 12-1, gross profitability, asset growth, ROA. L=6
- **Panel:** mensal 120 obs × 500 = 60k observações
- **K:** 1-6 fatores, pick K via OOS R² (walk-forward 60m train, 12m test, slide anual)

### 5.4 Arquitetura produção

`quant_engine/factor_model_ipca_service.py` com **mesma interface do PCA**:

```python
def decompose_portfolio(returns_matrix, config: IPCAConfig) -> FactorDecomposition: ...
```

`FactorDecomposition` ganha `loading_characteristics: np.ndarray | None` (só IPCA). ConfigService: `factor_model.engine: "pca" | "ipca"`. Flag por tenant.

**Reestimação:** trimestral via `ipca_estimation` worker (lock 900_091). Drift monitor: $\|\Gamma_{q+1} - \Gamma_q\|_F / \|\Gamma_q\|_F$ — alerta >0.25.

**Convergência risk:** ALS não converge (200 iter) → fallback automático PCA trimestre anterior + alerta ops.

### 5.5 Fórmula 4ª via attribution

$$r_{\text{fund}} = \alpha + \sum_{k=1}^K \beta_k f_k + \varepsilon$$

Contribuição fator-k: $\beta_k \cdot \bar{f}_k$. Peso confidence = $R^2_{OOS}$.

Vantagem vs returns-based: IPCA permite atribuir fundos com <36m histórico desde que universe de fit inclua universe similar. Cross-sectional richness resolve cold-start.

---

## 6. Testes / Validação

### G1
- Gaussiano T=240: $|SR_{CF} - SR| < 0.02$
- Skewed (skew=-1.5): $SR_{CF} < SR$ estrito
- Invariância escala
- R PerformanceAnalytics tol 1e-4
- Edge T=12, T=35, all-NaN → degraded

### G2
- Uniforme: $RC_k = 1/K \Rightarrow N_{\text{ent}} = K$
- Degenerado: $w$ puro 1 fator $\Rightarrow N_{\text{ent}} = 1$
- MT $\geq$ entropy sempre
- Shapes: (100,5), (10,5), (5,20)

### G3
- Golden 60/40 sintético (0.6·SPY + 0.4·AGG + noise σ=0.001) → exposures (0.60, 0.40) tol 0.02
- Constraint $\sum w = 1$ tol 1e-6
- R²>0.99 sintético exato, ≈0 noise puro

### G4
- GPD sintético ($\xi=0.3, \beta=0.02$): recuperar params dentro 1.96×SE em 1000 replicações
- R `evir` package tol 5% em VaR 99.9%
- Infinite tail ($\xi=1.1$): CVaR=NaN, degraded=True
- N=15 excessos → degraded

### G5
- Sintético K=3 fatores + chars: recuperar $\Gamma$ com $\|\hat{\Gamma} - \Gamma\|_F < 0.05$
- Convergência: 95% fits em ≤100 iter
- Walk-forward OOS R² ≥ PCA baseline em 70% trimestres → ship

---

## 7. Não-metas

- G6 copulas — post-G5
- G7 entropy pooling
- Factor zoo beyond 6 chars + PCA/IPCA
- Climate/ESG/sentiment factors
- Bayesian posteriors sobre $\Gamma$ IPCA (10x custo computacional)
- Higher-moment attribution (co-skewness/co-kurtosis)
