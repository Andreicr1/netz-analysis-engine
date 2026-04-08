<!--
  RollingRiskChart — two stacked grids sharing a time x-axis:
    • Top: rolling Sharpe (line, primary token).
    • Bottom: rolling annualized volatility (line, benchmark token).
  Fed by the `rolling_metrics` array from the returns-risk endpoint.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { chartTokens } from "../chart-tokens";

	interface RollingPoint {
		date: string;
		rolling_vol: number | null;
		rolling_sharpe: number | null;
	}

	interface Props {
		rolling: RollingPoint[];
		height?: number;
	}

	let { rolling, height = 300 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const dataset = $derived.by(() =>
		rolling.map((p) => [p.date, p.rolling_sharpe ?? null, p.rolling_vol ?? null]),
	);

	const option = $derived({
		textStyle: { fontFamily: tokens.fontFamily, fontSize: 12 },
		tooltip: {
			trigger: "axis",
			backgroundColor: tokens.tooltipBg,
			borderColor: tokens.tooltipBorder,
			borderWidth: 1,
			padding: 10,
		},
		grid: [
			{ left: 56, right: 24, top: 24, height: "40%", containLabel: false },
			{ left: 56, right: 24, top: "58%", height: "36%", containLabel: false },
		],
		xAxis: [
			{
				type: "time",
				gridIndex: 0,
				axisLabel: { show: false },
				axisLine: { lineStyle: { color: tokens.grid } },
			},
			{
				type: "time",
				gridIndex: 1,
				axisLabel: { color: tokens.axisLabel },
				axisLine: { lineStyle: { color: tokens.grid } },
			},
		],
		yAxis: [
			{
				type: "value",
				gridIndex: 0,
				name: "Sharpe",
				nameTextStyle: { color: tokens.axisLabel, fontSize: 10 },
				axisLabel: { color: tokens.axisLabel },
				splitLine: { lineStyle: { color: tokens.grid, type: "dashed" } },
			},
			{
				type: "value",
				gridIndex: 1,
				name: "Vol",
				nameTextStyle: { color: tokens.axisLabel, fontSize: 10 },
				axisLabel: {
					color: tokens.axisLabel,
					formatter: (v: number) => `${Math.round(v * 100)}%`,
				},
				splitLine: { lineStyle: { color: tokens.grid, type: "dashed" } },
			},
		],
		dataset: { source: dataset },
		series: [
			{
				name: "Rolling Sharpe",
				type: "line",
				xAxisIndex: 0,
				yAxisIndex: 0,
				encode: { x: 0, y: 1 },
				showSymbol: false,
				lineStyle: { color: tokens.primary, width: 2 },
				sampling: "lttb",
			},
			{
				name: "Rolling Vol",
				type: "line",
				xAxisIndex: 1,
				yAxisIndex: 1,
				encode: { x: 0, y: 2 },
				showSymbol: false,
				lineStyle: { color: tokens.benchmark, width: 2 },
				sampling: "lttb",
			},
		],
		animationDuration: 300,
	});
</script>

<ChartContainer {option} {height} ariaLabel="Rolling Sharpe and volatility" />
