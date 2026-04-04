<!--
  SectorAllocationTransition — "Sector Deep Dive"
  Animated morph between Treemap and Sunburst.
  Toggle button switches series type; ECharts morphing handles the transition.
  Hierarchy: Sector → Industry → Holding.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import { echarts, initTheme } from "@investintell/ui/charts/echarts-setup";
  import { Layers, Circle } from "lucide-svelte";

  // ── Design System hex ──
  const C = {
    brand: "#0177fb",
    green: "#11ec79",
    red: "#fc1a1a",
    textBase: "#d9d9d9",
    muted: "#71717a",
    grid: "#404149",
  } as const;

  // Categorical palette (dark-friendly, high contrast)
  const SECTOR_PALETTE = [
    "#0177fb", "#11ec79", "#a78bfa", "#f59e0b", "#14b8a6",
    "#f97316", "#ec4899", "#6366f1", "#84cc16", "#ef4444",
    "#06b6d4",
  ];

  // ── Mock hierarchical data ──
  const HIERARCHY = [
    {
      name: "Technology",
      children: [
        {
          name: "Semiconductors",
          children: [
            { name: "NVIDIA Corp", value: 312 },
            { name: "AMD Inc", value: 85 },
            { name: "Broadcom Inc", value: 72 },
          ],
        },
        {
          name: "Software",
          children: [
            { name: "Microsoft Corp", value: 245 },
            { name: "Salesforce Inc", value: 48 },
            { name: "Adobe Inc", value: 42 },
          ],
        },
        {
          name: "Internet",
          children: [
            { name: "Alphabet Inc", value: 195 },
            { name: "Meta Platforms", value: 168 },
            { name: "Amazon.com", value: 210 },
          ],
        },
      ],
    },
    {
      name: "Healthcare",
      children: [
        {
          name: "Pharmaceuticals",
          children: [
            { name: "Eli Lilly", value: 145 },
            { name: "Novo Nordisk", value: 120 },
            { name: "Pfizer Inc", value: 52 },
          ],
        },
        {
          name: "Biotech",
          children: [
            { name: "Amgen Inc", value: 68 },
            { name: "Regeneron", value: 45 },
          ],
        },
        {
          name: "Med Devices",
          children: [
            { name: "Abbott Labs", value: 58 },
            { name: "Intuitive Surgical", value: 42 },
          ],
        },
      ],
    },
    {
      name: "Financials",
      children: [
        {
          name: "Banks",
          children: [
            { name: "JPMorgan Chase", value: 135 },
            { name: "Bank of America", value: 72 },
            { name: "Wells Fargo", value: 48 },
          ],
        },
        {
          name: "Asset Management",
          children: [
            { name: "BlackRock Inc", value: 38 },
            { name: "Charles Schwab", value: 32 },
          ],
        },
        {
          name: "Insurance",
          children: [
            { name: "Berkshire Hathaway", value: 180 },
            { name: "Progressive Corp", value: 28 },
          ],
        },
      ],
    },
    {
      name: "Energy",
      children: [
        {
          name: "Oil & Gas",
          children: [
            { name: "ExxonMobil", value: 95 },
            { name: "Chevron Corp", value: 72 },
          ],
        },
        {
          name: "Renewables",
          children: [
            { name: "NextEra Energy", value: 38 },
            { name: "Enphase Energy", value: 12 },
          ],
        },
      ],
    },
    {
      name: "Consumer",
      children: [
        {
          name: "Retail",
          children: [
            { name: "Costco Wholesale", value: 68 },
            { name: "Walmart Inc", value: 52 },
          ],
        },
        {
          name: "Beverages",
          children: [
            { name: "Coca-Cola Co", value: 42 },
            { name: "PepsiCo Inc", value: 38 },
          ],
        },
      ],
    },
    {
      name: "Industrials",
      children: [
        {
          name: "Aerospace",
          children: [
            { name: "RTX Corp", value: 35 },
            { name: "Lockheed Martin", value: 32 },
          ],
        },
        {
          name: "Machinery",
          children: [
            { name: "Caterpillar Inc", value: 28 },
            { name: "Deere & Co", value: 25 },
          ],
        },
      ],
    },
  ];

  // ── Color assignment: each top-level sector gets a palette color ──
  function colorize(data: any[], palette: string[]): any[] {
    return data.map((sector, i) => ({
      ...sector,
      itemStyle: { color: palette[i % palette.length] },
      children: sector.children?.map((industry: any) => ({
        ...industry,
        itemStyle: { color: palette[i % palette.length], opacity: 0.8 },
        children: industry.children?.map((holding: any) => ({
          ...holding,
          itemStyle: { color: palette[i % palette.length], opacity: 0.6 },
        })),
      })),
    }));
  }

  const coloredData = colorize(HIERARCHY, SECTOR_PALETTE);

  // ── Chart mode ──
  let mode = $state<"treemap" | "sunburst">("treemap");

  function toggle() {
    mode = mode === "treemap" ? "sunburst" : "treemap";
  }

  // ── Shared ECharts config parts ──
  const baseTextStyle = { fontFamily: "Urbanist", color: C.textBase };

  const tooltipConfig = {
    confine: true,
    backgroundColor: "#1a1b20",
    borderColor: C.grid,
    textStyle: { color: C.textBase, fontFamily: "Urbanist", fontSize: 12 },
  };

  function treemapOption() {
    return {
      backgroundColor: "transparent",
      textStyle: baseTextStyle,
      tooltip: tooltipConfig,
      toolbox: { show: false },
      series: [
        {
          type: "treemap",
          id: "sector-viz",
          animationDurationUpdate: 800,
          roam: false,
          breadcrumb: {
            show: true,
            left: 8,
            bottom: 8,
            itemStyle: { color: "#22232a", borderColor: C.grid, textStyle: { color: C.muted } },
          },
          label: {
            show: true,
            fontFamily: "Urbanist",
            fontSize: 11,
            color: "#fff",
            fontWeight: "bold",
          },
          upperLabel: {
            show: true,
            height: 24,
            fontFamily: "Urbanist",
            fontSize: 11,
            color: "#fff",
            fontWeight: "bold",
          },
          levels: [
            { itemStyle: { borderColor: C.grid, borderWidth: 2, gapWidth: 2 } },
            { itemStyle: { borderColor: C.grid, borderWidth: 1, gapWidth: 1 }, upperLabel: { show: true } },
            { itemStyle: { borderColor: C.grid, borderWidth: 0.5 }, label: { fontSize: 9 } },
          ],
          data: coloredData,
        },
      ],
    };
  }

  function sunburstOption() {
    return {
      backgroundColor: "transparent",
      textStyle: baseTextStyle,
      tooltip: tooltipConfig,
      toolbox: { show: false },
      series: [
        {
          type: "sunburst",
          id: "sector-viz",
          animationDurationUpdate: 800,
          radius: ["15%", "95%"],
          sort: undefined,
          emphasis: { focus: "ancestor" },
          label: {
            fontFamily: "Urbanist",
            fontSize: 10,
            color: "#fff",
            rotate: "tangential" as const,
            minAngle: 8,
          },
          itemStyle: {
            borderRadius: 4,
            borderWidth: 1,
            borderColor: "#141519",
          },
          levels: [
            {},
            { r0: "15%", r: "45%", label: { fontSize: 12, fontWeight: "bold" } },
            { r0: "45%", r: "72%", label: { fontSize: 10 } },
            { r0: "72%", r: "95%", label: { fontSize: 8, align: "right" } },
          ],
          data: coloredData,
        },
      ],
    };
  }

  // ── Direct chart management (morph requires same series id) ──
  let containerEl: HTMLDivElement | undefined = $state();
  let chart: ReturnType<typeof echarts.init> | undefined = $state();

  onMount(() => {
    if (!containerEl) return;
    initTheme();
    chart = echarts.init(containerEl, undefined, { renderer: "canvas" });
    chart.setOption(treemapOption());

    const ro = new ResizeObserver(() => chart?.resize());
    ro.observe(containerEl);

    return () => {
      ro.disconnect();
      chart?.dispose();
      chart = undefined;
    };
  });

  $effect(() => {
    if (!chart) return;
    const opt = mode === "treemap" ? treemapOption() : sunburstOption();
    chart.setOption(opt, { notMerge: true });
  });
