<script lang="ts">
	import type { BaseChartProps } from "./ChartContainer.svelte";
	import ChartContainer from "./ChartContainer.svelte";

	interface GaugeChartProps extends BaseChartProps {
		value: number;
		min?: number;
		max?: number;
		thresholds?: { value: number; color: string }[];
		label?: string;
	}

	let {
		value,
		min = 0,
		max = 100,
		thresholds,
		label,
		height = 240,
		...rest
	}: GaugeChartProps = $props();

	let option = $derived.by(() => {
		let axisLine: Record<string, unknown> = {
			lineStyle: { width: 16 },
		};

		if (thresholds && thresholds.length > 0) {
			const sorted = [...thresholds].sort((a, b) => a.value - b.value);
			const range = max - min;
			const colorStops: [number, string][] = sorted.map((t) => [
				(t.value - min) / range,
				t.color,
			]);
			// Ensure we reach 1.0
			const lastStop = colorStops[colorStops.length - 1];
			if (lastStop && lastStop[0] < 1) {
				colorStops.push([1, lastStop[1]]);
			}
			axisLine = { lineStyle: { width: 16, color: colorStops } };
		}

		return {
			series: [
				{
					type: "gauge",
					min,
					max,
					startAngle: 210,
					endAngle: -30,
					axisLine,
					pointer: { width: 5 },
					axisTick: { show: false },
					splitLine: { length: 10 },
					axisLabel: { fontSize: 10 },
					detail: {
						valueAnimation: true,
						fontSize: 24,
						fontWeight: "bold",
						offsetCenter: [0, "65%"],
						formatter: label ? `{value}\n${label}` : "{value}",
					},
					data: [{ value }],
				},
			],
		} as Record<string, unknown>;
	});
</script>

<ChartContainer {option} {height} {...rest} />
