<!--
  RiskAttributionBarChart — Phase 6 Block B portfolio-specific chart.

  Decomposes total portfolio risk into block-level percentage
  contributions (PCTR + PCETL). The PCTR (Percentage Contribution To
  Risk) view answers "which block is doing the most damage to my
  variance?" — a fundamental institutional risk question.

  Data source: RiskBudgetResult from POST /analytics/risk-budget/...
  (existing route). The route is on-demand because it triggers heavy
  computation; the chart renders an EmptyState with a "Compute risk
  budget" CTA button when no data is loaded yet.

  Per CLAUDE.md DL16 — every percentage goes through formatPercent.
  Per OD-26 — strict empty states with action CTAs.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { EmptyState, Button, formatPercent } from "@investintell/ui";
	import type { RiskBudgetResult } from "$lib/types/analytics";
	import { chartTokens } from "$lib/components/charts/chart-tokens";

	interface Props {
		riskBudget: RiskBudgetResult | null;
		isLoading?: boolean;
		onCompute?: () => void;
		height?: number;
	}

	let {
		riskBudget,
		isLoading = false,
		onCompute,
		height = 320,
	}: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	const funds = $derived(riskBudget?.funds ?? []);
	const isEmpty = $derived(funds.length === 0);

	const option = $derived.by(() => {
		if (isEmpty) return {} as Record<string, unknown>;

		// Sort by PCTR descending so the biggest risk contributors are
		// at the top of the bar chart (institutional convention).
		const sorted = [...funds]
			.filter((f) => f.pctr !== null)
			.sort((a, b) => (b.pctr ?? 0) - (a.pctr ?? 0));

		const labels = sorted.map((f) => f.block_name);
		const pctrValues = sorted.map((f) => Math.round((f.pctr ?? 0) * 10000) / 100);
		const pcetlValues = sorted.map(
			(f) => Math.round((f.pcetl ?? 0) * 10000) / 100,
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
				valueFormatter: (v: number) => formatPercent(v / 100, 1),
			},
			legend: {
				data: ["Volatility (PCTR)", "Tail loss (PCETL)"],
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
					formatter: (v: number) => `${v}%`,
					fontSize: 10,
					color: tokens.axisLabel,
				},
				splitLine: {
					lineStyle: { color: "rgba(64,66,73,0.3)", type: "dashed" as const },
				},
			},
			yAxis: {
				type: "category" as const,
				data: labels,
				axisLabel: {
					width: 140,
					overflow: "truncate" as const,
					fontSize: 12,
					color: "#cbccd1",
				},
			},
			series: [
				{
					name: "Volatility (PCTR)",
					type: "bar" as const,
					data: pctrValues,
					itemStyle: {
						color: tokens.primary,
						borderRadius: [0, 3, 3, 0],
					},
				},
				{
					name: "Tail loss (PCETL)",
					type: "bar" as const,
					data: pcetlValues,
					itemStyle: {
						color: tokens.negative,
						borderRadius: [0, 3, 3, 0],
					},
				},
			],
		} as Record<string, unknown>;
	});
</script>

{#if isLoading}
	<EmptyState
		title="Computing risk budget..."
		message="The optimizer is decomposing block-level risk contributions."
	/>
{:else if isEmpty}
	<div class="rab-cta">
		<EmptyState
			title="Risk budget not computed"
			message="Marginal and percentage contributions to risk per allocation block. On-demand because the computation is heavy."
		/>
		{#if onCompute}
			<div class="rab-actions">
				<Button variant="outline" size="sm" onclick={onCompute}>
					Compute Risk Budget
				</Button>
			</div>
		{/if}
	</div>
{:else}
	<header class="rab-header">
		<div class="rab-stat">
			<span class="rab-kicker">Portfolio Vol</span>
			<span class="rab-value">{formatPercent(riskBudget?.portfolio_volatility ?? 0, 2)}</span>
		</div>
		<div class="rab-stat">
			<span class="rab-kicker">Portfolio ETL</span>
			<span class="rab-value">{formatPercent(riskBudget?.portfolio_etl ?? 0, 2)}</span>
		</div>
	</header>
	<ChartContainer
		{option}
		{height}
		ariaLabel="Risk attribution by allocation block"
	/>
{/if}

<style>
	.rab-cta {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 12px;
	}
	.rab-actions {
		display: flex;
		justify-content: center;
		padding-top: 4px;
	}
	.rab-header {
		display: flex;
		gap: 24px;
		margin-bottom: 8px;
	}
	.rab-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.rab-kicker {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, #85a0bd);
	}
	.rab-value {
		font-size: 16px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary, #ffffff);
	}
</style>
