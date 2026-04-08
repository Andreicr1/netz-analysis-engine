<!--
  NavHeroChart — hero chart for the Returns & Risk view.

  Two stacked grids sharing a single dataset derived from `nav_series`:
    • Top (62%): cumulative return (line, primary color).
    • Bottom (22%): drawdown from peak (filled line, negative token).

  Cumulative return is computed from `return_1d` (already log-returns on the
  backend — `sum → exp - 1` gives the simple cumulative return). Drawdown is
  the delta between cumulative return and running peak. Both series use LTTB
  sampling and progressive rendering to stay responsive on max (5y+) window.

  Tokens and the navTooltipFormatter are shared with the Analysis sprint
  primitives. No inline hex. No toFixed on user-facing values (formatPercent
  handles them via the shared tooltip formatter).
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { chartTokens } from "../chart-tokens";
	import { navTooltipFormatter } from "../tooltips";

	interface NavPoint {
		nav_date: string;
		nav: number;
		return_1d: number | null;
	}

	interface Props {
		series: NavPoint[];
		height?: number;
	}

	let { series, height = 380 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const dataset = $derived.by(() => {
		let cumLog = 0;
		let peak = 0;
		return series.map((p) => {
			cumLog += p.return_1d ?? 0;
			const cumRet = Math.exp(cumLog) - 1;
			peak = Math.max(peak, cumRet);
			const dd = cumRet - peak;
			return [p.nav_date, cumRet, dd];
		});
	});

	const option = $derived({
		textStyle: { fontFamily: tokens.fontFamily, fontSize: 12 },
		tooltip: {
			trigger: "axis",
			backgroundColor: tokens.tooltipBg,
			borderColor: tokens.tooltipBorder,
			borderWidth: 1,
			padding: 10,
			formatter: navTooltipFormatter(tokens),
		},
		grid: [
			{ left: 56, right: 24, top: 24, height: "62%", containLabel: false },
			{ left: 56, right: 24, top: "72%", height: "22%", containLabel: false },
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
				axisLabel: {
					color: tokens.axisLabel,
					formatter: (v: number) => `${Math.round(v * 100)}%`,
				},
				splitLine: { lineStyle: { color: tokens.grid, type: "dashed" } },
			},
			{
				type: "value",
				gridIndex: 1,
				axisLabel: {
					color: tokens.axisLabel,
					formatter: (v: number) => `${Math.round(v * 100)}%`,
				},
				splitLine: { lineStyle: { color: tokens.grid, type: "dashed" } },
				max: 0,
			},
		],
		dataset: { source: dataset },
		series: [
			{
				name: "Cumulative Return",
				type: "line",
				xAxisIndex: 0,
				yAxisIndex: 0,
				encode: { x: 0, y: 1 },
				showSymbol: false,
				lineStyle: { color: tokens.primary, width: 2 },
				sampling: "lttb",
				progressive: 500,
				progressiveThreshold: 3000,
			},
			{
				name: "Drawdown",
				type: "line",
				xAxisIndex: 1,
				yAxisIndex: 1,
				encode: { x: 0, y: 2 },
				showSymbol: false,
				areaStyle: { color: tokens.negative, opacity: 0.3 },
				lineStyle: { color: tokens.negative, width: 1 },
				sampling: "lttb",
			},
		],
		animationDuration: 300,
		animationEasing: "linear",
	});
</script>

<ChartContainer {option} {height} ariaLabel="Cumulative return and drawdown" />
