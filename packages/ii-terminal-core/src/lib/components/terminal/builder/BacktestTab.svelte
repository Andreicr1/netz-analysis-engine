<!--
  BacktestTab — BACKTEST tab in the Builder results panel.

  Equity curve (NAV line chart) + drawdown underwater chart + metrics sidebar.
  Period selector (1Y/3Y/5Y/10Y) re-fetches from nav-history endpoint.
  Data sourced from workspace.backtestData.
-->
<script lang="ts">
	import { formatNumber, formatPercent, createTerminalChartOptions, readTerminalTokens } from "@investintell/ui";
	import { workspace } from "../../../state/portfolio-workspace.svelte";
	import TerminalChart from "../../../components/terminal/charts/TerminalChart.svelte";
	import type { EChartsOption } from "echarts";

	const PERIODS = ["1Y", "3Y", "5Y", "10Y"] as const;
	type Period = (typeof PERIODS)[number];
	let activePeriod = $state<Period>("5Y");

	// Fetch on mount
	$effect(() => {
		if (workspace.portfolioId && !workspace.backtestData && !workspace.isLoadingBacktest) {
			workspace.fetchBacktestData(activePeriod);
		}
	});

	function selectPeriod(p: Period) {
		activePeriod = p;
		workspace.fetchBacktestData(p);
	}

	const data = $derived(workspace.backtestData);
	const metrics = $derived(data?.metrics ?? null);
	const isEmpty = $derived(!data || data.dates.length === 0);

	// PR-A5 B.5 — phase gating for the pre-run empty states.
	const run = $derived(workspace.constructionRun);
	const isIdle = $derived(
		run === null && workspace.runPhase === "idle" && isEmpty,
	);
	const isInFlight = $derived(
		run === null &&
			workspace.runPhase !== "idle" &&
			workspace.runPhase !== "done" &&
			workspace.runPhase !== "error" &&
			workspace.runPhase !== "cancelled" &&
			isEmpty,
	);

	// Equity curve chart option
	const navOption = $derived.by<EChartsOption>(() => {
		if (isEmpty || !data) return createTerminalChartOptions({ series: [] });
		const tokens = readTerminalTokens();
		return createTerminalChartOptions({
			series: [
				{
					type: "line",
					name: "NAV",
					data: data.dates.map((d, i) => [d, data.nav_series[i]]),
					showSymbol: false,
					lineStyle: { width: 1.5, color: tokens.accentAmber },
					itemStyle: { color: tokens.accentAmber },
					areaStyle: { color: tokens.accentAmber, opacity: 0.08 },
				},
			],
			slot: "primary",
		});
	});

	// Drawdown chart option
	const ddOption = $derived.by<EChartsOption>(() => {
		if (isEmpty || !data) return createTerminalChartOptions({ series: [] });
		const tokens = readTerminalTokens();
		return createTerminalChartOptions({
			series: [
				{
					type: "line",
					name: "Drawdown",
					data: data.dates.map((d, i) => [d, data.drawdown_series[i]]),
					showSymbol: false,
					lineStyle: { width: 1, color: tokens.statusError },
					itemStyle: { color: tokens.statusError },
					areaStyle: { color: tokens.statusError, opacity: 0.2 },
				},
			],
			yAxis: {
				type: "value" as const,
				axisLabel: {
					formatter: (v: number) => formatPercent(v, 0),
				},
			},
			slot: "secondary",
		});
	});

	function metricColor(value: number | null, threshold: number, invert: boolean = false): string {
		if (value === null) return "var(--terminal-fg-muted)";
		const bad = invert ? value > threshold : value < threshold;
		return bad ? "var(--terminal-status-error)" : "var(--terminal-status-success)";
	}
</script>

