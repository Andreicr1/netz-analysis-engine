<script lang="ts">
	import type { BaseChartProps } from "./ChartContainer.svelte";
	import ChartContainer from "./ChartContainer.svelte";

	interface FunnelChartProps extends BaseChartProps {
		stages: { name: string; value: number }[];
	}

	let {
		stages,
		...rest
	}: FunnelChartProps = $props();

	let option = $derived.by(() => {
		return {
			tooltip: { trigger: "item", formatter: "{b}: {c}" },
			series: [
				{
					type: "funnel",
					left: "10%",
					top: 20,
					bottom: 20,
					width: "80%",
					sort: "descending",
					gap: 2,
					label: { show: true, position: "inside", fontSize: 12 },
					data: stages.map((s) => ({ name: s.name, value: s.value })),
				},
			],
		} as Record<string, unknown>;
	});
</script>

<ChartContainer {option} {...rest} />
