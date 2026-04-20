// Mock data for the Netz Terminal Live Workbench
// Portfolios, watchlist, holdings, news, alerts, etc.

const PORTFOLIOS = [
  { id: "netz-way-mod", display_name: "Netz Way Moderate", profile: "MODERATE", state: "live", status: "TRADING", aum: 84_215_430 },
  { id: "netz-way-cons", display_name: "Netz Way Conservative", profile: "CONSERVATIVE", state: "live", status: "TRADING", aum: 42_880_120 },
  { id: "netz-way-agg", display_name: "Netz Way Aggressive", profile: "AGGRESSIVE", state: "live", status: "TRADING", aum: 31_540_900 },
  { id: "netz-vetta-usd", display_name: "Vetta Global USD", profile: "GLOBAL", state: "live", status: "TRADING", aum: 127_402_000 },
  { id: "netz-ntz-fic", display_name: "NTZ FIC Multimercado", profile: "HEDGE", state: "draft", status: "DRAFT", aum: 0 },
];

const INSTRUMENTS = [
  // ticker, name, weight, target_weight, sector, price, day_chg_pct
  { ticker: "AGG",   name: "iShares Core US Aggregate Bond",      weight: 0.158, target: 0.180, sector: "FIXED INCOME", price: 98.42,  dayPct: -0.08 },
  { ticker: "VTI",   name: "Vanguard Total Stock Market",         weight: 0.183, target: 0.150, sector: "EQUITY US",    price: 287.14, dayPct:  0.42 },
  { ticker: "VEA",   name: "Vanguard Developed Markets",          weight: 0.092, target: 0.100, sector: "EQUITY DM",    price: 52.18,  dayPct:  0.23 },
  { ticker: "VWO",   name: "Vanguard Emerging Markets",           weight: 0.061, target: 0.080, sector: "EQUITY EM",    price: 46.87,  dayPct: -0.54 },
  { ticker: "GLD",   name: "SPDR Gold Shares",                    weight: 0.084, target: 0.060, sector: "COMMODITY",    price: 218.44, dayPct:  0.91 },
  { ticker: "TLT",   name: "iShares 20+ Year Treasury",           weight: 0.038, target: 0.060, sector: "FIXED INCOME", price: 91.06,  dayPct: -0.33 },
  { ticker: "IEF",   name: "iShares 7-10 Year Treasury",          weight: 0.060, target: 0.060, sector: "FIXED INCOME", price: 94.21,  dayPct: -0.18 },
  { ticker: "LQD",   name: "iShares iBoxx Investment Grade",      weight: 0.070, target: 0.070, sector: "FIXED INCOME", price: 108.54, dayPct: -0.11 },
  { ticker: "HYG",   name: "iShares iBoxx High Yield",            weight: 0.040, target: 0.040, sector: "FIXED INCOME", price: 78.16,  dayPct:  0.04 },
  { ticker: "VNQ",   name: "Vanguard Real Estate",                weight: 0.048, target: 0.050, sector: "REAL ESTATE",  price: 88.92,  dayPct:  0.67 },
  { ticker: "QQQ",   name: "Invesco QQQ Trust",                   weight: 0.096, target: 0.070, sector: "EQUITY US",    price: 488.30, dayPct:  0.88 },
  { ticker: "XLE",   name: "Energy Select Sector SPDR",           weight: 0.010, target: 0.030, sector: "EQUITY US",    price: 94.75,  dayPct: -1.12 },
  { ticker: "XLF",   name: "Financial Select Sector SPDR",        weight: 0.040, target: 0.030, sector: "EQUITY US",    price: 44.62,  dayPct:  0.21 },
  { ticker: "EMB",   name: "iShares JP Morgan EM Bond",           weight: 0.020, target: 0.020, sector: "FIXED INCOME", price: 89.41,  dayPct: -0.09 },
];

const ALERTS = [
  { id: "a1", severity: "critical", source: "DRIFT",  title: "XLE underweight by 0.6pp", time: "14:22:08", portfolio: "Way Moderate" },
  { id: "a2", severity: "warning",  source: "DRIFT",  title: "GLD overweight by 0.7pp",  time: "14:21:52", portfolio: "Way Moderate" },
  { id: "a3", severity: "warning",  source: "MACRO",  title: "US CPI above consensus — 3.4% vs 3.2%", time: "13:58:12", portfolio: "—" },
  { id: "a4", severity: "info",     source: "DD",     title: "NTZ FIC — IC approval pending", time: "13:45:00", portfolio: "—" },
  { id: "a5", severity: "info",     source: "NEWS",   title: "FOMC minutes scheduled 18:00 UTC", time: "13:30:00", portfolio: "—" },
  { id: "a6", severity: "warning",  source: "RISK",   title: "Vetta Global USD — VaR ↑ 1.8σ", time: "13:12:44", portfolio: "Vetta Global" },
];

