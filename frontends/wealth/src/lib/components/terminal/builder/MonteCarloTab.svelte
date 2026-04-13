<!--
  MonteCarloTab — MONTE CARLO tab in the Builder results panel.

  Single chart: stacked area bands for percentile ranges (p5-p95)
  with solid p50 median line. Horizons: 12m, 36m, 60m.
  Data sourced from workspace.monteCarloData.
-->
<script lang="ts">
	import { formatPercent, createTerminalChartOptions, readTerminalTokens } from "@investintell/ui";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import TerminalChart from "$lib/components/terminal/charts/TerminalChart.svelte";
	import type { EChartsOption } from "echarts";

	// Fetch on mount
	$effect(() => {
		if (workspace.portfolioId && !workspace.monteCarloData && !workspace.isLoadingMonteCarlo) {
			workspace.fetchMonteCarlo();
		}
	});

	const data = $derived(workspace.monteCarloData);
	const bars = $derived(data?.confidence_bars ?? []);
	const isEmpty = $derived(!data || bars.length === 0);

	const chartOption = $derived.by<EChartsOption>(() => {
		if (isEmpty || bars.length === 0) {
			return createTerminalChartOptions({ series: [] });
		}

		const tokens = readTerminalTokens();

		// X-axis: months from horizons
		const horizonLabels = bars.map((b) => b.horizon);

		// Build stacked area bands using 4 stacked invisible-base series:
		// The technique: stack from bottom up, each series value = band height.
		// p5 base (invisible), p5→p25 band, p25→p50 band, p50→p75 band, p75→p95 band.
		const barsRef = bars;
		const p5Values = barsRef.map((b) => b.pct_5);
		const p25Values = barsRef.map((b) => b.pct_25);
		const p50Values = barsRef.map((b) => b.pct_50);
		const p75Values = barsRef.map((b) => b.pct_75);
		const p95Values = barsRef.map((b) => b.pct_95);

		const bandColor = tokens.accentCyan;

		return createTerminalChartOptions({
			xAxis: {
				type: "category" as const,
				data: horizonLabels,
				boundaryGap: false,
			},
			yAxis: {
				type: "value" as const,
				axisLabel: {
					formatter: (v: number) => formatPercent(v, 0),
				},
			},
			series: [
				// Invisible base: p5
				{
					type: "line",
					name: "p5-base",
					stack: "mc-band",
					data: p5Values,
					lineStyle: { opacity: 0 },
					areaStyle: { opacity: 0 },
					showSymbol: false,
					silent: true,
				},
				// Band: p5 → p25
				{
					type: "line",
					name: "5th - 25th",
					stack: "mc-band",
					data: p25Values.map((v, i) => v - (p5Values[i] ?? 0)),
					lineStyle: { opacity: 0 },
					areaStyle: { color: bandColor, opacity: 0.08 },
					showSymbol: false,
					silent: true,
				},
				// Band: p25 → p50
				{
					type: "line",
					name: "25th - 50th",
					stack: "mc-band",
					data: p50Values.map((v, i) => v - (p25Values[i] ?? 0)),
					lineStyle: { opacity: 0 },
					areaStyle: { color: bandColor, opacity: 0.15 },
					showSymbol: false,
					silent: true,
				},
				// Band: p50 → p75
				{
					type: "line",
					name: "50th - 75th",
					stack: "mc-band",
					data: p75Values.map((v, i) => v - (p50Values[i] ?? 0)),
					lineStyle: { opacity: 0 },
					areaStyle: { color: bandColor, opacity: 0.22 },
					showSymbol: false,
					silent: true,
				},
				// Band: p75 → p95
				{
					type: "line",
					name: "75th - 95th",
					stack: "mc-band",
					data: p95Values.map((v, i) => v - (p75Values[i] ?? 0)),
					lineStyle: { opacity: 0 },
					areaStyle: { color: bandColor, opacity: 0.30 },
					showSymbol: false,
					silent: true,
				},
				// Solid median line (non-stacked)
				{
					type: "line",
					name: "Median",
					data: p50Values,
					showSymbol: true,
					symbolSize: 6,
					lineStyle: { width: 2, color: tokens.accentAmber },
					itemStyle: { color: tokens.accentAmber },
				},
			],
			showLegend: false,
			tooltipFormatter: (params: unknown) => {
				if (!Array.isArray(params) || params.length === 0) return "";
				const idx = (params[0] as { dataIndex: number }).dataIndex;
				if (idx == null || idx >= barsRef.length) return "";
				const bar = barsRef[idx];
				if (!bar) return "";
				const lines = [
					`<b>${bar.horizon}</b>`,
					`95th: ${formatPercent(bar.pct_95, 1)}`,
					`75th: ${formatPercent(bar.pct_75, 1)}`,
					`Median: ${formatPercent(bar.pct_50, 1)}`,
					`25th: ${formatPercent(bar.pct_25, 1)}`,
					`5th: ${formatPercent(bar.pct_5, 1)}`,
				];
				return lines.join("<br>");
			},
			slot: "primary",
		});
	});
</script>

<div class="mc-root">
	{#if isEmpty && !workspace.isLoadingMonteCarlo}
		<div class="mc-empty">Run construction to simulate future outcomes</div>
	{:else}
		<div class="mc-header">
			<span class="mc-title">
				Monte Carlo Simulation
				{#if data}
					({data.n_simulations.toLocaleString()} paths)
				{/if}
			</span>
		</div>
		<TerminalChart
			option={chartOption}
			height={360}
			loading={workspace.isLoadingMonteCarlo}
			empty={isEmpty}
			emptyMessage="INSUFFICIENT DATA"
			ariaLabel="Monte Carlo percentile band chart"
		/>
	{/if}
</div>

<style>
	.mc-root {
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-secondary);
	}

	.mc-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 300px;
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-12);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.mc-header {
		padding: var(--terminal-space-1) 0 var(--terminal-space-2);
	}

	.mc-title {
		font-size: var(--terminal-text-11);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
	}
</style>
