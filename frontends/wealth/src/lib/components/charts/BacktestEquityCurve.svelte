<!--
  Backtest Equity Curve — horizontal bar chart of Sharpe per fold + KPI summary.
  Uses ChartContainer from @investintell/ui/charts.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import { formatNumber, formatPercent, formatDate } from "@investintell/ui";
	import type { BacktestFold } from "$lib/types/model-portfolio";

	interface Props {
		folds: BacktestFold[];
		youngestFundStart?: string | null;
		height?: number;
	}

	let { folds, youngestFundStart = null, height = 240 }: Props = $props();

	let isEmpty = $derived(folds.length === 0);

	// KPI summary
	let kpis = $derived.by(() => {
		if (folds.length === 0) return null;
		const sharpes = folds.map((f) => f.sharpe).filter((s): s is number => s !== null);
		const cvars = folds.map((f) => f.cvar_95).filter((c): c is number => c !== null);
		const sorted = [...sharpes].sort((a, b) => a - b);
		const median = sorted.length > 0
			? sorted.length % 2 === 0
				? (sorted[sorted.length / 2 - 1]! + sorted[sorted.length / 2]!) / 2
				: sorted[Math.floor(sorted.length / 2)]!
			: null;
		const positiveFolds = sharpes.filter((s) => s > 0).length;
		const worstCvar = cvars.length > 0 ? Math.min(...cvars) : null;
		return { consistency: `${positiveFolds}/${folds.length}`, median, worstCvar };
	});

	function sharpeColor(sharpe: number | null): string {
		if (sharpe === null) return "var(--ii-text-muted)";
		if (sharpe >= 1.0) return "var(--ii-success)";
		if (sharpe >= 0) return "#86efac";
		if (sharpe >= -0.5) return "var(--ii-warning)";
		return "var(--ii-danger)";
	}

	let option = $derived.by(() => {
		if (isEmpty) return {};

		const foldLabels = folds.map((f) => `Fold ${f.fold}`);
		const sharpeValues = folds.map((f) => f.sharpe ?? 0);

		return {
			...globalChartOptions,
			grid: { left: 70, right: 40, top: 10, bottom: 30, containLabel: false },
			tooltip: {
				...globalChartOptions.tooltip,
				formatter(params: unknown) {
					const p = Array.isArray(params) ? params[0] : params;
					const { dataIndex } = p as { dataIndex: number };
					const fold = folds[dataIndex];
					if (!fold) return "";
					let html = `<strong>Fold ${fold.fold}</strong>`;
					html += `<br/>Sharpe: ${fold.sharpe !== null ? formatNumber(fold.sharpe, 3) : "—"}`;
					html += `<br/>CVaR 95%: ${fold.cvar_95 !== null ? formatPercent(fold.cvar_95) : "—"}`;
					html += `<br/>Max DD: ${fold.max_drawdown !== null ? formatPercent(fold.max_drawdown) : "—"}`;
					html += `<br/>Observations: ${formatNumber(fold.n_obs)}`;
					return html;
				},
			},
			xAxis: {
				type: "value" as const,
				axisLabel: { fontSize: 10 },
				splitLine: { lineStyle: { color: "var(--ii-border-subtle)", type: "dashed" as const } },
			},
			yAxis: {
				type: "category" as const,
				data: foldLabels,
				inverse: true,
				axisLabel: { fontSize: 11 },
				axisTick: { show: false },
				axisLine: { show: false },
			},
			series: [
				{
					name: "Sharpe",
					type: "bar" as const,
					data: sharpeValues.map((v, i) => ({
						value: v,
						itemStyle: {
							color: sharpeColor(folds[i]?.sharpe ?? null),
							borderRadius: v >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4],
							opacity: (folds[i]?.n_obs ?? 100) < 60 ? 0.4 : 1.0,
						},
					})),
					barWidth: "60%",
					label: {
						show: true,
						position: "right" as const,
						fontSize: 10,
						formatter: (p: { value: number }) => formatNumber(p.value, 2),
					},
					markLine: {
						silent: true,
						symbol: "none" as const,
						data: [{ xAxis: 0 }],
						lineStyle: { color: "var(--ii-text-muted)", type: "solid" as const, width: 1 },
						label: { show: false },
					},
				},
			],
			aria: { enabled: true },
		};
	});
</script>

{#if youngestFundStart}
	<div class="bt-youngest-warning">
		Backtest limited to data since <strong>{formatDate(youngestFundStart)}</strong>
		due to newest fund inception date.
	</div>
{/if}

{#if kpis}
	<div class="bt-kpi-row">
		<div class="bt-kpi">
			<span class="bt-kpi-label">Consistency</span>
			<span class="bt-kpi-value">{kpis.consistency} folds</span>
		</div>
		<div class="bt-kpi">
			<span class="bt-kpi-label">Median Sharpe</span>
			<span class="bt-kpi-value">{kpis.median !== null ? formatNumber(kpis.median, 3) : "—"}</span>
		</div>
		<div class="bt-kpi">
			<span class="bt-kpi-label">Worst CVaR</span>
			<span class="bt-kpi-value">{kpis.worstCvar !== null ? formatPercent(kpis.worstCvar) : "—"}</span>
		</div>
	</div>
{/if}

{#if isEmpty}
	<p class="bt-empty">No fold data available.</p>
{:else}
	<ChartContainer {option} {height} />
{/if}

<style>
	.bt-youngest-warning {
		display: flex;
		align-items: center;
		gap: 8px;
		border-radius: 8px;
		border: 1px solid var(--ii-warning-border, #fde68a);
		background: color-mix(in srgb, var(--ii-warning) 8%, transparent);
		padding: 8px 16px;
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-warning);
		margin-bottom: 12px;
	}

	.bt-kpi-row {
		display: flex;
		gap: 24px;
		margin-bottom: 12px;
	}

	.bt-kpi {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.bt-kpi-label {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-weight: 500;
	}

	.bt-kpi-value {
		font-size: var(--ii-text-body, 0.875rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.bt-empty {
		text-align: center;
		color: var(--ii-text-muted);
		padding: 24px;
		font-size: var(--ii-text-small, 0.8125rem);
	}
</style>
