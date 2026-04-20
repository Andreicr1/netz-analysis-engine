// Macro page data — regimes, assets, economic indicators, news

// --- Seeded random ---
function seededM(seed) {
  let s = seed;
  return () => { s = (s * 1664525 + 1013904223) % 4294967296; return s / 4294967296; };
}

// --- Regime matrix: history trail (growth × inflation) ---
// Axes: growth (-1 contraction .. +1 expansion), inflation (-1 disinflation .. +1 accelerating)
const REGIME_TRAIL = (() => {
  const rand = seededM(77);
  const out = [];
  // walk through quadrants over 18 months
  const anchors = [
    { m: "2024-11", g: -0.3, i: 0.6, label: "Stagflation" },
    { m: "2025-01", g: -0.1, i: 0.5, label: "Stagflation" },
    { m: "2025-03", g: 0.15, i: 0.35, label: "Overheating" },
    { m: "2025-05", g: 0.35, i: 0.25, label: "Overheating" },
    { m: "2025-07", g: 0.45, i: 0.05, label: "Goldilocks" },
    { m: "2025-09", g: 0.55, i: -0.1, label: "Goldilocks" },
    { m: "2025-11", g: 0.40, i: -0.05, label: "Goldilocks" },
    { m: "2026-01", g: 0.25, i: 0.15, label: "Overheating" },
    { m: "2026-03", g: 0.18, i: 0.28, label: "Overheating" },
  ];
  return anchors;
})();

const CURRENT_REGIME = { g: 0.22, i: 0.32, label: "Overheating", month: "Apr 2026" };

// --- Cross-asset universe: sector, ticker, name, region, last, chg1d, chg1w, chg1m, chg3m, chg6m, chgYTD, chg1y, chg5y ---
function buildAsset(sector, ticker, name, region, seed) {
  const rand = seededM(seed);
  const last = Math.round((10 + rand() * 450) * 100) / 100;
  const ch = () => Math.round((-4 + rand() * 10) * 100) / 100;
  const chY = () => Math.round((-20 + rand() * 60) * 10) / 10;
  return {
    sector, ticker, name, region, last,
    chg1d: ch(), chg1w: ch(), chg1m: ch() + 0.4, chg3m: Math.round((-10 + rand() * 24) * 10) / 10,
    chgYTD: chY(), chg1y: chY(), chg5y: Math.round((-30 + rand() * 180) * 10) / 10,
    // 60 bar synthetic series (5Y monthly)
    series: (() => {
      const n = 60;
      let v = 100;
      const drift = (rand() - 0.4) * 0.008;
      const vol = 0.02 + rand() * 0.04;
      const out = [v];
      for (let i = 1; i < n; i++) {
        const shock = (rand() - 0.5) * vol;
        v = Math.max(20, v * (1 + drift + shock));
        out.push(v);
      }
      return out;
    })(),
  };
}

