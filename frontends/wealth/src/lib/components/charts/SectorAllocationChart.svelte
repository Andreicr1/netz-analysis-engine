<!--
  Sector Evolution — stacked area chart of sector weights over time.
  Uses ChartContainer + ii-theme for institutional consistency.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";

	interface HistoryEntry {
		report_date: string;
		sector_weights: Record<string, number>;
	}

	interface Props {
		history: HistoryEntry[];
		height?: number;
	}

	let { history = [], height = 350 }: Props = $props();

	// Same palette as Treemap for visual consistency
	const SECTOR_COLORS: Record<string, string> = {
		"Information Technology": "#0177fb",
		"Communication Services": "#6366f1",
		"Health Care":            "#06b6d4",
		"Financials":             "#0ea5e9",
		"Consumer Discretionary": "#f59e0b",
		"Consumer Staples":       "#84cc16",
		"Industrials":            "#8b5cf6",
		"Energy":                 "#f97316",
		"Materials":              "#14b8a6",
		"Real Estate":            "#ec4899",
		"Utilities":              "#a78bfa",
	};
	const FALLBACK_COLORS = [
		"#64748b", "#94a3b8", "#78716c", "#a1a1aa",
	];

	let option = $derived.by(() => {
		if (!history || history.length === 0) return {};

		const dates = history.map((h) => h.report_date);

		// Collect all sectors, ordered by total weight descending
		const sectorTotals = new Map<string, number>();
		history.forEach((h) => {
			for (const [s, v] of Object.entries(h.sector_weights)) {
				sectorTotals.set(s, (sectorTotals.get(s) ?? 0) + v);
			}
		});
		const sectors = [...sectorTotals.entries()]
			.sort(([, a], [, b]) => b - a)
			.map(([s]) => s);

		let fallbackIdx = 0;
		const series = sectors.map((sector) => {
			let color = SECTOR_COLORS[sector];
			if (!color) {
				color = FALLBACK_COLORS[fallbackIdx % FALLBACK_COLORS.length];
				fallbackIdx++;
			}
			return {
				name: sector,
				type: "line" as const,
				stack: "Total",
				areaStyle: { opacity: 0.7 },
				lineStyle: { width: 1.5 },
				symbol: "circle",
				symbolSize: 5,
				showSymbol: false,
				emphasis: { focus: "series" as const },
				itemStyle: { color },
				data: history.map((h) => +((h.sector_weights[sector] ?? 0) * 100).toFixed(2)),
			};
		});

		return {
			...globalChartOptions,
			toolbox: { show: false },
			tooltip: {
				trigger: "axis",
				axisPointer: {
					type: "cross",
					label: { backgroundColor: "#1e1e22", color: "#e4e4e7" },
				},
				backgroundColor: "#1e1e22",
				borderColor: "#2a2a2e",
				textStyle: { color: "#e4e4e7", fontSize: 12 },
				formatter(params: any) {
					if (!Array.isArray(params) || params.length === 0) return "";
					let res = `<span style="font-weight:600">${params[0].name}</span><br/>`;
					const sorted = [...params].sort(
						(a: any, b: any) => (b.value ?? 0) - (a.value ?? 0),
					);
					for (const p of sorted) {
						if (p.value > 0) {
							res += `${p.marker} ${p.seriesName}: <b>${p.value.toFixed(1)}%</b><br/>`;
						}
					}
					return res;
				},
			},
			legend: {
				data: sectors,
				bottom: 0,
				type: "scroll",
				textStyle: { color: "#a1a1aa", fontSize: 11 },
				pageTextStyle: { color: "#71717a" },
				pageIconColor: "#a1a1aa",
				pageIconInactiveColor: "#2a2a2e",
			},
			grid: {
				left: 16,
				right: 16,
				top: 16,
				bottom: 52,
				containLabel: true,
			},
			xAxis: {
				type: "category",
				boundaryGap: false,
				data: dates,
				axisLine: { lineStyle: { color: "#3f3f46" } },
				axisLabel: {
					color: "#a1a1aa",
					fontSize: 11,
					formatter(val: string) {
						const d = new Date(val);
						if (isNaN(d.getTime())) return val;
						return `${d.toLocaleString("en", { month: "short" })} ${d.getFullYear()}`;
					},
					rotate: 0,
				},
				axisTick: { show: false },
			},
			yAxis: {
				type: "value",
				max: 100,
				axisLabel: {
					formatter: "{value}%",
					color: "#a1a1aa",
					fontSize: 11,
				},
				splitLine: {
					lineStyle: { color: "#2a2a2e", type: "dashed" as const },
				},
				axisLine: { show: false },
				axisTick: { show: false },
			},
			series,
		};
	});

	let isEmpty = $derived(!history || history.length === 0);
</script>

{#if !isEmpty}
	<ChartContainer {option} {height} />
{:else}
	<div class="no-data">No sector history available.</div>
{/if}

<style>
	.no-data {
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--ii-text-muted);
		font-style: italic;
		font-size: 13px;
	}
</style>
