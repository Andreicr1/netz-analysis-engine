<!--
  Risk Budget Scatter — Mean Return vs Implied Return.
  STARR diagonal line shows the optimal risk-reward boundary.
  Funds above the line should receive increased allocation.
-->
<script lang="ts">
	import { formatNumber } from "@investintell/ui";
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import type { RiskBudgetResult } from "$wealth/types/analytics";

	interface Props {
		data: RiskBudgetResult;
	}

	let { data }: Props = $props();

	let chartOption = $derived.by(() => {
		const funds = data.funds;
		if (funds.length === 0) return null;

		const scatter = funds
			.filter(f => f.implied_return_vol != null && f.mean_return != null)
			.map(f => ({
				value: [f.implied_return_vol! * 10000, f.mean_return * 10000],
				name: f.block_name,
			}));

		if (scatter.length === 0) return null;

		// Compute STARR diagonal range
		const allX = scatter.map(s => s.value[0]!);
		const minX = Math.min(...allX) * 0.8;
		const maxX = Math.max(...allX) * 1.2;

		return {
			...globalChartOptions,
			grid: { left: 70, right: 30, top: 30, bottom: 50 },
			tooltip: {
				trigger: "item",
				formatter: (params: { name: string; value: [number, number] }) => {
					const [implied, actual] = params.value;
					const diff = actual - implied;
					const diffSign = diff >= 0 ? "+" : "";
					return `<div style="font-size:12px">
						<b>${params.name}</b><br/>
						Implied: ${formatNumber(implied, 2, "en-US")} bps<br/>
						Actual: ${formatNumber(actual, 2, "en-US")} bps<br/>
						Diff: <span style="color:${diff >= 0 ? '#22c55e' : '#ef4444'}">${diffSign}${formatNumber(diff, 2, "en-US")} bps</span>
					</div>`;
				},
			},
			xAxis: {
				type: "value",
				name: "Implied Return (bps)",
				nameLocation: "center",
				nameGap: 30,
				axisLabel: { fontSize: 10 },
				nameTextStyle: { fontSize: 11, color: "var(--ii-text-muted)" },
			},
			yAxis: {
				type: "value",
				name: "Mean Return (bps)",
				nameLocation: "center",
				nameGap: 50,
				axisLabel: { fontSize: 10 },
				nameTextStyle: { fontSize: 11, color: "var(--ii-text-muted)" },
			},
			series: [
				{
					type: "scatter",
					data: scatter,
					symbolSize: 12,
					itemStyle: { color: "rgba(59, 130, 246, 0.8)" },
					label: {
						show: true,
						position: "right",
						fontSize: 10,
						formatter: (params: { name: string }) => params.name,
					},
				},
				{
					type: "line",
					data: [[minX, minX], [maxX, maxX]],
					lineStyle: { color: "#94a3b8", type: "dashed", width: 1 },
					symbol: "none",
					tooltip: { show: false },
					silent: true,
				},
			],
		} as Record<string, unknown>;
	});

	let isEmpty = $derived(data.funds.length === 0);
</script>

<section class="rbs-panel">
	<h3 class="rbs-title">Mean vs Implied Return</h3>
	<p class="rbs-subtitle">Funds above the diagonal have higher returns than risk-implied. Dashed line = STARR-optimal boundary.</p>
	<ChartContainer
		option={chartOption ?? {}}
		height={320}
		empty={isEmpty}
		emptyMessage="Insufficient data for risk budget scatter"
		ariaLabel="Risk budget scatter: mean vs implied return"
	/>
</section>

<style>
	.rbs-panel {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		margin: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px) 0;
	}

	.rbs-title {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		margin-bottom: 2px;
	}

	.rbs-subtitle {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		margin-bottom: var(--ii-space-stack-sm, 12px);
	}
</style>
