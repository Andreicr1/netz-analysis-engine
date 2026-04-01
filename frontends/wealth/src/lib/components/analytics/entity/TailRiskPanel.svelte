<!--
  Tail Risk Panel — eVestment Section VII.
  VaR comparison (Parametric vs Modified vs Historical ETL), ETR bar, normality badge.
-->
<script lang="ts">
	import { formatPercent, formatNumber } from "@investintell/ui";
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import type { TailRiskMetrics } from "$lib/types/entity-analytics";

	interface Props {
		tailRisk: TailRiskMetrics;
	}

	let { tailRisk }: Props = $props();

	function fmtPct(v: number | null): string {
		if (v == null) return "\u2014";
		return formatPercent(v, 2, "en-US", true);
	}

	function fmtNum(v: number | null, decimals = 4): string {
		if (v == null) return "\u2014";
		return formatNumber(v, decimals, "en-US");
	}

	let chartOption = $derived.by(() => {
		const tr = tailRisk;
		const categories = ["VaR 90%", "VaR 95%", "VaR 99%", "mVaR 95%", "mVaR 99%", "ETL 95%", "mETL 95%", "ETR 95%"];
		const values = [
			tr.var_parametric_90,
			tr.var_parametric_95,
			tr.var_parametric_99,
			tr.var_modified_95,
			tr.var_modified_99,
			tr.etl_95,
			tr.etl_modified_95,
			tr.etr_95,
		];

		const hasData = values.some(v => v != null);
		if (!hasData) return null;

		return {
			...globalChartOptions,
			grid: { left: 90, right: 30, top: 20, bottom: 30 },
			xAxis: {
				type: "value",
				axisLabel: {
					fontSize: 10,
					formatter: (v: number) => (v * 100).toFixed(2) + "%",
				},
			},
			yAxis: {
				type: "category",
				data: categories,
				axisLabel: { fontSize: 10 },
			},
			tooltip: {
				trigger: "axis",
				confine: true,
				formatter: (params: { name: string; data: number; color: string }[]) => {
					if (!params.length) return "";
					const p = params[0]!;
					return `<div style="font-size:12px"><b>${p.name}</b><br/>${(p.data * 100).toFixed(4)}%</div>`;
				},
			},
			series: [
				{
					type: "bar",
					data: values.map((v, i) => ({
						value: v ?? 0,
						itemStyle: {
							color: i === 7
								? "rgba(34, 197, 94, 0.7)"     /* ETR = green (right tail) */
								: i >= 5
									? "rgba(239, 68, 68, 0.8)"  /* ETL = deep red */
									: i >= 3
										? "rgba(168, 85, 247, 0.7)" /* Modified VaR = purple */
										: "rgba(59, 130, 246, 0.6)", /* Parametric VaR = blue */
						},
					})),
					barWidth: "60%",
				},
			],
		} as Record<string, unknown>;
	});

	let isEmpty = $derived(
		tailRisk.var_parametric_95 == null && tailRisk.etl_95 == null,
	);
</script>

<section class="ea-panel">
	<h2 class="ea-panel-title">Tail Risk</h2>

	<div class="ea-tr-kpis">
		<div class="ea-stat">
			<span class="ea-stat-label">VaR 95% (Param)</span>
			<span class="ea-stat-value" style:color="var(--ii-danger)">{fmtPct(tailRisk.var_parametric_95)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">mVaR 95% (CF)</span>
			<span class="ea-stat-value" style:color="var(--ii-danger)">{fmtPct(tailRisk.var_modified_95)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">ETL 95%</span>
			<span class="ea-stat-value" style:color="var(--ii-danger)">{fmtPct(tailRisk.etl_95)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">ETR 95%</span>
			<span class="ea-stat-value" style:color="var(--ii-success)">{fmtPct(tailRisk.etr_95)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">STARR Ratio</span>
			<span class="ea-stat-value">{fmtNum(tailRisk.starr_ratio, 4)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Rachev Ratio</span>
			<span class="ea-stat-value">{fmtNum(tailRisk.rachev_ratio, 4)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Jarque-Bera</span>
			<span class="ea-stat-value">{fmtNum(tailRisk.jarque_bera_stat, 2)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Normality</span>
			<span class="ea-stat-value">
				{#if tailRisk.is_normal == null}
					&#8212;
				{:else if tailRisk.is_normal}
					<span class="ea-badge ea-badge--ok">Normal</span>
				{:else}
					<span class="ea-badge ea-badge--warn">Non-Normal</span>
				{/if}
			</span>
		</div>
	</div>

	<ChartContainer
		option={chartOption ?? {}}
		height={260}
		empty={isEmpty}
		emptyMessage="Insufficient data for tail risk analysis"
		ariaLabel="Tail risk VaR comparison chart"
	/>
</section>

<style>
	.ea-panel {
		background: var(--ii-surface-elevated);
		border: 1px solid var(--ii-border);
		border-radius: 12px;
		padding: clamp(16px, 1rem + 0.5vw, 28px);
		margin-bottom: 16px;
	}

	.ea-panel-title {
		font-size: 0.9rem;
		font-weight: 700;
		color: var(--ii-text-primary);
		margin: 0 0 12px;
	}

	.ea-tr-kpis {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
		gap: 12px;
		margin-bottom: 16px;
	}

	.ea-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.ea-stat-label {
		font-size: 0.7rem;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ii-text-muted);
	}

	.ea-stat-value {
		font-size: 1.1rem;
		font-weight: 700;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.ea-badge {
		font-size: 0.7rem;
		font-weight: 600;
		padding: 2px 8px;
		border-radius: 4px;
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}

	.ea-badge--ok {
		color: var(--ii-success);
		background: color-mix(in srgb, var(--ii-success) 12%, transparent);
	}

	.ea-badge--warn {
		color: var(--ii-warning);
		background: color-mix(in srgb, var(--ii-warning) 12%, transparent);
	}
</style>
