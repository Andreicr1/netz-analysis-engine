<script lang="ts">
	import type { BaseChartProps } from "./ChartContainer.svelte";
	import ChartContainer from "./ChartContainer.svelte";

	interface TimeSeriesChartProps extends BaseChartProps {
		series: { name: string; data: [string, number][] }[];
		dateRange?: [string, string];
		yAxisLabel?: string;
		area?: boolean;
	}

	let {
		series,
		dateRange,
		yAxisLabel,
		area = false,
		...rest
	}: TimeSeriesChartProps = $props();

	let option = $derived.by(() => {
		const seriesOpts = series.map((s) => ({
			name: s.name,
			type: "line" as const,
			data: s.data,
			smooth: true,
			showSymbol: false,
			areaStyle: area ? { opacity: 0.15 } : undefined,
		}));

		const xMin = dateRange?.[0];
		const xMax = dateRange?.[1];

		return {
			tooltip: { trigger: "axis" },
			legend: { show: series.length > 1, bottom: 0 },
			grid: { left: 60, right: 20, top: 20, bottom: series.length > 1 ? 40 : 20 },
			xAxis: {
				type: "time",
				min: xMin,
				max: xMax,
				axisLabel: { fontSize: 11 },
			},
			yAxis: {
				type: "value",
				name: yAxisLabel,
				nameLocation: "middle",
				nameGap: 45,
				axisLabel: { fontSize: 11 },
			},
			series: seriesOpts,
		} as Record<string, unknown>;
	});
</script>

<ChartContainer {option} {...rest} />