const MACRO_ASSETS = [
  // RATES (sovereign yields, %)
  buildAsset("RATES", "US02Y", "US 2Y Treasury",      "US",     101),
  buildAsset("RATES", "US10Y", "US 10Y Treasury",     "US",     102),
  buildAsset("RATES", "US30Y", "US 30Y Treasury",     "US",     103),
  buildAsset("RATES", "DE10Y", "German Bund 10Y",     "EU",     104),
  buildAsset("RATES", "JP10Y", "JGB 10Y",             "ASIA",   105),
  buildAsset("RATES", "BR10Y", "Brazil 10Y NTN-F",    "BR",     106),
  // CURVES
  buildAsset("RATES", "US2s10s", "US 2s10s Curve",    "US",     107),
  buildAsset("RATES", "US5s30s", "US 5s30s Curve",    "US",     108),
  // FX (vs USD)
  buildAsset("FX", "DXY",    "US Dollar Index",       "GLOBAL", 201),
  buildAsset("FX", "EURUSD", "Euro / US Dollar",      "EU",     202),
  buildAsset("FX", "USDJPY", "US Dollar / Yen",       "ASIA",   203),
  buildAsset("FX", "GBPUSD", "Pound / US Dollar",     "EU",     204),
  buildAsset("FX", "USDBRL", "USD / Brazilian Real",  "BR",     205),
  buildAsset("FX", "USDCNY", "USD / Yuan",            "ASIA",   206),
  // EQUITIES
  buildAsset("EQUITY", "SPX",   "S&P 500",            "US",     301),
  buildAsset("EQUITY", "NDX",   "Nasdaq 100",         "US",     302),
  buildAsset("EQUITY", "RTY",   "Russell 2000",       "US",     303),
  buildAsset("EQUITY", "SX5E",  "Euro Stoxx 50",      "EU",     304),
  buildAsset("EQUITY", "NKY",   "Nikkei 225",         "ASIA",   305),
  buildAsset("EQUITY", "HSI",   "Hang Seng",          "ASIA",   306),
  buildAsset("EQUITY", "IBOV",  "Ibovespa",           "BR",     307),
  // COMMODITIES
  buildAsset("COMMODITY", "CL", "WTI Crude Oil",      "GLOBAL", 401),
  buildAsset("COMMODITY", "CO", "Brent Crude",        "GLOBAL", 402),
  buildAsset("COMMODITY", "XAU", "Gold",              "GLOBAL", 403),
  buildAsset("COMMODITY", "XAG", "Silver",            "GLOBAL", 404),
  buildAsset("COMMODITY", "HG", "Copper",             "GLOBAL", 405),
  buildAsset("COMMODITY", "IO", "Iron Ore 62%",       "GLOBAL", 406),
  buildAsset("COMMODITY", "S",  "Soybeans",           "GLOBAL", 407),
  // CREDIT (spreads, bps)
  buildAsset("CREDIT", "CDX IG",  "CDX Investment Grade",   "US",     501),
  buildAsset("CREDIT", "CDX HY",  "CDX High Yield",          "US",     502),
  buildAsset("CREDIT", "iTraxx",  "iTraxx Europe Main",      "EU",     503),
  buildAsset("CREDIT", "EMBI",    "JPM EMBI+ Spread",        "GLOBAL", 504),
  buildAsset("CREDIT", "BR EMBI", "Brazil EMBI",             "BR",     505),
  // SENTIMENT
  buildAsset("SENTIMENT", "VIX",     "CBOE Volatility Index",  "US",   601),
  buildAsset("SENTIMENT", "MOVE",    "MOVE (Rates Vol)",       "US",   602),
  buildAsset("SENTIMENT", "SKEW",    "CBOE SKEW",              "US",   603),
  buildAsset("SENTIMENT", "PUT/CALL","Equity Put/Call",        "US",   604),
  buildAsset("SENTIMENT", "FGI",     "Fear & Greed Index",     "GLOBAL", 605),
];

// Override specific tickers with meaningful "last" values
const OVERRIDES = {
  US02Y: 4.18, US10Y: 4.42, US30Y: 4.58, DE10Y: 2.61, JP10Y: 1.15, BR10Y: 11.82,
  US2s10s: 24, US5s30s: 18,
  DXY: 103.48, EURUSD: 1.086, USDJPY: 152.4, GBPUSD: 1.268, USDBRL: 5.12, USDCNY: 7.24,
  SPX: 5482, NDX: 19240, RTY: 2186, SX5E: 5094, NKY: 39820, HSI: 17640, IBOV: 128740,
  CL: 78.42, CO: 82.18, XAU: 2384, XAG: 28.94, HG: 4.52, IO: 108.2, S: 1184,
  "CDX IG": 52, "CDX HY": 322, "iTraxx": 58, "EMBI": 348, "BR EMBI": 228,
  VIX: 14.2, MOVE: 91, SKEW: 142, "PUT/CALL": 0.82, FGI: 62,
};
MACRO_ASSETS.forEach(a => { if (OVERRIDES[a.ticker] != null) a.last = OVERRIDES[a.ticker]; });

