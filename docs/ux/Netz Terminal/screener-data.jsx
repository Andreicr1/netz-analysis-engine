// Screener data — synthetic universe of funds

const FUND_UNIVERSES = ["NETZ ELITE", "RECOMMENDED", "APPROVED", "WATCH", "ALL"];
const STRATEGIES = ["Multi-Asset", "Equity LS", "Macro", "Credit", "Fixed Income", "Event-Driven", "Quant", "Real Estate", "Commodities", "Structured"];
const GEOGRAPHIES = ["BR", "US", "EU", "JP", "CN", "LATAM", "EM", "GLOBAL"];
const MANAGERS = ["Vetta", "NTZ Capital", "Kapitalo", "Verde", "SPX", "Vinland", "Dahlia", "Occam", "Absolute", "Giant Steps", "Ibiúna", "Legacy", "Truxt", "Asa", "Kinea"];

function seeded(seed) {
  let s = seed;
  return () => { s = (s * 1664525 + 1013904223) % 4294967296; return s / 4294967296; };
}

const FUNDS = (() => {
  const rand = seeded(42);
  const out = [];
  const fundNames = [
    "Vetta Global Macro", "NTZ FIC Multimercado", "NTZ Equities Long Bias", "Kapitalo K10 FIC",
    "Verde AM 60 FIC", "SPX Nimitz", "Vinland Macro Plus", "Dahlia Total Return",
    "Occam Equity Hedge", "Absolute Vertex", "Giant Steps Zarathustra", "Ibiúna Hedge STH",
    "Legacy Capital FIC", "Truxt Long Bias", "Asa Hedge", "Kinea Chronos", "Vetta Vertex USD",
    "NTZ Credit Opportunities", "Kapitalo Zeta FIM", "Verde AM Scena", "SPX Lancer", "Vinland Long Bias",
    "Dahlia Global EM Debt", "Occam FI Plus", "Absolute Ações", "Giant Steps Gauss",
    "Ibiúna STH Long Bias", "Legacy Total Return", "Truxt Macro", "Asa Equities Long Bias",
    "Kinea Apollo", "Vetta EM Equities", "NTZ Real Estate FIP", "Kapitalo Kappa",
    "Verde AM Scena USD", "SPX Falcon", "Vinland Commodities", "Dahlia Credit FIC",
    "Occam Retorno Absoluto", "Absolute Hedge", "Giant Steps Riemann", "Ibiúna Long Short",
    "Legacy Capital Macro", "Truxt Equities LB", "Asa Long Short"
  ];
  for (let i = 0; i < fundNames.length; i++) {
    const name = fundNames[i];
    const manager = MANAGERS.find(m => name.startsWith(m)) ?? MANAGERS[Math.floor(rand() * MANAGERS.length)];
    const strategy = STRATEGIES[Math.floor(rand() * STRATEGIES.length)];
    const geo = GEOGRAPHIES[Math.floor(rand() * GEOGRAPHIES.length)];
    const universeRoll = rand();
    const universe = universeRoll > 0.85 ? "NETZ ELITE" : universeRoll > 0.6 ? "RECOMMENDED" : universeRoll > 0.3 ? "APPROVED" : "WATCH";
    const aum = Math.round((0.05 + rand() * 12) * 1000) / 10; // R$ Bi
    const ret1y = Math.round((-8 + rand() * 38) * 10) / 10;
    const ret3y = Math.round((-3 + rand() * 22) * 10) / 10;
    const ret10y = Math.round((2 + rand() * 15) * 10) / 10;
    const sharpe = Math.round((-0.2 + rand() * 2.5) * 100) / 100;
    const vol = Math.round((2 + rand() * 22) * 10) / 10;
    const ddMax = -Math.round((2 + rand() * 34) * 10) / 10;
    const te = Math.round((1 + rand() * 8) * 10) / 10;
    const expense = Math.round((0.3 + rand() * 2.2) * 100) / 100;
    const ddScore = Math.round(60 + rand() * 40);
    const elite = universe === "NETZ ELITE";
    const inception = 2006 + Math.floor(rand() * 18);
    out.push({
      id: "f" + (i + 1),
      ticker: name.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 5) + String(i).padStart(2, "0"),
      name,
      manager,
      strategy,
      geo,
      universe,
      elite,
      aum,               // Bi
      ret1y, ret3y, ret10y,
      sharpe, vol, ddMax, te, expense,
      ddScore,
      inception,
    });
  }
  return out;
})();

Object.assign(window, { FUND_UNIVERSES, STRATEGIES, GEOGRAPHIES, MANAGERS, FUNDS });
