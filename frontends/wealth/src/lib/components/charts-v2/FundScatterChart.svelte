<!--
  FundScatterChart — "Risk-Return Galaxy"
  Scatter: X = volatility_1y (%), Y = return_1y (%).
  Bubble size = AUM. Color = strategy category.
  Tooltip: Name, Strategy, Volatility, Return, Sharpe.
-->
<script lang="ts">
  import { ChartContainer } from "@investintell/ui/charts";

  // ── Design System hex (Canvas doesn't read CSS vars) ──
  const C = {
    brand: "#0177fb",
    green: "#11ec79",
    red: "#fc1a1a",
    textBase: "#d9d9d9",
    muted: "#71717a",
    grid: "#404149",
    bg: "transparent",
  } as const;

  const STRATEGY_COLORS: Record<string, string> = {
    Equities: "#0177fb",
    "Fixed Income": "#11ec79",
    "Multi-Asset": "#a78bfa",
    Alternatives: "#f59e0b",
    "Real Estate": "#14b8a6",
    Commodities: "#f97316",
    "Money Market": "#6b7280",
  };

  // ── Mock Data (high fidelity) ──
  interface FundPoint {
    name: string;
    strategy: string;
    volatility_1y: number;
    return_1y: number;
    aum: number;
    sharpe: number;
  }

  const MOCK_FUNDS: FundPoint[] = [
    { name: "Vanguard 500 Index", strategy: "Equities", volatility_1y: 0.162, return_1y: 0.243, aum: 820_000_000_000, sharpe: 1.50 },
    { name: "PIMCO Total Return", strategy: "Fixed Income", volatility_1y: 0.048, return_1y: 0.051, aum: 130_000_000_000, sharpe: 1.06 },
    { name: "Fidelity Contrafund", strategy: "Equities", volatility_1y: 0.178, return_1y: 0.281, aum: 140_000_000_000, sharpe: 1.58 },
    { name: "BlackRock Global Alloc", strategy: "Multi-Asset", volatility_1y: 0.102, return_1y: 0.127, aum: 60_000_000_000, sharpe: 1.25 },
    { name: "Bridgewater Pure Alpha", strategy: "Alternatives", volatility_1y: 0.088, return_1y: 0.094, aum: 45_000_000_000, sharpe: 1.07 },
    { name: "T. Rowe Price Growth", strategy: "Equities", volatility_1y: 0.201, return_1y: 0.312, aum: 85_000_000_000, sharpe: 1.55 },
    { name: "DoubleLine Total Return", strategy: "Fixed Income", volatility_1y: 0.038, return_1y: 0.042, aum: 48_000_000_000, sharpe: 1.10 },
    { name: "AQR Managed Futures", strategy: "Alternatives", volatility_1y: 0.135, return_1y: 0.082, aum: 15_000_000_000, sharpe: 0.61 },
    { name: "Invesco Real Estate", strategy: "Real Estate", volatility_1y: 0.145, return_1y: 0.068, aum: 12_000_000_000, sharpe: 0.47 },
    { name: "JPM Equity Premium", strategy: "Equities", volatility_1y: 0.121, return_1y: 0.185, aum: 35_000_000_000, sharpe: 1.53 },
    { name: "Wellington Balanced", strategy: "Multi-Asset", volatility_1y: 0.092, return_1y: 0.108, aum: 28_000_000_000, sharpe: 1.17 },
    { name: "Goldman Sachs EM Equity", strategy: "Equities", volatility_1y: 0.224, return_1y: 0.174, aum: 18_000_000_000, sharpe: 0.78 },
    { name: "Vanguard Short-Term Bond", strategy: "Fixed Income", volatility_1y: 0.022, return_1y: 0.048, aum: 72_000_000_000, sharpe: 2.18 },
    { name: "Man AHL Trend", strategy: "Alternatives", volatility_1y: 0.112, return_1y: 0.145, aum: 8_000_000_000, sharpe: 1.29 },
    { name: "Capital Research Growth", strategy: "Equities", volatility_1y: 0.185, return_1y: 0.268, aum: 210_000_000_000, sharpe: 1.45 },
    { name: "Nuveen Real Assets", strategy: "Real Estate", volatility_1y: 0.168, return_1y: -0.032, aum: 6_000_000_000, sharpe: -0.19 },
    { name: "State Street S&P 500 ETF", strategy: "Equities", volatility_1y: 0.160, return_1y: 0.240, aum: 450_000_000_000, sharpe: 1.50 },
    { name: "PIMCO Income", strategy: "Fixed Income", volatility_1y: 0.055, return_1y: 0.072, aum: 155_000_000_000, sharpe: 1.31 },
  ];

  /** Map AUM to bubble size (12-60px range). */
  function aumToSize(aum: number): number {
    const min = 6_000_000_000;
    const max = 820_000_000_000;
    const t = Math.min(1, Math.max(0, (aum - min) / (max - min)));
    return 12 + t * 48;
  }

  function formatB(val: number): string {
    if (val >= 1e12) return `$${(val / 1e12).toFixed(1)}T`;
    if (val >= 1e9) return `$${(val / 1e9).toFixed(1)}B`;
    return `$${(val / 1e6).toFixed(0)}M`;
  }

  // ── Build series per strategy (for legend) ──
  const strategies = [...new Set(MOCK_FUNDS.map((f) => f.strategy))];

  const series = strategies.map((strat) => ({
    name: strat,
    type: "scatter" as const,
    data: MOCK_FUNDS.filter((f) => f.strategy === strat).map((f) => ({
      value: [f.volatility_1y, f.return_1y, f.aum, f.sharpe],
      name: f.name,
      symbolSize: aumToSize(f.aum),
    })),
    itemStyle: {
      color: STRATEGY_COLORS[strat] ?? C.muted,
      opacity: 0.85,
    },
    emphasis: {
      itemStyle: { opacity: 1, borderColor: "#fff", borderWidth: 2 },
    },
  }));

  const option = $derived.by(() => ({
    backgroundColor: C.bg,
    textStyle: { fontFamily: "Urbanist", color: C.textBase },
    animation: true,
    animationDuration: 600,
    grid: { left: 60, right: 24, top: 56, bottom: 48, containLabel: false },
    legend: {
      top: 8,
      left: "center",
      textStyle: { color: C.muted, fontFamily: "Urbanist", fontSize: 11 },
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 16,
    },
    tooltip: {
      trigger: "item",
      confine: true,
      backgroundColor: "#1a1b20",
      borderColor: C.grid,
      textStyle: { color: C.textBase, fontFamily: "Urbanist", fontSize: 12 },
      formatter: (p: any) => {
        const [vol, ret, aum, sharpe] = p.value;
        return [
          `<b style="color:#fff">${p.name}</b>`,
          `<span style="color:${STRATEGY_COLORS[p.seriesName] ?? C.muted}">\u25CF</span> ${p.seriesName}`,
          `Volatility: <b>${(vol * 100).toFixed(1)}%</b>`,
          `Return: <b style="color:${ret >= 0 ? C.green : C.red}">${(ret * 100).toFixed(1)}%</b>`,
          `AUM: <b>${formatB(aum)}</b>`,
          `Sharpe: <b>${sharpe.toFixed(2)}</b>`,
        ].join("<br/>");
      },
    },
    toolbox: { show: false },
    xAxis: {
      name: "Volatility (1Y)",
      nameLocation: "center" as const,
      nameGap: 32,
      nameTextStyle: { color: C.muted, fontFamily: "Urbanist", fontSize: 11 },
      type: "value" as const,
      axisLabel: {
        color: C.muted,
        fontFamily: "Urbanist",
        fontSize: 10,
        formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
      },
      axisLine: { lineStyle: { color: C.grid } },
      splitLine: { lineStyle: { color: C.grid, type: "dashed" as const, opacity: 0.4 } },
    },
    yAxis: {
      name: "Return (1Y)",
      nameLocation: "center" as const,
      nameGap: 44,
      nameTextStyle: { color: C.muted, fontFamily: "Urbanist", fontSize: 11 },
      type: "value" as const,
      axisLabel: {
        color: C.muted,
        fontFamily: "Urbanist",
        fontSize: 10,
        formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
      },
      axisLine: { lineStyle: { color: C.grid } },
      splitLine: { lineStyle: { color: C.grid, type: "dashed" as const, opacity: 0.4 } },
    },
    series,
  }));
</script>

<div class="fsc-wrap">
  <h3 class="fsc-title">Risk-Return Galaxy</h3>
  <ChartContainer {option} height={480} ariaLabel="Fund risk-return scatter plot" />
</div>

<style>
  .fsc-wrap {
    background: #141519;
    border: 1px solid #404149;
    border-radius: 16px;
    padding: 20px;
  }

  .fsc-title {
    font-family: "Urbanist", sans-serif;
    font-size: 15px;
    font-weight: 700;
    color: #d9d9d9;
    margin: 0 0 8px 4px;
  }
</style>
