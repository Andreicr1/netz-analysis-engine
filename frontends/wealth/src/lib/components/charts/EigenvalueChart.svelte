<!--
  Eigenvalue Decomposition — Marchenko-Pastur threshold bars.
  Blue (#2166ac) for signal eigenvalues (above MP), grey (#94a3b8) for noise.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";

	interface Props {
		eigenvalues: number[];
		mpThreshold: number;
		nSignal: number;
		height?: number;
	}

	let {
		eigenvalues,
		mpThreshold,
		nSignal,
		height = 220,
	}: Props = $props();

	let option = $derived.by(() => {
		if (eigenvalues.length === 0) return {};

		return {
			tooltip: { trigger: "axis" },
			grid: { left: 60, right: 20, top: 20, bottom: 30 },
			xAxis: {
				type: "category",
				data: eigenvalues.map((_: number, i: number) => `\u03BB${i + 1}`),
				axisLabel: { fontSize: 10 },
			},
			yAxis: {
				type: "value",
				axisLabel: { fontSize: 10 },
			},
			series: [
				{
					type: "bar",
					data: eigenvalues.map((v: number) => ({
						value: v,
						itemStyle: {
							color: v > mpThreshold ? "#2166ac" : "#94a3b8",
						},
					})),
					markLine: {
						silent: true,
						data: [
							{
								yAxis: mpThreshold,
								lineStyle: { color: "#ef4444", type: "dashed", width: 2 },
								label: {
									formatter: "MP threshold",
									position: "end",
									fontSize: 10,
								},
							},
						],
					},
				},
			],
		} as Record<string, unknown>;
	});
</script>

{#if eigenvalues.length > 0}
	<ChartContainer
		{option}
		{height}
		ariaLabel="Eigenvalue decomposition with Marchenko-Pastur threshold"
	/>
{/if}
