// Builder — Data layer. Global ex-Brazil assets, calibration, cascade, MC data.

// ─── Regime context (global macro signals, no BR) ─────────────
const REGIME_CONTEXT = {
  current: "LATE_CYCLE",
  growth: 0.42,      // z-score
  inflation: 0.78,   // z-score
  bands: [
    { code: "SPX",     label: "S&P 500",         z:  1.18, v: 5842 },
    { code: "NDX",     label: "Nasdaq 100",      z:  1.32, v: 20415 },
    { code: "STOXX",   label: "Euro Stoxx 50",   z:  0.58, v: 4925 },
    { code: "NKY",     label: "Nikkei 225",      z:  0.74, v: 38210 },
    { code: "US10Y",   label: "UST 10Y",         z:  0.92, v: 4.38 },
    { code: "DXY",     label: "Dollar Index",    z:  0.44, v: 103.8 },
    { code: "VIX",     label: "Vol Index",       z:  0.62, v: 17.2 },
    { code: "GOLD",    label: "Gold $/oz",       z:  1.48, v: 2612 },
  ],
};

// ─── Asset universe (global, ex-Brazil) ──────────────────────
const UNIVERSE = [
  // US large cap
  { ticker: "SPY",    name: "SPDR S&P 500",         cls: "US_EQ",   region: "US", color: "#6689BC" },
  { ticker: "QQQ",    name: "Invesco QQQ",          cls: "US_EQ",   region: "US", color: "#6689BC" },
  { ticker: "IWM",    name: "iShares Russell 2k",   cls: "US_EQ",   region: "US", color: "#6689BC" },
  { ticker: "XLF",    name: "Financials SPDR",      cls: "US_EQ",   region: "US", color: "#6689BC" },
  { ticker: "XLE",    name: "Energy SPDR",          cls: "US_EQ",   region: "US", color: "#6689BC" },
  // Developed ex-US
  { ticker: "EFA",    name: "iShares MSCI EAFE",    cls: "DM_EQ",   region: "DM", color: "#9FB4D6" },
  { ticker: "EWJ",    name: "iShares MSCI Japan",   cls: "DM_EQ",   region: "DM", color: "#9FB4D6" },
  { ticker: "EWG",    name: "iShares MSCI Germany", cls: "DM_EQ",   region: "DM", color: "#9FB4D6" },
  { ticker: "EWU",    name: "iShares MSCI UK",      cls: "DM_EQ",   region: "DM", color: "#9FB4D6" },
  // Emerging ex-BR
  { ticker: "EEM",    name: "iShares MSCI EM",      cls: "EM_EQ",   region: "EM", color: "#30558E" },
  { ticker: "MCHI",   name: "iShares MSCI China",   cls: "EM_EQ",   region: "EM", color: "#30558E" },
  { ticker: "INDA",   name: "iShares MSCI India",   cls: "EM_EQ",   region: "EM", color: "#30558E" },
  // Fixed income global
  { ticker: "TLT",    name: "iShares UST 20Y+",     cls: "GL_FI",   region: "US", color: "#2BAF7E" },
  { ticker: "IEF",    name: "iShares UST 7-10Y",    cls: "GL_FI",   region: "US", color: "#2BAF7E" },
  { ticker: "LQD",    name: "iShares IG Corp",      cls: "GL_FI",   region: "US", color: "#2BAF7E" },
  { ticker: "HYG",    name: "iShares High Yield",   cls: "GL_FI",   region: "US", color: "#2BAF7E" },
  { ticker: "TIP",    name: "iShares TIPS",         cls: "GL_FI",   region: "US", color: "#2BAF7E" },
  { ticker: "BNDX",   name: "Vanguard Intl Bond",   cls: "GL_FI",   region: "DM", color: "#2BAF7E" },
  // Alternatives
  { ticker: "GLD",    name: "SPDR Gold",            cls: "ALT",     region: "GL", color: "#F2C94C" },
  { ticker: "USO",    name: "US Oil Fund",          cls: "ALT",     region: "GL", color: "#F2C94C" },
  { ticker: "VNQ",    name: "REITs ETF",            cls: "ALT",     region: "US", color: "#F2C94C" },
  // Cash
  { ticker: "CASH",   name: "USD Cash",             cls: "CASH",    region: "US", color: "#A8B4D4" },
];