<div class="bt-root">
	{#if isIdle && !workspace.isLoadingBacktest}
		<div class="bt-empty">Aguardando construction run</div>
	{:else if isInFlight && !workspace.isLoadingBacktest}
		<div class="bt-skeleton" aria-busy="true">
			<div class="bt-skeleton-line bt-skeleton-line--wide"></div>
			<div class="bt-skeleton-line"></div>
			<div class="bt-skeleton-line bt-skeleton-line--narrow"></div>
		</div>
	{:else if isEmpty && !workspace.isLoadingBacktest}
		<div class="bt-empty">Run the NAV synthesizer to see historical performance</div>
	{:else}
		<div class="bt-layout">
			<div class="bt-charts">
				<div class="bt-chart-label">Equity Curve</div>
				<TerminalChart
					option={navOption}
					height={180}
					loading={workspace.isLoadingBacktest}
					empty={isEmpty}
					emptyMessage="NO NAV DATA"
					ariaLabel="Portfolio equity curve"
				/>
				<div class="bt-chart-label">Drawdown</div>
				<TerminalChart
					option={ddOption}
					height={140}
					loading={workspace.isLoadingBacktest}
					empty={isEmpty}
					emptyMessage="NO DRAWDOWN DATA"
					ariaLabel="Portfolio drawdown underwater chart"
				/>
				<!-- Period selector -->
				<div class="bt-period-bar">
					{#each PERIODS as p (p)}
						<button
							type="button"
							class="bt-period-btn"
							class:bt-period-btn--active={activePeriod === p}
							onclick={() => selectPeriod(p)}
						>
							{p}
						</button>
					{/each}
				</div>
			</div>

			<!-- Metrics sidebar -->
			<div class="bt-metrics">
				<div class="bt-metric">
					<div class="bt-metric-label">Sharpe Ratio</div>
					<div class="bt-metric-value">
						{metrics?.sharpe != null ? formatNumber(metrics.sharpe, 2) : "\u2014"}
					</div>
				</div>
				<div class="bt-metric">
					<div class="bt-metric-label">Maximum Drawdown</div>
					<div
						class="bt-metric-value"
						style="color: {metricColor(metrics?.max_dd ?? null, -0.10)}"
					>
						{metrics?.max_dd != null ? formatPercent(metrics.max_dd, 1) : "\u2014"}
					</div>
				</div>
				<div class="bt-metric">
					<div class="bt-metric-label">Annualized Return</div>
					<div
						class="bt-metric-value"
						style="color: {metricColor(metrics?.ann_return ?? null, 0, true)}"
					>
						{metrics?.ann_return != null ? formatPercent(metrics.ann_return, 1) : "\u2014"}
					</div>
				</div>
				<div class="bt-metric">
					<div class="bt-metric-label">Calmar Ratio</div>
					<div class="bt-metric-value">
						{metrics?.calmar != null ? formatNumber(metrics.calmar, 2) : "\u2014"}
					</div>
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	.bt-root {
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-secondary);
	}

	.bt-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 300px;
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-12);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.bt-layout {
		display: grid;
		grid-template-columns: 1fr 120px;
		gap: 0;
	}

	.bt-charts {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
	}

	.bt-chart-label {
		font-size: var(--terminal-text-10);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		padding: var(--terminal-space-1) 0;
	}

	.bt-period-bar {
		display: flex;
		gap: var(--terminal-space-1);
		padding: var(--terminal-space-2) 0;
	}

	.bt-period-btn {
		background: transparent;
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-tertiary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		padding: var(--terminal-space-1) var(--terminal-space-2);
		cursor: pointer;
		border-radius: var(--terminal-radius-none);
		transition: color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.bt-period-btn:hover {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber);
	}

	.bt-period-btn--active {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber);
		background: var(--terminal-bg-panel-raised);
	}

	.bt-period-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}

	/* Metrics sidebar */
	.bt-metrics {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-4);
		padding: var(--terminal-space-4) var(--terminal-space-2);
		border-left: var(--terminal-border-hairline);
	}

	.bt-metric {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.bt-metric-label {
		font-size: var(--terminal-text-10);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-muted);
	}

	.bt-metric-value {
		font-size: var(--terminal-text-14);
		font-weight: 700;
		color: var(--terminal-fg-primary);
	}

	/* ── PR-A5 B.5 — shimmer skeleton ────────────────── */

	.bt-skeleton {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-4);
	}

	.bt-skeleton-line {
		height: 12px;
		background: linear-gradient(
			90deg,
			var(--terminal-bg-panel-raised) 0%,
			var(--terminal-fg-muted) 50%,
			var(--terminal-bg-panel-raised) 100%
		);
		background-size: 200% 100%;
		animation: bt-shimmer 1.4s linear infinite;
		opacity: 0.4;
	}

	.bt-skeleton-line--wide {
		width: 80%;
	}

	.bt-skeleton-line--narrow {
		width: 45%;
	}

	@keyframes bt-shimmer {
		0% { background-position: 200% 0; }
		100% { background-position: -200% 0; }
	}
</style>
