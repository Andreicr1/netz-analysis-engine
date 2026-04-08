<!--
  ReturnDistributionChart — histogram of daily-return bins with a vertical
  dashed markLine at the distribution mean.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { formatPercent } from "@investintell/ui";
	import { chartTokens } from "../chart-tokens";

	interface Distribution {
		bins: number[];
		counts: number[];
		mean: number | null;
	}

	interface Props {
		distribution: Distribution;
		height?: number;
	}

	let { distribution, height = 300 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const hasData = $derived(distribution.bins.length > 0);

	const option = $derived.by(() => {
		const binLabels = distribution.bins.map((b) => formatPercent(b, 1));
		const meanValue = distribution.mean ?? 0;
		return {
			textStyle: { fontFamily: tokens.fontFamily, fontSize: 11 },
			tooltip: {
				trigger: "axis",
				backgroundColor: tokens.tooltipBg,
				borderColor: tokens.tooltipBorder,
				borderWidth: 1,
				padding: 10,
			},
			grid: { left: 56, right: 24, top: 24, bottom: 36, containLabel: false },
			xAxis: {
				type: "category",
				data: binLabels,
				axisLabel: { color: tokens.axisLabel, fontSize: 10 },
				axisLine: { lineStyle: { color: tokens.grid } },
			},
			yAxis: {
				type: "value",
				axisLabel: { color: tokens.axisLabel },
				splitLine: { lineStyle: { color: tokens.grid, type: "dashed" } },
			},
			series: [
				{
					name: "Frequency",
					type: "bar",
					data: distribution.counts,
					itemStyle: { color: tokens.primary },
					barCategoryGap: "8%",
					markLine: {
						symbol: "none",
						lineStyle: { color: tokens.axisLabel, type: "dashed", width: 1 },
						label: {
							color: tokens.axisLabel,
							formatter: `mean ${formatPercent(meanValue, 2)}`,
						},
						data: [
							{
								xAxis: binLabels.reduce((closestIdx, _, idx) => {
									const current = distribution.bins[idx] ?? 0;
									const closest = distribution.bins[closestIdx] ?? 0;
									return Math.abs(current - meanValue) <
										Math.abs(closest - meanValue)
										? idx
										: closestIdx;
								}, 0),
							},
						],
					},
				},
			],
			animationDuration: 300,
		};
	});
</script>

{#if !hasData}
	<ChartContainer
		option={{}}
		{height}
		empty
		emptyMessage="No distribution data available."
		ariaLabel="Return distribution histogram"
	/>
{:else}
	<ChartContainer
		{option}
		{height}
		ariaLabel="Return distribution histogram"
	/>
{/if}