</script>

<div class="sat-wrap">
  <div class="sat-header">
    <h3 class="sat-title">Sector Deep Dive</h3>
    <button class="sat-toggle" onclick={toggle} title={mode === "treemap" ? "Switch to Sunburst" : "Switch to Treemap"}>
      {#if mode === "treemap"}
        <Circle size={16} />
      {:else}
        <Layers size={16} />
      {/if}
      <span>{mode === "treemap" ? "Sunburst" : "Treemap"}</span>
    </button>
  </div>
  <div
    bind:this={containerEl}
    class="sat-chart"
    role="img"
    aria-label="Sector allocation {mode} chart"
  ></div>
</div>

<style>
  .sat-wrap {
    background: #141519;
    border: 1px solid #404149;
    border-radius: 16px;
    padding: 20px;
  }

  .sat-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
  }

  .sat-title {
    font-family: "Urbanist", sans-serif;
    font-size: 15px;
    font-weight: 700;
    color: #d9d9d9;
    margin: 0;
  }

  .sat-toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 14px;
    border: 1px solid #404149;
    border-radius: 8px;
    background: transparent;
    color: #a1a1aa;
    font-family: "Urbanist", sans-serif;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: background 100ms ease, border-color 100ms ease, color 100ms ease;
  }

  .sat-toggle:hover {
    background: #22232a;
    border-color: #0177fb;
    color: #0177fb;
  }

  .sat-chart {
    width: 100%;
    height: 500px;
  }
</style>
