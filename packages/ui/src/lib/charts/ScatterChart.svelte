<script lang="ts">
	import type { BaseChartProps } from "./ChartContainer.svelte";
	import ChartContainer from "./ChartContainer.svelte";

	interface ScatterChartProps extends BaseChartProps {
		points: { x: number; y: number; label?: string; size?: number }[];
		xLabel?: string;
		yLabel?: string;
	}

	let {
		points,
		xLabel,
		yLabel,
		...rest
	}: ScatterChartProps = $props();

	let option = $derived.by(() => {
		const data = points.map((p) => ({
			value: [p.x, p.y],
			name: p.label,
			symbolSize: p.size ?? 10,
		}));

		return {
			tooltip: {
				trigger: "item",
				formatter: (params: { name?: string; value: [number, number] }) => {
					const label = params.name ? `${params.name}<br/>` : "";
					return `${label}${xLabel ?? "X"}: ${params.value[0]}<br/>${yLabel ?? "Y"}: ${params.value[1]}`;
				},
			},
			grid: { left: 60, right: 20, top: 20, bottom: 40 },
			xAxis: {
				type: "value",
				name: xLabel,
				nameLocation: "middle",
				nameGap: 30,
				axisLabel: { fontSize: 11 },
			},
			yAxis: {
				type: "value",
				name: yLabel,
				nameLocation: "middle",
				nameGap: 45,
				axisLabel: { fontSize: 11 },
			},
			series: [
				{
					type: "scatter",
					data,
				},
			],
		} as Record<string, unknown>;
	});
</script>

<ChartContainer {option} {...rest} />
