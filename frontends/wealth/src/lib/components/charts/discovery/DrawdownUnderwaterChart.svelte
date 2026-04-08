<!--
  DrawdownUnderwaterChart — standalone underwater chart showing drawdown
  from rolling peak. Identical computation to the bottom grid of NavHeroChart,
  but rendered full-size as its own card for operators who want a zoomed view.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { formatPercent } from "@investintell/ui";
	import { chartTokens } from "../chart-tokens";

	interface NavPoint {
		nav_date: string;
		nav: number;
		return_1d: number | null;
	}

	interface Props {
		series: NavPoint[];
		height?: number;
	}

	let { series, height = 300 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const dataset = $derived.by(() => {
		let cumLog = 0;
		let peak = 0;
		return series.map((p) => {
			cumLog += p.return_1d ?? 0;
			const cumRet = Math.exp(cumLog) - 1;
			peak = Math.max(peak, cumRet);
			return [p.nav_date, cumRet - peak];
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
			formatter: (params: { axisValueLabel?: string; value?: [string, number] }[]) => {
				const p = params?.[0];
				if (!p) return "";
				const v = Array.isArray(p.value) ? (p.value[1] ?? 0) : 0;
				return `<div style="font-family:${tokens.fontFamily};font-size:11px;">
					<div style="color:${tokens.axisLabel};">${p.axisValueLabel ?? ""}</div>
					<div style="color:${tokens.negative};font-weight:600;">${formatPercent(v, 2)}</div>
				</div>`;
			},
		},
		grid: { left: 56, right: 24, top: 24, bottom: 36 },
		xAxis: {
			type: "time",
			axisLabel: { color: tokens.axisLabel },
			axisLine: { lineStyle: { color: tokens.grid } },
		},
		yAxis: {
			type: "value",
			max: 0,
			axisLabel: {
				color: tokens.axisLabel,
				formatter: (v: number) => formatPercent(v, 0),
			},
			splitLine: { lineStyle: { color: tokens.grid, type: "dashed" } },
		},
		dataset: { source: dataset },
		series: [
			{
				name: "Drawdown",
				type: "line",
				encode: { x: 0, y: 1 },
				showSymbol: false,
				lineStyle: { color: tokens.negative, width: 1 },
				areaStyle: { color: tokens.negative, opacity: 0.3 },
				sampling: "lttb",
				progressive: 500,
			},
		],
		animationDuration: 300,
	});
</script>

<ChartContainer {option} {height} ariaLabel="Drawdown underwater chart" />
