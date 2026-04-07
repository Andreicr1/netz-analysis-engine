<!--
  ContagionNetworkGraph — "The Contagion Map"
  Force-directed graph: Central asset node → Manager nodes → Fund satellite nodes.
  Reverse Lookup visualization: "Who holds NVIDIA?"
-->
<script lang="ts">
  import { ChartContainer } from "@investintell/ui/charts";

  // ── Design System hex (Canvas) ──
  const C = {
    brand: "#0177fb",
    green: "#11ec79",
    red: "#fc1a1a",
    textBase: "#d9d9d9",
    muted: "#71717a",
    grid: "#404149",
  } as const;

  // ── Sample Data: "Who holds NVDA?" ──
  interface GraphNode {
    name: string;
    category: number; // 0=asset, 1=manager, 2=fund
    symbolSize: number;
    value: number;
    label?: { show: boolean };
  }

  interface GraphLink {
    source: string;
    target: string;
    value?: number;
  }

  const CATEGORIES = [
    { name: "Asset" },
    { name: "Manager" },
    { name: "Fund" },
  ];

  const nodes: GraphNode[] = [
    // Central Asset
    { name: "NVDA", category: 0, symbolSize: 60, value: 3_200_000_000_000, label: { show: true } },

    // Managers (intermediate)
    { name: "Vanguard", category: 1, symbolSize: 40, value: 285_000_000_000, label: { show: true } },
    { name: "BlackRock", category: 1, symbolSize: 38, value: 260_000_000_000, label: { show: true } },
    { name: "State Street", category: 1, symbolSize: 30, value: 145_000_000_000, label: { show: true } },
    { name: "Fidelity", category: 1, symbolSize: 32, value: 178_000_000_000, label: { show: true } },
    { name: "Capital Research", category: 1, symbolSize: 28, value: 98_000_000_000, label: { show: true } },
    { name: "T. Rowe Price", category: 1, symbolSize: 24, value: 62_000_000_000, label: { show: true } },
    { name: "Geode Capital", category: 1, symbolSize: 22, value: 48_000_000_000, label: { show: true } },

    // Funds (satellites)
    { name: "Vanguard 500 Index", category: 2, symbolSize: 14, value: 95_000_000_000 },
    { name: "Vanguard Total Stock", category: 2, symbolSize: 13, value: 82_000_000_000 },
    { name: "Vanguard Growth Index", category: 2, symbolSize: 10, value: 45_000_000_000 },
    { name: "iShares Core S&P 500", category: 2, symbolSize: 15, value: 110_000_000_000 },
    { name: "iShares MSCI USA", category: 2, symbolSize: 9, value: 32_000_000_000 },
    { name: "BlackRock Equity Div", category: 2, symbolSize: 8, value: 18_000_000_000 },
    { name: "SPDR S&P 500 ETF", category: 2, symbolSize: 16, value: 120_000_000_000 },
    { name: "State Street Equity", category: 2, symbolSize: 7, value: 12_000_000_000 },
    { name: "Fidelity 500 Index", category: 2, symbolSize: 12, value: 65_000_000_000 },
    { name: "Fidelity Contrafund", category: 2, symbolSize: 11, value: 55_000_000_000 },
    { name: "Fidelity Growth Co", category: 2, symbolSize: 9, value: 38_000_000_000 },
    { name: "Growth Fund of America", category: 2, symbolSize: 10, value: 48_000_000_000 },
    { name: "Capital World G&I", category: 2, symbolSize: 8, value: 24_000_000_000 },
    { name: "T. Rowe Price Growth", category: 2, symbolSize: 9, value: 35_000_000_000 },
    { name: "T. Rowe Price Blue Chip", category: 2, symbolSize: 8, value: 22_000_000_000 },
    { name: "Geode Capital S&P 500", category: 2, symbolSize: 10, value: 42_000_000_000 },
  ];

  const links: GraphLink[] = [
    // Manager → Asset
    { source: "Vanguard", target: "NVDA", value: 285 },
    { source: "BlackRock", target: "NVDA", value: 260 },
    { source: "State Street", target: "NVDA", value: 145 },
    { source: "Fidelity", target: "NVDA", value: 178 },
    { source: "Capital Research", target: "NVDA", value: 98 },
    { source: "T. Rowe Price", target: "NVDA", value: 62 },
    { source: "Geode Capital", target: "NVDA", value: 48 },

    // Fund → Manager
    { source: "Vanguard 500 Index", target: "Vanguard" },
    { source: "Vanguard Total Stock", target: "Vanguard" },
    { source: "Vanguard Growth Index", target: "Vanguard" },
    { source: "iShares Core S&P 500", target: "BlackRock" },
    { source: "iShares MSCI USA", target: "BlackRock" },
    { source: "BlackRock Equity Div", target: "BlackRock" },
    { source: "SPDR S&P 500 ETF", target: "State Street" },
    { source: "State Street Equity", target: "State Street" },
    { source: "Fidelity 500 Index", target: "Fidelity" },
    { source: "Fidelity Contrafund", target: "Fidelity" },
    { source: "Fidelity Growth Co", target: "Fidelity" },
    { source: "Growth Fund of America", target: "Capital Research" },
    { source: "Capital World G&I", target: "Capital Research" },
    { source: "T. Rowe Price Growth", target: "T. Rowe Price" },
    { source: "T. Rowe Price Blue Chip", target: "T. Rowe Price" },
    { source: "Geode Capital S&P 500", target: "Geode Capital" },
  ];

  function formatB(val: number): string {
    if (val >= 1e12) return `$${(val / 1e12).toFixed(1)}T`;
    if (val >= 1e9) return `$${(val / 1e9).toFixed(1)}B`;
    return `$${(val / 1e6).toFixed(0)}M`;
  }

  const CATEGORY_COLORS = [C.brand, C.green, "#a78bfa"];

  const option = $derived.by(() => ({
    backgroundColor: "transparent",
    textStyle: { fontFamily: "Urbanist" },
    animation: true,
    animationDuration: 1200,
    animationEasingUpdate: "quinticInOut",
    toolbox: { show: false },
    tooltip: {
      trigger: "item",
      confine: true,
      backgroundColor: "#1a1b20",
      borderColor: C.grid,
      textStyle: { color: C.textBase, fontFamily: "Urbanist", fontSize: 12 },
      formatter: (p: any) => {
        if (p.dataType === "edge") {
          return `${p.data.source} \u2192 ${p.data.target}`;
        }
        const cat = CATEGORIES[p.data.category]?.name ?? "Unknown";
        const val = p.data.value;
        return [
          `<b style="color:#fff">${p.name}</b>`,
          `Type: ${cat}`,
          val ? `Market Value: <b>${formatB(val)}</b>` : "",
        ].filter(Boolean).join("<br/>");
      },
    },
    legend: {
      data: CATEGORIES.map((c) => c.name),
      top: 8,
      left: "center",
      textStyle: { color: C.muted, fontFamily: "Urbanist", fontSize: 11 },
      itemWidth: 10,
      itemHeight: 10,
    },
    series: [
      {
        type: "graph",
        layout: "force",
        roam: true,
        draggable: true,
        categories: CATEGORIES.map((c, i) => ({
          name: c.name,
          itemStyle: { color: CATEGORY_COLORS[i] },
        })),
        data: nodes.map((n) => ({
          ...n,
          itemStyle: { color: CATEGORY_COLORS[n.category] },
          label: {
            show: n.label?.show ?? false,
            color: C.textBase,
            fontFamily: "Urbanist",
            fontSize: n.category === 0 ? 14 : n.category === 1 ? 11 : 9,
            fontWeight: n.category <= 1 ? "bold" : "normal",
            position: "bottom" as const,
          },
        })),
        links: links.map((l) => ({
          ...l,
          lineStyle: {
            color: C.grid,
            opacity: 0.4,
            curveness: 0.3,
            width: l.value ? Math.max(1, Math.min(3, l.value / 100)) : 1,
          },
        })),
        force: {
          repulsion: 400,
          edgeLength: [50, 200],
          gravity: 0.1,
          layoutAnimation: true,
        },
        emphasis: {
          focus: "adjacency",
          lineStyle: { opacity: 0.8, width: 3 },
          itemStyle: { borderColor: "#fff", borderWidth: 2 },
        },
        scaleLimit: { min: 0.4, max: 4 },
      },
    ],
  }));
</script>

<div class="cng-wrap">
  <h3 class="cng-title">
    Contagion Map — <span class="cng-highlight">Who holds NVDA?</span>
  </h3>
  <ChartContainer {option} height={540} ariaLabel="Contagion network graph showing NVDA holders" />
</div>

<style>
  .cng-wrap {
    background: #141519;
    border: 1px solid #404149;
    border-radius: 16px;
    padding: 20px;
  }

  .cng-title {
    font-family: "Urbanist", sans-serif;
    font-size: 15px;
    font-weight: 700;
    color: #d9d9d9;
    margin: 0 0 8px 4px;
  }

  .cng-highlight {
    color: #0177fb;
    font-weight: 700;
  }
</style>
