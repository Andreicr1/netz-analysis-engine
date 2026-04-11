<!--
  Rolling Returns — multi-series line chart (1M/3M/6M/1Y overlaid).
-->
<script lang="ts">
	import { formatNumber } from "@investintell/ui";
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import type { RollingReturns } from "$lib/types/entity-analytics";

	interface Props {
		rollingReturns: RollingReturns;
	}

	let { rollingReturns }: Props = $props();

	const colors = ["#1b365d", "#3a7bd5", "#ff975a", "#8b9daf"];

	let isEmpty = $derived(!rollingReturns.series.length);

	let chartOption = $derived.by(() => {
		const series = rollingReturns.series;
		if (!series.length) return null;

		const longestSeries = series.reduce((a, b) => a.dates.length > b.dates.length ? a : b);

		return {
			...globalChartOptions,
			grid: { left: 60, right: 20, top: 30, bottom: 60 },
			legend: {
				data: series.map(s => s.window_label),
				top: 0,
				left: "center",
				textStyle: { fontSize: 11 },
			},
			xAxis: {
				type: "category",
				data: longestSeries.dates,
				axisLabel: { fontSize: 10, rotate: 0, formatter: (v: string) => v.slice(5) },
				boundaryGap: false,
			},
			yAxis: {
				type: "value",
				axisLabel: { fontSize: 10, formatter: (v: number) => `${formatNumber(v * 100, 0)}%` },
			},
			tooltip: {
				trigger: "axis",
				confine: true,
				formatter: (params: { seriesName: string; data: [string, number]; color: string }[]) => {
					if (!params.length) return "";
					let html = `<div style="font-size:12px"><b>${params[0]!.data[0]}</b>`;
					for (const p of params) {
						const val = formatNumber(p.data[1] * 100, 2);
						html += `<br/><span style="color:${p.color}">\u25CF</span> ${p.seriesName}: <b>${val}%</b>`;
					}
					return html + "</div>";
				},
			},
			dataZoom: [
				{ type: "inside", start: 0, end: 100 },
				{ type: "slider", start: 0, end: 100, height: 20, bottom: 8 },
			],
			series: series.map((s, i) => ({
				name: s.window_label,
				type: "line",
				data: s.dates.map((d, j) => [d, s.values[j]]),
				smooth: false,
				symbol: "none",
				lineStyle: { width: 1.5, color: colors[i % colors.length] },
				itemStyle: { color: colors[i % colors.length] },
			})),
		} as Record<string, unknown>;
	});
</script>

<section class="ea-panel">
	<h2 class="ea-panel-title">Rolling Returns</h2>
	<ChartContainer
		option={chartOption ?? {}}
		height={320}
		empty={isEmpty}
		emptyMessage="Insufficient data for rolling return computation"
		ariaLabel="Rolling returns chart"
	/>
</section>

<style>
	.ea-panel {
		background: var(--ii-surface-elevated);
		border: 1px solid var(--ii-border);
		border-radius: 12px;
		padding: clamp(16px, 1rem + 0.5vw, 28px);
		margin-bottom: 16px;
	}

	.ea-panel-title {
		font-size: 0.9rem;
		font-weight: 700;
		color: var(--ii-text-primary);
		margin: 0 0 12px;
	}
</style>