const ASSET_CLASSES = [
  { id: "US_EQ", name: "US Equity",          color: "#6689BC" },
  { id: "DM_EQ", name: "Developed ex-US",    color: "#9FB4D6" },
  { id: "EM_EQ", name: "Emerging Markets",   color: "#30558E" },
  { id: "GL_FI", name: "Global Fixed Inc",   color: "#2BAF7E" },
  { id: "ALT",   name: "Alternatives",       color: "#F2C94C" },
  { id: "CASH",  name: "Cash",               color: "#A8B4D4" },
];

// ─── Calibration schema ───────────────────────────────────────
const CALIBRATION_DEFAULTS = {
  preset: "MODERATE",
  factors: {
    growth:   0.30,
    value:    0.10,
    momentum: 0.45,
    quality:  0.60,
    size:    -0.20,
  },
  sectorCaps: {
    financials: 25,
    technology: 30,
    energy:     15,
    materials:  15,
    consumer:   20,
    healthcare: 15,
    industrial: 15,
    utilities:  10,
  },
  // global regions (no BR)
  regionCaps: {
    US: 55, DM: 30, EM: 20, ASIA: 25,
  },
  constraints: {
    maxDrawdown:   15,
    trackingError: 3.0,
    turnoverLimit: 40,
    maxSingleName: 8,
    minPositions:  12,
    maxPositions:  24,
  },
  optimizer: {
    riskAversion: 2.5,
    shrinkage:    0.35,
    horizon:      "3Y",
    rebalance:    "QUARTERLY",
  },
};

const PRESETS = {
  CONSERVATIVE: { riskAversion: 4.0, maxDrawdown:  8, trackingError: 1.5, factorMomentum: 0.10, factorQuality: 0.80 },
  MODERATE:     { riskAversion: 2.5, maxDrawdown: 15, trackingError: 3.0, factorMomentum: 0.45, factorQuality: 0.60 },
  AGGRESSIVE:   { riskAversion: 1.2, maxDrawdown: 22, trackingError: 5.0, factorMomentum: 0.85, factorQuality: 0.30 },
};

// ─── Cascade phases ──────────────────────────────────────────
const CASCADE_PHASES = [
  { id: "FACTOR_MODELING",  label: "Factor Modeling",     sub: "Barra-style factor loadings", dur: 1200, tabs: ["RISK"] },
  { id: "SHRINKAGE",        label: "Covariance Shrinkage",sub: "Ledoit-Wolf estimator",       dur: 1000, tabs: ["RISK"] },
  { id: "SOCP_OPTIMIZATION",label: "SOCP Optimization",   sub: "Second-order cone program",   dur: 1600, tabs: ["WEIGHTS"] },
  { id: "STRESS_BACKTEST",  label: "Stress + Backtest",   sub: "8 scenarios · 5Y monthly",    dur: 1400, tabs: ["STRESS", "BACKTEST"] },
  { id: "MONTE_CARLO",      label: "Monte Carlo",          sub: "2,000 paths · log-normal",   dur: 1100, tabs: ["MC"] },
  { id: "ADVISOR",          label: "Advisor Synthesis",    sub: "Heuristics + validation",    dur:  900, tabs: ["ADVISOR"] },
];

