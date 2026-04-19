<!--
  Factor Contribution Chart — eVestment p.46.
  Horizontal stacked bar: factor contributions + specific risk.
-->
<script lang="ts">
	import { formatPercent, formatNumber } from "@investintell/ui";
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import type { FactorAnalysisResult } from "$wealth/types/analytics";

	interface Props {
		data: FactorAnalysisResult;
	}

	let { data }: Props = $props();

	const factorColors = [
		"rgba(59, 130, 246, 0.8)",   /* blue */
		"rgba(168, 85, 247, 0.7)",   /* purple */
		"rgba(34, 197, 94, 0.7)",    /* green */
		"rgba(245, 158, 11, 0.7)",   /* amber */
		"rgba(236, 72, 153, 0.7)",   /* pink */
		"rgba(14, 165, 233, 0.7)",   /* sky */
		"rgba(234, 88, 12, 0.7)",    /* orange */
		"rgba(99, 102, 241, 0.7)",   /* indigo */
		"rgba(20, 184, 166, 0.7)",   /* teal */
		"rgba(244, 63, 94, 0.7)",    /* rose */
	];

	let chartOption = $derived.by(() => {
		const contribs = data.factor_contributions;
		if (contribs.length === 0) return null;

		const categories = ["Risk"];
		const series = contribs.map((fc, i) => ({
			name: fc.factor_label,
			type: "bar" as const,
			stack: "risk",
			data: [fc.pct_contribution],
			itemStyle: { color: factorColors[i % factorColors.length] },
			barWidth: "60%",
		}));

		// Add specific risk as last stack
		series.push({
			name: "Specific",
			type: "bar",
			stack: "risk",
			data: [data.specific_risk_pct],
			itemStyle: { color: "rgba(148, 163, 184, 0.5)" },
			barWidth: "60%",
		});

		return {
			...globalChartOptions,
			grid: { left: 60, right: 30, top: 20, bottom: 30 },
			tooltip: {
				trigger: "axis",
				confine: true,
				formatter: (params: { seriesName: string; data: number; color: string }[]) => {
					if (!params.length) return "";
					let html = "<div style='font-size:12px'>";
					for (const p of params) {
						html += `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color};margin-right:4px"></span>`;
						html += `${p.seriesName}: ${formatNumber(p.data, 1, "en-US")}%<br/>`;
					}
					html += "</div>";
					return html;
				},
			},
			xAxis: {
				type: "value",
				max: 100,
				axisLabel: { fontSize: 10, formatter: (v: number) => `${v}%` },
			},
			yAxis: {
				type: "category",
				data: categories,
				axisLabel: { fontSize: 10 },
			},
			series,
		} as Record<string, unknown>;
	});

	let isEmpty = $derived(data.factor_contributions.length === 0);
</script>

<section class="fc-panel">
	<div class="fc-header">
		<h3 class="fc-title">Factor Decomposition (PCA)</h3>
		<div class="fc-kpis">
			<div class="fc-kpi">
				<span class="fc-kpi-label">Systematic</span>
				<span class="fc-kpi-value">{formatPercent(data.systematic_risk_pct / 100, 1, "en-US")}</span>
			</div>
			<div class="fc-kpi">
				<span class="fc-kpi-label">Specific</span>
				<span class="fc-kpi-value">{formatPercent(data.specific_risk_pct / 100, 1, "en-US")}</span>
			</div>
			<div class="fc-kpi">
				<span class="fc-kpi-label">R&sup2;</span>
				<span class="fc-kpi-value">{formatNumber(data.r_squared, 4, "en-US")}</span>
			</div>
		</div>
	</div>

	<div class="fc-body">
		<ChartContainer
			option={chartOption ?? {}}
			height={80}
			empty={isEmpty}
			emptyMessage="Insufficient data for factor analysis"
			ariaLabel="Factor contribution stacked bar chart"
		/>

		{#if data.factor_contributions.length > 0}
			<div class="fc-detail">
				{#each data.factor_contributions as fc, i (fc.factor_label)}
					<div class="fc-row">
						<span class="fc-dot" style:background={factorColors[i % factorColors.length]}></span>
						<span class="fc-label">{fc.factor_label}</span>
						<span class="fc-value">{formatNumber(fc.pct_contribution, 1, "en-US")}%</span>
						{#if data.portfolio_factor_exposures[fc.factor_label] != null}
							<span class="fc-exposure">
								exp: {formatNumber(data.portfolio_factor_exposures[fc.factor_label]!, 4, "en-US")}
							</span>
						{/if}
					</div>
				{/each}
				<div class="fc-row">
					<span class="fc-dot" style:background="rgba(148, 163, 184, 0.5)"></span>
					<span class="fc-label">Specific (idiosyncratic)</span>
					<span class="fc-value">{formatNumber(data.specific_risk_pct, 1, "en-US")}%</span>
				</div>
			</div>
		{/if}
	</div>
</section>

<style>
	.fc-panel {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		overflow: hidden;
		margin: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px) 0;
	}

	.fc-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
		flex-wrap: wrap;
		gap: 8px;
	}

	.fc-title {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.fc-kpis {
		display: flex;
		gap: 16px;
	}

	.fc-kpi {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.fc-kpi-label {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.fc-kpi-value {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
	}

	.fc-body {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
	}

	.fc-detail {
		display: flex;
		flex-direction: column;
		gap: 4px;
		margin-top: var(--ii-space-stack-sm, 12px);
	}

	.fc-row {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.fc-dot {
		width: 10px;
		height: 10px;
		border-radius: 2px;
		flex-shrink: 0;
	}

	.fc-label {
		flex: 1;
		color: var(--ii-text-primary);
		font-weight: 500;
	}

	.fc-value {
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
		min-width: 50px;
		text-align: right;
	}

	.fc-exposure {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
		min-width: 80px;
		text-align: right;
	}
</style>
