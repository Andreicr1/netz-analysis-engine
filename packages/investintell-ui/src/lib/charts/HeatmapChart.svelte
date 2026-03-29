<script lang="ts">
	import type { BaseChartProps } from "./ChartContainer.svelte";
	import ChartContainer from "./ChartContainer.svelte";

	interface HeatmapChartProps extends BaseChartProps {
		matrix: number[][];
		xLabels: string[];
		yLabels: string[];
		minColor?: string;
		maxColor?: string;
	}

	let {
		matrix,
		xLabels,
		yLabels,
		minColor = "var(--ii-surface-alt, #EFF6FF)",
		maxColor = "var(--ii-brand-primary, #1E40AF)",
		...rest
	}: HeatmapChartProps = $props();

	let option = $derived.by(() => {
		const data: [number, number, number][] = [];
		let minVal = Infinity;
		let maxVal = -Infinity;

		for (let y = 0; y < matrix.length; y++) {
			const row = matrix[y];
			if (!row) continue;
			for (let x = 0; x < row.length; x++) {
				const v = row[x];
				if (v === undefined) continue;
				data.push([x, y, v]);
				if (v < minVal) minVal = v;
				if (v > maxVal) maxVal = v;
			}
		}

		return {
			tooltip: {
				position: "top",
				formatter: (params: { data: [number, number, number] }) => {
					const [x, y, v] = params.data;
					return `${xLabels[x] ?? x} / ${yLabels[y] ?? y}: ${v}`;
				},
			},
			grid: { left: 100, right: 20, top: 20, bottom: 60 },
			xAxis: {
				type: "category",
				data: xLabels,
				splitArea: { show: true },
				axisLabel: { fontSize: 11, rotate: xLabels.length > 8 ? 45 : 0 },
			},
			yAxis: {
				type: "category",
				data: yLabels,
				splitArea: { show: true },
				axisLabel: { fontSize: 11 },
			},
			visualMap: {
				min: minVal === Infinity ? 0 : minVal,
				max: maxVal === -Infinity ? 1 : maxVal,
				calculable: true,
				orient: "horizontal",
				left: "center",
				bottom: 0,
				inRange: { color: [minColor, maxColor] },
			},
			series: [
				{
					type: "heatmap",
					data,
					label: { show: data.length <= 100, fontSize: 10 },
					emphasis: { itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,0.3)" } },
				},
			],
		} as Record<string, unknown>;
	});
</script>

<ChartContainer {option} {...rest} />
