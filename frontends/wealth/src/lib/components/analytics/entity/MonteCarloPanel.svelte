<!--
  Monte Carlo Panel — block bootstrap simulation results.
  Percentile distribution table + confidence bar chart across horizons.
-->
<script lang="ts">
	import { formatPercent, formatNumber } from "@investintell/ui";
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import type { MonteCarloResult } from "$lib/types/analytics";

	interface Props {
		mc: MonteCarloResult;
	}

	let { mc }: Props = $props();

	function fmtPct(v: number): string {
		return formatPercent(v, 2, "en-US", true);
	}

	function fmtNum(v: number, decimals = 4): string {
		return formatNumber(v, decimals, "en-US");
	}

	let statLabel = $derived(
		mc.statistic === "max_drawdown" ? "Max Drawdown" :
		mc.statistic === "return" ? "Total Return" : "Sharpe Ratio"
	);

	let isPercent = $derived(mc.statistic !== "sharpe");

	function fmtVal(v: number): string {
		return isPercent ? fmtPct(v) : fmtNum(v, 2);
	}

	let pctlEntries = $derived(Object.entries(mc.percentiles));

	let chartOption = $derived.by(() => {
		if (!mc.confidence_bars.length) return null;

		const horizons = mc.confidence_bars.map(b => b.horizon);
		const medians = mc.confidence_bars.map(b => b.pct_50);
		const p5 = mc.confidence_bars.map(b => b.pct_5);
		const p95 = mc.confidence_bars.map(b => b.pct_95);
		const p25 = mc.confidence_bars.map(b => b.pct_25);
		const p75 = mc.confidence_bars.map(b => b.pct_75);

		return {
			...globalChartOptions,
			grid: { left: 60, right: 30, top: 30, bottom: 40 },
			legend: { show: true, top: 0, textStyle: { fontSize: 10 } },
			xAxis: {
				type: "category",
				data: horizons,
				axisLabel: { fontSize: 10 },
			},
			yAxis: {
				type: "value",
				axisLabel: {
					fontSize: 10,
					formatter: isPercent
						? (v: number) => (v * 100).toFixed(1) + "%"
						: (v: number) => v.toFixed(2),
				},
			},
			tooltip: {
				trigger: "axis",
				confine: true,
			},
			series: [
				{
					name: "5th-95th",
					type: "bar",
					data: p95.map((v, i) => v - p5[i]!),
					stack: "band",
					barWidth: "50%",
					itemStyle: { color: "rgba(59, 130, 246, 0.15)", borderColor: "transparent" },
					emphasis: { disabled: true },
				},
				{
					name: "25th-75th",
					type: "bar",
					data: p75.map((v, i) => v - p25[i]!),
					stack: "inner",
					barWidth: "30%",
					itemStyle: { color: "rgba(59, 130, 246, 0.35)", borderColor: "transparent" },
					emphasis: { disabled: true },
				},
				{
					name: "Median",
					type: "line",
					data: medians,
					symbol: "circle",
					symbolSize: 6,
					lineStyle: { color: "rgba(59, 130, 246, 0.9)", width: 2 },
					itemStyle: { color: "rgba(59, 130, 246, 0.9)" },
				},
			],
		} as Record<string, unknown>;
	});
</script>

<section class="ea-panel">
	<h2 class="ea-panel-title">Monte Carlo Simulation</h2>
	<p class="ea-panel-sub">{mc.n_simulations?.toLocaleString() ?? "—"} simulations &middot; Block bootstrap (21-day) &middot; {statLabel}</p>

	<div class="mc-summary">
		<div class="ea-stat">
			<span class="ea-stat-label">Historical</span>
			<span class="ea-stat-value">{fmtVal(mc.historical_value)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Sim. Mean</span>
			<span class="ea-stat-value">{fmtVal(mc.mean)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Sim. Median</span>
			<span class="ea-stat-value">{fmtVal(mc.median)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Sim. Std Dev</span>
			<span class="ea-stat-value">{fmtVal(mc.std)}</span>
		</div>
	</div>

	{#if pctlEntries.length > 0}
		<div class="mc-pctl-table">
			<table>
				<thead>
					<tr>
						{#each pctlEntries as [label] (label)}
							<th>{label}</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					<tr>
						{#each pctlEntries as [, val] (val)}
							<td>{fmtVal(val)}</td>
						{/each}
					</tr>
				</tbody>
			</table>
		</div>
	{/if}

	<ChartContainer
		option={chartOption ?? {}}
		height={280}
		empty={!mc.confidence_bars.length}
		emptyMessage="No confidence bar data"
		ariaLabel="Monte Carlo confidence bars across horizons"
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
		margin: 0 0 4px;
	}

	.ea-panel-sub {
		font-size: 0.75rem;
		color: var(--ii-text-muted);
		margin: 0 0 16px;
	}

	.mc-summary {
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

	.mc-pctl-table {
		overflow-x: auto;
		margin-bottom: 16px;
	}

	.mc-pctl-table table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.75rem;
	}

	.mc-pctl-table th {
		font-weight: 600;
		color: var(--ii-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 6px 8px;
		border-bottom: 1px solid var(--ii-border);
		text-align: center;
	}

	.mc-pctl-table td {
		padding: 6px 8px;
		text-align: center;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
		font-weight: 600;
	}
</style>
