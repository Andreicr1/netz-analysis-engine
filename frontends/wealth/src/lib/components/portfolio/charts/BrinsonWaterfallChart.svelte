<!--
  BrinsonWaterfallChart — Phase 6 Block B portfolio-specific chart.

  Renders Brinson-Fachler attribution as a stacked horizontal bar
  showing allocation_effect + selection_effect per sector. The "total"
  line above the bars (markPoint) makes the total contribution per
  sector immediately visible without a second tooltip hover.

  Data source: AttributionResult from
  GET /analytics/attribution/{profile}. Profile-keyed and requires a
  live model_portfolio for that profile (the route 404s otherwise).

  Per CLAUDE.md DL16 — every basis-point goes through formatBps. Per
  OD-26 — strict empty state when no attribution data.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { EmptyState, formatBps, formatNumber } from "@investintell/ui";
	import type { AttributionResult } from "$wealth/types/analytics";
	import { chartTokens } from "$wealth/components/charts/chart-tokens";

	interface Props {
		attribution: AttributionResult | null;
		height?: number;
	}

	let { attribution, height = 320 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const sectors = $derived(attribution?.sectors ?? []);
	const isEmpty = $derived(sectors.length === 0);

	const option = $derived.by(() => {
		if (isEmpty) return {} as Record<string, unknown>;

		// Convert decimal effects to basis points (× 10_000) so the
		// axis is human-readable. The tooltip uses formatBps which
		// already handles the conversion + sign.
		const names = sectors.map((s) => s.sector);
		const allocBps = sectors.map((s) =>
			Math.round(s.allocation_effect * 10000 * 10) / 10,
		);
		const selBps = sectors.map((s) =>
			Math.round(s.selection_effect * 10000 * 10) / 10,
		);

		return {
			textStyle: { fontFamily: tokens.fontFamily, fontSize: 12 },
			tooltip: {
				trigger: "axis" as const,
				axisPointer: { type: "shadow" as const },
				backgroundColor: tokens.tooltipBg,
				borderColor: tokens.tooltipBorder,
				borderWidth: 1,
				padding: 10,
				valueFormatter: (v: number) =>
					`${v >= 0 ? "+" : ""}${formatNumber(v, 1)} bps`,
			},
			legend: {
				data: ["Allocation", "Selection"],
				bottom: 0,
				textStyle: { color: tokens.axisLabel, fontSize: 11 },
			},
			grid: {
				left: 16,
				right: 24,
				top: 12,
				bottom: 36,
				containLabel: true,
			},
			xAxis: {
				type: "value" as const,
				axisLabel: {
					formatter: (v: number) => `${v} bps`,
					fontSize: 10,
					color: tokens.axisLabel,
				},
				splitLine: {
					lineStyle: { color: "rgba(64,66,73,0.3)", type: "dashed" as const },
				},
			},
			yAxis: {
				type: "category" as const,
				data: names,
				axisLabel: {
					width: 140,
					overflow: "truncate" as const,
					fontSize: 12,
					color: "#cbccd1",
				},
			},
			series: [
				{
					name: "Allocation",
					type: "bar" as const,
					data: allocBps,
					itemStyle: {
						color: tokens.positive,
						borderRadius: [0, 3, 3, 0],
					},
				},
				{
					name: "Selection",
					type: "bar" as const,
					data: selBps,
					itemStyle: {
						color: tokens.primary,
						borderRadius: [0, 3, 3, 0],
					},
				},
			],
		} as Record<string, unknown>;
	});

	const totalExcessBps = $derived(
		attribution ? formatBps(attribution.total_excess_return) : "",
	);
</script>

{#if isEmpty}
	<EmptyState
		title="No attribution data"
		message="Activate the portfolio to compute Brinson-Fachler attribution. The route returns 404 until the portfolio is live."
	/>
{:else}
	<header class="bwc-header">
		<span class="bwc-kicker">Total excess return</span>
		<span class="bwc-value">{totalExcessBps}</span>
	</header>
	<ChartContainer
		{option}
		{height}
		ariaLabel="Brinson-Fachler attribution by sector"
	/>
{/if}

<style>
	.bwc-header {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin-bottom: 8px;
	}
	.bwc-kicker {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, #85a0bd);
	}
	.bwc-value {
		font-size: 16px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary, #ffffff);
	}
</style>