// --- Macro news ---
const MACRO_NEWS = [
  { id: "mn1", src: "BLOOMBERG", time: "14:22", tag: "FED", title: "Fed officials split on timing of next cut as services inflation stays sticky", tickers: ["US10Y", "US02Y"] },
  { id: "mn2", src: "REUTERS",   time: "13:58", tag: "DATA", title: "US CPI 3.4% YoY vs 3.2% consensus — shelter prints hotter", tickers: ["TLT", "US10Y", "DXY"] },
  { id: "mn3", src: "FT",        time: "13:41", tag: "ECB", title: "Lagarde: 'June cut conditional on wage data'", tickers: ["EURUSD", "DE10Y"] },
  { id: "mn4", src: "VALOR",     time: "13:20", tag: "BCB", title: "COPOM mantém Selic 10,50% e sinaliza pausa prolongada", tickers: ["BR10Y", "USDBRL"] },
  { id: "mn5", src: "BLOOMBERG", time: "12:44", tag: "BOJ", title: "BoJ minutes hint at gradual tightening — JGB yields test 1.2%", tickers: ["JP10Y", "USDJPY"] },
  { id: "mn6", src: "WSJ",       time: "12:18", tag: "GEO", title: "Middle East tensions lift Brent; gold extends record pace", tickers: ["CO", "XAU"] },
  { id: "mn7", src: "REUTERS",   time: "11:52", tag: "CN", title: "China PMI back in expansion — copper catches bid", tickers: ["HG", "HSI", "USDCNY"] },
  { id: "mn8", src: "BLOOMBERG", time: "11:30", tag: "CREDIT", title: "IG spreads tighten to 18-month lows as IG supply absorbed", tickers: ["CDX IG", "iTraxx"] },
  { id: "mn9", src: "FT",        time: "10:58", tag: "EM", title: "EMBI narrows 12bps this week on disinflation optimism", tickers: ["EMBI", "BR EMBI"] },
  { id: "mn10", src: "REUTERS", time: "10:22", tag: "EQUITY", title: "US tech earnings surprise — cloud capex accelerating", tickers: ["NDX", "SPX"] },
];

// --- Central bank calendar ---
const CB_CALENDAR = [
  { cb: "FOMC", date: "Apr 30", currentRate: "5.25 — 5.50", mktImplied: "5.00 — 5.25", change: "−25bps", prob: 68 },
  { cb: "ECB",  date: "May 07", currentRate: "3.75",         mktImplied: "3.50",         change: "−25bps", prob: 81 },
  { cb: "BOE",  date: "May 09", currentRate: "4.75",         mktImplied: "4.75",         change: "HOLD",   prob: 62 },
  { cb: "BOJ",  date: "May 01", currentRate: "0.25",         mktImplied: "0.25",         change: "HOLD",   prob: 88 },
  { cb: "COPOM",date: "May 08", currentRate: "10.50",        mktImplied: "10.50",        change: "HOLD",   prob: 72 },
  { cb: "PBOC", date: "May 20", currentRate: "3.35",         mktImplied: "3.25",         change: "−10bps", prob: 58 },
];

// --- Economic indicators (pulse cards) ---
const ECON_PULSES = [
  { name: "US CPI",       period: "Mar",  actual: 3.4,   consensus: 3.2, prior: 3.2, unit: "%", surprise: "hot" },
  { name: "US NFP",       period: "Mar",  actual: 303,   consensus: 214, prior: 275, unit: "k",  surprise: "hot" },
  { name: "EU CPI",       period: "Mar",  actual: 2.4,   consensus: 2.5, prior: 2.6, unit: "%", surprise: "cool" },
  { name: "China PMI",    period: "Mar",  actual: 50.8,  consensus: 50.1, prior: 49.1, unit: "",  surprise: "hot" },
  { name: "BR IPCA",      period: "Mar",  actual: 3.93,  consensus: 3.85, prior: 4.50, unit: "%", surprise: "hot" },
  { name: "JP Core CPI",  period: "Mar",  actual: 2.6,   consensus: 2.7, prior: 2.8, unit: "%", surprise: "cool" },
  { name: "US PPI",       period: "Mar",  actual: 2.1,   consensus: 2.2, prior: 1.6, unit: "%", surprise: "cool" },
  { name: "US Retail",    period: "Mar",  actual: 0.7,   consensus: 0.4, prior: 0.6, unit: "%", surprise: "hot" },
];

// --- Liquidity gauge (global conditions) ---
// -1 tightest ... +1 loosest
const LIQUIDITY_HISTORY = [
  -0.12, -0.18, -0.24, -0.30, -0.28, -0.22, -0.15, -0.10,
  -0.05, 0.02, 0.08, 0.14, 0.22, 0.30, 0.28, 0.24,
  0.20, 0.18, 0.15, 0.12, 0.08, 0.04, 0.00, -0.05,
];
const LIQUIDITY_NOW = -0.05;

Object.assign(window, {
  REGIME_TRAIL, CURRENT_REGIME, MACRO_ASSETS, MACRO_NEWS, CB_CALENDAR, ECON_PULSES,
  LIQUIDITY_HISTORY, LIQUIDITY_NOW,
});
