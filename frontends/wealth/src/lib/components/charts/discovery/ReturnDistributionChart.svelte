<!--
  ReturnDistributionChart — histogram of daily-return bins with a vertical
  dashed markLine at the distribution mean.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { chartTokens } from "../chart-tokens";

	interface Distribution {
		bins: number[];
		counts: number[];
		mean: number;
	}

	interface Props {
		distribution: Distribution;
		height?: number;
	}

	let { distribution, height = 300 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const option = $derived.by(() => {
		const binLabels = distribution.bins.map((b) => `${(b * 100).toFixed(1)}%`);
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
							formatter: `mean ${(distribution.mean * 100).toFixed(2)}%`,
						},
						data: [
							{
								xAxis: binLabels.reduce((closestIdx, _, idx) => {
									const current = distribution.bins[idx] ?? 0;
									const closest = distribution.bins[closestIdx] ?? 0;
									return Math.abs(current - distribution.mean) <
										Math.abs(closest - distribution.mean)
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

<ChartContainer {option} {height} ariaLabel="Return distribution histogram" />