const TRADES = [
  { id: "t1", side: "BUY",  ticker: "VTI", qty: 1_200, price: 286.84, time: "14:18:02", status: "FILLED" },
  { id: "t2", side: "SELL", ticker: "GLD", qty:   300, price: 217.90, time: "14:16:45", status: "FILLED" },
  { id: "t3", side: "BUY",  ticker: "TLT", qty:   800, price:  91.22, time: "14:12:11", status: "FILLED" },
  { id: "t4", side: "BUY",  ticker: "XLE", qty:   450, price:  95.11, time: "14:05:33", status: "PARTIAL" },
  { id: "t5", side: "SELL", ticker: "QQQ", qty:    90, price: 487.66, time: "13:58:04", status: "FILLED" },
];

const NEWS = [
  { id: "n1", src: "REUTERS",   time: "14:22", title: "Fed officials signal patience on rate cuts as services inflation stays sticky", tickers: ["TLT", "IEF"] },
  { id: "n2", src: "BLOOMBERG", time: "14:18", title: "Brent crude slides 1.4% on OPEC+ output reports",                                tickers: ["XLE"] },
  { id: "n3", src: "FT",        time: "14:07", title: "US tech earnings surprise — Alphabet, Meta beat cloud expectations",             tickers: ["QQQ", "VTI"] },
  { id: "n4", src: "VALOR",     time: "13:52", title: "COPOM mantém Selic em 10,50% e sinaliza pausa prolongada",                       tickers: [] },
  { id: "n5", src: "BLOOMBERG", time: "13:41", title: "EM local-currency debt sees $2.1B weekly inflows — biggest since Nov",            tickers: ["EMB", "VWO"] },
  { id: "n6", src: "REUTERS",   time: "13:30", title: "ECB's Lagarde: 'June cut remains conditional on wage data'",                      tickers: ["VEA"] },
  { id: "n7", src: "WSJ",       time: "13:14", title: "Gold extends rally as central bank buying hits record pace",                     tickers: ["GLD"] },
  { id: "n8", src: "BLOOMBERG", time: "12:58", title: "Investment-grade spreads tighten to 18-month lows",                               tickers: ["LQD"] },
];

const MACRO_REGIMES = [
  { region: "US",     stress: 0.42, trend: "↗", label: "Mid-cycle expansion",     color: "warn" },
  { region: "EU",     stress: 0.58, trend: "↗", label: "Late-cycle / disinflat.",  color: "warn" },
  { region: "CN",     stress: 0.71, trend: "→", label: "Stimulus-driven rebound",  color: "alert" },
  { region: "BR",     stress: 0.33, trend: "↘", label: "Easing cycle / goldilocks", color: "ok" },
  { region: "JP",     stress: 0.28, trend: "→", label: "Policy normalization",     color: "ok" },
  { region: "EM-xCN", stress: 0.48, trend: "↗", label: "Mixed — divergent flows",   color: "warn" },
];

// Generate historical candles for a given ticker seed.
function genCandles(seed, count = 90, basePrice = 100) {
  const bars = [];
  let p = basePrice;
  // Simple deterministic PRNG
  let s = seed;
  const rand = () => { s = (s * 1664525 + 1013904223) % 4294967296; return s / 4294967296; };
  const now = Math.floor(Date.now() / 1000);
  for (let i = count - 1; i >= 0; i--) {
    const drift = (rand() - 0.48) * 0.018;
    const vol = 0.008 + rand() * 0.012;
    const open = p;
    const close = open * (1 + drift);
    const high = Math.max(open, close) * (1 + rand() * vol);
    const low = Math.min(open, close) * (1 - rand() * vol);
    bars.push({
      t: now - i * 86400,
      o: open, h: high, l: low, c: close,
      v: Math.floor(1_000_000 + rand() * 9_000_000),
    });
    p = close;
  }
  return bars;
}

// Seed hash per ticker so each ticker has stable synthetic history
function hash(str) { let h = 0; for (const c of str) h = (h * 31 + c.charCodeAt(0)) | 0; return Math.abs(h) || 1; }

const HISTORICAL = Object.fromEntries(
  INSTRUMENTS.map(i => [i.ticker, genCandles(hash(i.ticker), 120, i.price)])
);

// Sparkline-length series (30 bars) for watchlist rows
const SPARKS = Object.fromEntries(
  INSTRUMENTS.map(i => [i.ticker, genCandles(hash(i.ticker) + 7, 30, i.price).map(b => b.c)])
);

Object.assign(window, {
  PORTFOLIOS, INSTRUMENTS, ALERTS, TRADES, NEWS, MACRO_REGIMES,
  HISTORICAL, SPARKS, genCandles, hash,
});
