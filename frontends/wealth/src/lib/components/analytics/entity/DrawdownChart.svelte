<!--
  Drawdown Analysis — underwater-style ECharts area chart + worst periods table.
-->
<script lang="ts">
	import { formatPercent, formatNumber } from "@investintell/ui";
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions, statusColors } from "@investintell/ui/charts/echarts-setup";
	import type { DrawdownAnalysis } from "$wealth/types/entity-analytics";

	interface Props {
		drawdown: DrawdownAnalysis;
	}

	let { drawdown }: Props = $props();

	function fmtPct(v: number | null): string {
		if (v == null) return "\u2014";
		return formatPercent(v, 2, "en-US", true);
	}

	let chartOption = $derived.by(() => {
		if (!drawdown.dates.length) return null;
		return {
			...globalChartOptions,
			grid: { left: 60, right: 20, top: 20, bottom: 60 },
			xAxis: {
				type: "category",
				data: drawdown.dates,
				axisLabel: { fontSize: 10, rotate: 0, formatter: (v: string) => v.slice(5) },
				boundaryGap: false,
			},
			yAxis: {
				type: "value",
				axisLabel: { fontSize: 10, formatter: (v: number) => `${formatNumber(v * 100, 1)}%` },
				max: 0,
			},
			tooltip: {
				trigger: "axis",
				confine: true,
				formatter: (params: { data: number; axisValue: string }[]) => {
					const p = params[0];
					if (!p) return "";
					return `<div style="font-size:12px"><b>${p.axisValue}</b><br/>Drawdown: <b style="color:${statusColors.breach}">${formatNumber(p.data * 100, 2)}%</b></div>`;
				},
			},
			dataZoom: [
				{ type: "inside", start: 0, end: 100 },
				{ type: "slider", start: 0, end: 100, height: 20, bottom: 8 },
			],
			series: [
				{
					type: "line",
					data: drawdown.values,
					areaStyle: {
						color: {
							type: "linear",
							x: 0, y: 0, x2: 0, y2: 1,
							colorStops: [
								{ offset: 0, color: "rgba(239, 68, 68, 0.4)" },
								{ offset: 1, color: "rgba(239, 68, 68, 0.05)" },
							],
						},
					},
					lineStyle: { color: "#ef4444", width: 1.5 },
					itemStyle: { color: "#ef4444" },
					symbol: "none",
					smooth: false,
				},
			],
		} as Record<string, unknown>;
	});
</script>

<section class="ea-panel">
	<h2 class="ea-panel-title">Drawdown Analysis</h2>
	<div class="ea-dd-kpis">
		<div class="ea-dd-kpi">
			<span class="ea-stat-label">Max Drawdown</span>
			<span class="ea-stat-value" style:color="var(--ii-danger)">
				{fmtPct(drawdown.max_drawdown)}
			</span>
		</div>
		<div class="ea-dd-kpi">
			<span class="ea-stat-label">Current DD</span>
			<span class="ea-stat-value" style:color={drawdown.current_drawdown && drawdown.current_drawdown < -0.01 ? "var(--ii-danger)" : "var(--ii-text-secondary)"}>
				{fmtPct(drawdown.current_drawdown)}
			</span>
		</div>
		<div class="ea-dd-kpi">
			<span class="ea-stat-label">Longest DD</span>
			<span class="ea-stat-value">{drawdown.longest_duration_days ?? "\u2014"} days</span>
		</div>
		<div class="ea-dd-kpi">
			<span class="ea-stat-label">Avg Recovery</span>
			<span class="ea-stat-value">{drawdown.avg_recovery_days != null ? `${formatNumber(drawdown.avg_recovery_days, 0)} days` : "\u2014"}</span>
		</div>
	</div>
	<ChartContainer
		option={chartOption ?? {}}
		height={280}
		empty={!chartOption}
		emptyMessage="Insufficient data for drawdown analysis"
		ariaLabel="Drawdown analysis chart"
	/>
	{#if drawdown.worst_periods.length}
		<div class="ea-dd-table">
			<table>
				<thead>
					<tr>
						<th>Start</th>
						<th>Trough</th>
						<th>Recovery</th>
						<th>Depth</th>
						<th>Duration</th>
					</tr>
				</thead>
				<tbody>
					{#each drawdown.worst_periods as p (p.start_date)}
						<tr>
							<td>{p.start_date}</td>
							<td>{p.trough_date}</td>
							<td>{p.end_date ?? "open"}</td>
							<td style:color="var(--ii-danger)">{fmtPct(p.depth)}</td>
							<td>{p.duration_days}d</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
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

	.ea-dd-kpis {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
		gap: 12px;
		margin-bottom: 16px;
	}

	.ea-dd-kpi {
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

	.ea-dd-table {
		margin-top: 12px;
		overflow-x: auto;
	}

	.ea-dd-table table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.78rem;
	}

	.ea-dd-table th {
		text-align: left;
		font-weight: 600;
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ii-text-muted);
		padding: 6px 8px;
		border-bottom: 1px solid var(--ii-border);
	}

	.ea-dd-table td {
		padding: 5px 8px;
		color: var(--ii-text-secondary);
		border-bottom: 1px solid color-mix(in srgb, var(--ii-border) 50%, transparent);
		font-variant-numeric: tabular-nums;
	}
</style>
