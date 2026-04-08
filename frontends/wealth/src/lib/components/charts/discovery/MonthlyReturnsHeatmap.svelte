<!--
  MonthlyReturnsHeatmap — classic month-by-year heatmap of compound returns.
    X axis = months Jan..Dec, Y axis = years descending.
    Cell color = diverging green/red around 0 (visualMap).
  Fed by `monthly_returns` (each row's `month` is an ISO date string whose
  year and month-index we extract client-side).
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { formatPercent } from "@investintell/ui";
	import { chartTokens } from "../chart-tokens";

	interface MonthlyPoint {
		month: string;
		compound_return: number;
		compound_log_return: number;
		trading_days: number;
		min_nav: number;
		max_nav: number;
	}

	interface Props {
		monthly: MonthlyPoint[];
		height?: number;
	}

	let { monthly, height = 300 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const MONTH_LABELS = [
		"Jan",
		"Feb",
		"Mar",
		"Apr",
		"May",
		"Jun",
		"Jul",
		"Aug",
		"Sep",
		"Oct",
		"Nov",
		"Dec",
	];

	const hasData = $derived(monthly.length > 0);

	const parsed = $derived.by(() => {
		const years = new Set<number>();
		const data: [number, number, number][] = [];
		let maxAbs = 0;
		for (const row of monthly) {
			const d = new Date(row.month);
			if (Number.isNaN(d.getTime())) continue;
			const y = d.getUTCFullYear();
			const m = d.getUTCMonth();
			years.add(y);
			data.push([m, y, row.compound_return]);
			maxAbs = Math.max(maxAbs, Math.abs(row.compound_return));
		}
		const yearList = Array.from(years).sort((a, b) => b - a);
		const yearIndex = new Map<number, number>(
			yearList.map((y, i) => [y, i]),
		);
		return {
			yearList,
			cells: data.map(([m, y, v]) => [m, yearIndex.get(y) ?? 0, v]),
			maxAbs: maxAbs || 0.01,
		};
	});

	const option = $derived({
		textStyle: { fontFamily: tokens.fontFamily, fontSize: 11 },
		tooltip: {
			position: "top",
			backgroundColor: tokens.tooltipBg,
			borderColor: tokens.tooltipBorder,
			borderWidth: 1,
			padding: 10,
			formatter: (params: { data: [number, number, number] }) => {
				const [m, yIdx, v] = params.data;
				const year = parsed.yearList[yIdx];
				const pct = formatPercent(v, 2);
				return `<div style="font-family:${tokens.fontFamily};">
					<div style="color:${tokens.axisLabel};font-size:10px;">${MONTH_LABELS[m]} ${year}</div>
					<div style="color:${v >= 0 ? tokens.positive : tokens.negative};font-weight:600;">${pct}</div>
				</div>`;
			},
		},
		grid: { left: 64, right: 24, top: 24, bottom: 40 },
		xAxis: {
			type: "category",
			data: MONTH_LABELS,
			axisLabel: { color: tokens.axisLabel },
			axisLine: { lineStyle: { color: tokens.grid } },
			splitArea: { show: true },
		},
		yAxis: {
			type: "category",
			data: parsed.yearList.map(String),
			axisLabel: { color: tokens.axisLabel },
			axisLine: { lineStyle: { color: tokens.grid } },
			splitArea: { show: true },
		},
		visualMap: {
			min: -parsed.maxAbs,
			max: parsed.maxAbs,
			calculable: false,
			orient: "horizontal",
			left: "center",
			bottom: 0,
			textStyle: { color: tokens.axisLabel, fontSize: 10 },
			inRange: { color: [tokens.negative, tokens.tooltipBg, tokens.positive] },
		},
		series: [
			{
				name: "Monthly Return",
				type: "heatmap",
				data: parsed.cells,
				label: { show: false },
				emphasis: { itemStyle: { borderColor: tokens.primary, borderWidth: 1 } },
			},
		],
		animationDuration: 300,
	});
</script>

{#if !hasData}
	<ChartContainer
		option={{}}
		{height}
		empty
		emptyMessage="No monthly return data available."
		ariaLabel="Monthly returns heatmap"
	/>
{:else}
	<ChartContainer {option} {height} ariaLabel="Monthly returns heatmap" />
{/if}