// ─── Post-run outputs (global ex-BR) ──────────────────────────
const OPTIMIZED_WEIGHTS = [
  { ticker: "SPY",    cls: "US_EQ", weight: 14.5, prior: 12.0 },
  { ticker: "QQQ",    cls: "US_EQ", weight: 10.2, prior: 8.5 },
  { ticker: "IWM",    cls: "US_EQ", weight:  4.5, prior: 4.0 },
  { ticker: "XLF",    cls: "US_EQ", weight:  5.8, prior: 5.0 },
  { ticker: "XLE",    cls: "US_EQ", weight:  3.2, prior: 3.8 },
  { ticker: "EFA",    cls: "DM_EQ", weight:  7.8, prior: 8.5 },
  { ticker: "EWJ",    cls: "DM_EQ", weight:  4.2, prior: 4.5 },
  { ticker: "EWG",    cls: "DM_EQ", weight:  3.0, prior: 3.2 },
  { ticker: "EWU",    cls: "DM_EQ", weight:  2.5, prior: 2.8 },
  { ticker: "EEM",    cls: "EM_EQ", weight:  4.8, prior: 5.5 },
  { ticker: "MCHI",   cls: "EM_EQ", weight:  2.0, prior: 3.0 },
  { ticker: "INDA",   cls: "EM_EQ", weight:  3.2, prior: 2.5 },
  { ticker: "TLT",    cls: "GL_FI", weight:  6.5, prior: 5.2 },
  { ticker: "IEF",    cls: "GL_FI", weight:  5.8, prior: 5.0 },
  { ticker: "LQD",    cls: "GL_FI", weight:  4.5, prior: 4.8 },
  { ticker: "HYG",    cls: "GL_FI", weight:  2.8, prior: 3.2 },
  { ticker: "TIP",    cls: "GL_FI", weight:  3.5, prior: 2.5 },
  { ticker: "BNDX",   cls: "GL_FI", weight:  2.2, prior: 2.8 },
  { ticker: "GLD",    cls: "ALT",   weight:  5.5, prior: 4.2 },
  { ticker: "USO",    cls: "ALT",   weight:  1.8, prior: 2.2 },
  { ticker: "VNQ",    cls: "ALT",   weight:  1.2, prior: 1.5 },
  { ticker: "CASH",   cls: "CASH",  weight:  0.4, prior: 5.3 },
];

const FACTOR_EXPOSURES = [
  { factor: "Growth",     portfolio:  0.32, target:  0.30, bench: 0.15 },
  { factor: "Value",      portfolio:  0.08, target:  0.10, bench: 0.00 },
  { factor: "Momentum",   portfolio:  0.52, target:  0.45, bench: 0.20 },
  { factor: "Quality",    portfolio:  0.68, target:  0.60, bench: 0.25 },
  { factor: "Size",       portfolio: -0.18, target: -0.20, bench: 0.05 },
  { factor: "Volatility", portfolio: -0.42, target: -0.35, bench: 0.00 },
];

const RISK_DECOMP = [
  { source: "Market (β)",          pct: 38.5, color: "#6689BC" },
  { source: "Sector · Financials", pct: 12.8, color: "#30558E" },
  { source: "Sector · Technology", pct: 14.2, color: "#FF965A" },
  { source: "Sector · Energy",     pct:  8.5, color: "#F2C94C" },
  { source: "Rates · Duration",    pct: 10.2, color: "#2BAF7E" },
  { source: "FX · DXY",            pct:  7.8, color: "#3DD39A" },
  { source: "Idiosyncratic",       pct:  8.0, color: "#A8B4D4" },
];

const STRESS_SCENARIOS = [
  { id: "2008",    name: "GFC 2008",              pnl: -18.2, prob: "TAIL",   worst: "XLF",  note: "Credit + growth collapse; financials dominant" },
  { id: "2013",    name: "Taper Tantrum",         pnl:  -6.8, prob: "MOD",    worst: "TLT",  note: "Duration shock on long treasuries" },
  { id: "2015",    name: "Oil Crash 2015",        pnl:  -4.2, prob: "MOD",    worst: "XLE",  note: "Energy exporters under pressure" },
  { id: "2020",    name: "COVID Mar'20",          pnl: -12.5, prob: "TAIL",   worst: "IWM",  note: "Risk-off everything; gold rallies" },
  { id: "2022",    name: "Inflation Shock 2022",  pnl:  -8.8, prob: "HIGH",   worst: "QQQ",  note: "Duration + growth repricing" },
  { id: "2018",    name: "Trade War Q4 2018",     pnl:  -5.4, prob: "MOD",    worst: "MCHI", note: "China + tech drawdown" },
  { id: "DXY_10",  name: "USD +10% Rally",        pnl:  -3.2, prob: "MOD",    worst: "EEM",  note: "EM assets under pressure from strong dollar" },
  { id: "RATES",   name: "Fed Cuts 200bp Fast",   pnl:   8.5, prob: "UPSIDE", worst: "HYG",  note: "Long duration rallies hard" },
];

