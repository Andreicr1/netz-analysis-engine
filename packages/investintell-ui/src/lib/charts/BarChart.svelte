<script lang="ts">
	import type { BaseChartProps } from "./ChartContainer.svelte";
	import ChartContainer from "./ChartContainer.svelte";

	interface BarChartProps extends BaseChartProps {
		data: { name: string; value: number }[];
		orientation?: "horizontal" | "vertical";
		stacked?: boolean;
	}

	let {
		data,
		orientation = "vertical",
		stacked = false,
		...rest
	}: BarChartProps = $props();

	let option = $derived.by(() => {
		const isHorizontal = orientation === "horizontal";
		const categories = data.map((d) => d.name);
		const values = data.map((d) => d.value);

		const categoryAxis = {
			type: "category" as const,
			data: categories,
			axisLabel: { fontSize: 11, interval: 0 },
		};
		const valueAxis = {
			type: "value" as const,
			axisLabel: { fontSize: 11 },
		};

		return {
			tooltip: { trigger: "axis" },
			grid: {
				left: isHorizontal ? 100 : 40,
				right: 20,
				top: 20,
				bottom: 30,
				containLabel: false,
			},
			xAxis: isHorizontal ? valueAxis : categoryAxis,
			yAxis: isHorizontal ? categoryAxis : valueAxis,
			series: [
				{
					type: "bar",
					data: values,
					stack: stacked ? "total" : undefined,
					barMaxWidth: 40,
				},
			],
		} as Record<string, unknown>;
	});
</script>

<ChartContainer {option} {...rest} />
