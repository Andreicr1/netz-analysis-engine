<script lang="ts">
	import type { BaseChartProps } from "./ChartContainer.svelte";
	import ChartContainer from "./ChartContainer.svelte";

	type RegimeType = "RISK_ON" | "RISK_OFF" | "INFLATION" | "CRISIS";

	const REGIME_COLORS: Record<RegimeType, string> = {
		RISK_ON: "#10B98133",
		RISK_OFF: "#F59E0B33",
		INFLATION: "#F9731633",
		CRISIS: "#EF444433",
	};

	interface RegimeChartProps extends BaseChartProps {
		series: { name: string; data: [string, number][] }[];
		regimes: { start: string; end: string; type: RegimeType }[];
	}

	let {
		series,
		regimes,
		...rest
	}: RegimeChartProps = $props();

	let option = $derived.by(() => {
		const markAreaData = regimes.map((r) => [
			{
				xAxis: r.start,
				itemStyle: { color: REGIME_COLORS[r.type] },
			},
			{ xAxis: r.end },
		]);

		const seriesOpts = series.map((s, i) => ({
			name: s.name,
			type: "line" as const,
			data: s.data,
			smooth: true,
			showSymbol: false,
			markArea: i === 0 ? { silent: true, data: markAreaData } : undefined,
		}));

		return {
			tooltip: { trigger: "axis" },
			legend: { show: series.length > 1, bottom: 0 },
			grid: { left: 60, right: 20, top: 20, bottom: series.length > 1 ? 40 : 20 },
			xAxis: {
				type: "time",
				axisLabel: { fontSize: 11 },
			},
			yAxis: {
				type: "value",
				axisLabel: { fontSize: 11 },
			},
			series: seriesOpts,
		} as Record<string, unknown>;
	});
</script>

<ChartContainer {option} {...rest} />