// 60-month back-test series
function generateSeries(startBase, driftPct, volPct, seedBias) {
  const n = 60;
  const out = [startBase];
  let rnd = seedBias;
  for (let i = 1; i < n; i++) {
    rnd = (rnd * 9301 + 49297) % 233280;
    const noise = (rnd / 233280 - 0.5) * volPct;
    out.push(out[i-1] * (1 + driftPct/12 + noise));
  }
  return out;
}
const BACKTEST_OPTIMIZED = generateSeries(100, 0.098, 0.032, 0.42);
const BACKTEST_PRIOR     = generateSeries(100, 0.082, 0.036, 0.58);
const BACKTEST_BENCH     = generateSeries(100, 0.068, 0.028, 0.73);

// Monte Carlo
function mcPercentiles() {
  const months = 121;
  const startVal = 100;
  const annMean = 0.098;
  const annVol = 0.108;
  const mMu  = annMean / 12;
  const mSig = annVol / Math.sqrt(12);
  const zs = [-1.645, -0.674, 0, 0.674, 1.645];
  return zs.map(z => {
    const out = [startVal];
    for (let t = 1; t < months; t++) {
      const v = startVal * Math.exp((mMu - mSig*mSig/2) * t + mSig * z * Math.sqrt(t));
      out.push(v);
    }
    return out;
  });
}
const MONTE_CARLO = {
  percentiles: mcPercentiles(),
  probLoss: 18.4,
  p5:  118,
  p50: 241,
  p95: 489,
};

const ADVISOR_INSIGHTS = [
  {
    severity: "INFO",
    tag: "Factor Tilt",
    title: "Quality factor 13% above target",
    body: "Portfolio quality exposure (β=0.68) drifted above the 0.60 target. Driven by overweight in QQQ and XLF. Consider trimming QQQ by 80bp to realign factor budget.",
    actions: ["Apply rebalance", "Ignore"],
  },
  {
    severity: "WARN",
    tag: "Concentration",
    title: "SPY + QQQ = 24.7% of book",
    body: "US large-cap exposure approaching 25% soft ceiling. Current macro regime (LATE_CYCLE) historically penalizes growth concentration. Monitor closely.",
    actions: ["Add position sizing rule", "View scenario"],
  },
  {
    severity: "CRIT",
    tag: "Regime Mismatch",
    title: "Duration heavy into rate volatility",
    body: "TLT + IEF = 12.3% while rate vol (MOVE index) sits at +0.9σ above trailing mean. Expected P&L contribution turns negative if 10Y moves +50bp. Hedge via TIPS or cut duration.",
    actions: ["Rebalance to TIPS", "View stress"],
  },
  {
    severity: "INFO",
    tag: "Optimization",
    title: "Turnover well within budget",
    body: "Rebalance trades total 14.2% of book vs 40% annual limit. Ample room for future tilts without breaching turnover constraint.",
    actions: ["Dismiss"],
  },
  {
    severity: "WARN",
    tag: "Liquidity",
    title: "BNDX takes 2.8 days to exit",
    body: "At current book size and ADV, full exit of international bond position would require 2.8 trading days. Acceptable but logged in liquidity profile.",
    actions: ["View liquidity profile"],
  },
];

Object.assign(window, {
  REGIME_CONTEXT, UNIVERSE, ASSET_CLASSES,
  CALIBRATION_DEFAULTS, PRESETS, CASCADE_PHASES,
  OPTIMIZED_WEIGHTS, FACTOR_EXPOSURES, RISK_DECOMP,
  STRESS_SCENARIOS, BACKTEST_OPTIMIZED, BACKTEST_PRIOR, BACKTEST_BENCH,
  MONTE_CARLO, ADVISOR_INSIGHTS,
});
