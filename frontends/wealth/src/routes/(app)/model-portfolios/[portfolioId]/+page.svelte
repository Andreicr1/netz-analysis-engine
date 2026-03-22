<!--
  Model Portfolio Workbench — Committee view with backtest, stress scenarios, fund selection.
  Top: Equity curve placeholder + stress bar chart.
  Bottom: Fund Selection Schema (approved universe assets assigned to this strategy).
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { invalidateAll } from "$app/navigation";
	import {
		PageHeader, Button, StatusBadge, EmptyState, ActionButton,
		formatNumber, formatPercent, formatDateTime,
	} from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { ModelPortfolio, TrackRecord, FundWeight, BacktestFold, StressScenario } from "$lib/types/model-portfolio";
	import { scenarioLabel, profileColor } from "$lib/types/model-portfolio";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let portfolio = $derived(data.portfolio as ModelPortfolio);
	let trackRecord = $derived(data.trackRecord as TrackRecord | null);
	let portfolioId = $derived(data.portfolioId as string);

	let backtest = $derived(trackRecord?.backtest ?? null);
	let stress = $derived(trackRecord?.stress ?? null);
	let funds = $derived(portfolio.fund_selection_schema?.funds ?? [] as FundWeight[]);

	// ── Actions ───────────────────────────────────────────────────────────

	let constructing = $state(false);
	let backtesting = $state(false);
	let stressing = $state(false);
	let error = $state<string | null>(null);

	async function runConstruct() {
		constructing = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/model-portfolios/${portfolioId}/construct`, {});
			await invalidateAll();
		} catch (e) {
			error = e instanceof Error ? e.message : "Construction failed";
		} finally {
			constructing = false;
		}
	}

	async function runBacktest() {
		backtesting = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/model-portfolios/${portfolioId}/backtest`, {});
			await invalidateAll();
		} catch (e) {
			error = e instanceof Error ? e.message : "Backtest failed";
		} finally {
			backtesting = false;
		}
	}

	async function runStress() {
		stressing = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/model-portfolios/${portfolioId}/stress`, {});
			await invalidateAll();
		} catch (e) {
			error = e instanceof Error ? e.message : "Stress test failed";
		} finally {
			stressing = false;
		}
	}

	// ── Stress scenario bar width ─────────────────────────────────────────

	function stressBarWidth(scenarios: StressScenario[], s: StressScenario): number {
		const maxAbs = Math.max(...scenarios.map((x) => Math.abs(x.portfolio_return)), 0.01);
		return (Math.abs(s.portfolio_return) / maxAbs) * 100;
	}
</script>

<PageHeader
	title={portfolio.display_name}
	breadcrumbs={[{ label: "Model Portfolios", href: "/model-portfolios" }, { label: portfolio.display_name }]}
>
	{#snippet actions()}
		<div class="mp-actions">
			<StatusBadge status={portfolio.status} />
			<span class="mp-profile-badge" style:color={profileColor(portfolio.profile)}>
				{portfolio.profile}
			</span>
			{#if !portfolio.fund_selection_schema}
				<Button size="sm" onclick={runConstruct} disabled={constructing}>
					{constructing ? "Constructing…" : "Construct Portfolio"}
				</Button>
			{:else}
				<Button size="sm" variant="outline" onclick={runBacktest} disabled={backtesting}>
					{backtesting ? "Running…" : "Run Backtest"}
				</Button>
				<Button size="sm" variant="outline" onclick={runStress} disabled={stressing}>
					{stressing ? "Running…" : "Stress Test"}
				</Button>
			{/if}
		</div>
	{/snippet}
</PageHeader>

{#if error}
	<div class="mp-error">{error}</div>
{/if}

<div class="mp-workbench">
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- TOP: Backtest + Stress                                             -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<div class="mp-charts">
		<!-- Backtest equity curve placeholder -->
		<section class="mp-section">
			<h3 class="mp-section-title">Backtest — Walk-Forward CV</h3>
			{#if backtest}
				<div class="backtest-metrics">
					<div class="metric-card">
						<span class="metric-label">Mean Sharpe</span>
						<span class="metric-value">
							{backtest.mean_sharpe !== null ? backtest.mean_sharpe.toFixed(3) : "—"}
						</span>
					</div>
					<div class="metric-card">
						<span class="metric-label">Std Sharpe</span>
						<span class="metric-value">
							{backtest.std_sharpe !== null ? backtest.std_sharpe.toFixed(3) : "—"}
						</span>
					</div>
					<div class="metric-card">
						<span class="metric-label">Positive Folds</span>
						<span class="metric-value">{backtest.positive_folds}/{backtest.total_folds}</span>
					</div>
				</div>

				{#if backtest.folds.length > 0}
					<table class="folds-table">
						<thead>
							<tr>
								<th>Fold</th>
								<th>Sharpe</th>
								<th>CVaR 95%</th>
								<th>Max DD</th>
								<th>Obs</th>
							</tr>
						</thead>
						<tbody>
							{#each backtest.folds as fold (fold.fold)}
								<tr>
									<td class="fold-num">{fold.fold}</td>
									<td>{fold.sharpe !== null ? fold.sharpe.toFixed(3) : "—"}</td>
									<td>{fold.cvar_95 !== null ? formatPercent(fold.cvar_95) : "—"}</td>
									<td>{fold.max_drawdown !== null ? formatPercent(fold.max_drawdown) : "—"}</td>
									<td>{formatNumber(fold.n_obs)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			{:else}
				<div class="mp-empty">
					<p>Run backtest to see walk-forward cross-validation results.</p>
				</div>
			{/if}
		</section>

		<!-- Stress scenarios -->
		<section class="mp-section">
			<h3 class="mp-section-title">Stress Scenarios</h3>
			{#if stress && stress.scenarios.length > 0}
				<div class="stress-bars">
					{#each stress.scenarios as scenario (scenario.name)}
						<div class="stress-row">
							<span class="stress-label">{scenarioLabel(scenario.name)}</span>
							<div class="stress-bar-track">
								<div
									class="stress-bar-fill"
									class:stress-bar-negative={scenario.portfolio_return < 0}
									style:width="{stressBarWidth(stress.scenarios, scenario)}%"
								></div>
							</div>
							<span class="stress-value" class:stress-negative={scenario.portfolio_return < 0}>
								{formatPercent(scenario.portfolio_return)}
							</span>
						</div>
						<div class="stress-detail">
							Max DD: {formatPercent(scenario.max_drawdown)}
							{#if scenario.recovery_days !== null}
								· Recovery: {scenario.recovery_days}d
							{/if}
						</div>
					{/each}
				</div>
			{:else}
				<div class="mp-empty">
					<p>Run stress test to see historical scenario impact.</p>
				</div>
			{/if}
		</section>
	</div>

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- BOTTOM: Fund Selection Schema                                      -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<section class="mp-section mp-section--full">
		<h3 class="mp-section-title">
			Fund Selection
			{#if funds.length > 0}
				<span class="mp-section-count">{funds.length} funds · {formatPercent(portfolio.fund_selection_schema?.total_weight ?? 0)} allocated</span>
			{/if}
		</h3>

		{#if funds.length === 0}
			<div class="mp-empty">
				<p>No funds assigned. Run "Construct Portfolio" to auto-select from approved universe.</p>
			</div>
		{:else}
			<div class="fund-table-wrap">
				<table class="fund-table">
					<thead>
						<tr>
							<th class="th-fund">Fund</th>
							<th class="th-block">Block</th>
							<th class="th-weight">Weight</th>
							<th class="th-score">Score</th>
							<th class="th-bar"></th>
						</tr>
					</thead>
					<tbody>
						{#each funds as fund (fund.instrument_id)}
							<tr class="fund-row">
								<td class="td-fund">{fund.fund_name}</td>
								<td class="td-block">{fund.block_id}</td>
								<td class="td-weight">{formatPercent(fund.weight)}</td>
								<td class="td-score">{fund.score.toFixed(1)}</td>
								<td class="td-bar">
									<div class="weight-bar-track">
										<div class="weight-bar-fill" style:width="{fund.weight * 100}%"></div>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>
</div>

<style>
	/* ── Actions bar ─────────────────────────────────────────────────────── */
	.mp-actions {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-sm, 10px);
	}

	.mp-profile-badge {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.mp-error {
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-lg, 24px);
		background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
		color: var(--netz-danger);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	/* ── Workbench layout ────────────────────────────────────────────────── */
	.mp-workbench {
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-md, 16px);
	}

	.mp-charts {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--netz-space-stack-md, 16px);
	}

	@media (max-width: 900px) {
		.mp-charts {
			grid-template-columns: 1fr;
		}
	}

	.mp-section {
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
		background: var(--netz-surface-elevated);
		overflow: hidden;
	}

	.mp-section--full {
		grid-column: 1 / -1;
	}

	.mp-section-title {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px);
		font-size: var(--netz-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--netz-text-primary);
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-alt);
	}

	.mp-section-count {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 400;
		color: var(--netz-text-muted);
	}

	.mp-empty {
		padding: var(--netz-space-stack-lg, 32px);
		text-align: center;
		color: var(--netz-text-muted);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	/* ── Backtest metrics ────────────────────────────────────────────────── */
	.backtest-metrics {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 1px;
		background: var(--netz-border-subtle);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.metric-card {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-sm, 12px);
		background: var(--netz-surface-elevated);
	}

	.metric-label {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.metric-value {
		font-size: var(--netz-text-h4, 1.125rem);
		font-weight: 700;
		color: var(--netz-text-primary);
		font-variant-numeric: tabular-nums;
	}

	/* ── Folds table ─────────────────────────────────────────────────────── */
	.folds-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.folds-table th {
		padding: var(--netz-space-stack-2xs, 5px) var(--netz-space-inline-sm, 10px);
		text-align: left;
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		color: var(--netz-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.02em;
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.folds-table td {
		padding: var(--netz-space-stack-2xs, 5px) var(--netz-space-inline-sm, 10px);
		border-bottom: 1px solid var(--netz-border-subtle);
		font-variant-numeric: tabular-nums;
		color: var(--netz-text-secondary);
	}

	.fold-num {
		font-weight: 600;
		color: var(--netz-text-primary);
	}

	/* ── Stress bars ─────────────────────────────────────────────────────── */
	.stress-bars {
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px);
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-2xs, 4px);
	}

	.stress-row {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-sm, 10px);
	}

	.stress-label {
		width: 120px;
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--netz-text-primary);
		flex-shrink: 0;
	}

	.stress-bar-track {
		flex: 1;
		height: 18px;
		background: var(--netz-surface-alt);
		border-radius: 4px;
		overflow: hidden;
	}

	.stress-bar-fill {
		height: 100%;
		border-radius: 4px;
		background: var(--netz-success);
		transition: width 300ms ease;
	}

	.stress-bar-negative {
		background: var(--netz-danger);
	}

	.stress-value {
		width: 70px;
		text-align: right;
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--netz-text-primary);
	}

	.stress-negative {
		color: var(--netz-danger);
	}

	.stress-detail {
		padding-left: 130px;
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
		margin-bottom: var(--netz-space-stack-xs, 8px);
	}

	/* ── Fund selection table ────────────────────────────────────────────── */
	.fund-table-wrap {
		overflow-x: auto;
	}

	.fund-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.fund-table th {
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-sm, 12px);
		text-align: left;
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		color: var(--netz-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.02em;
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.fund-table td {
		padding: var(--netz-space-stack-2xs, 8px) var(--netz-space-inline-sm, 12px);
		border-bottom: 1px solid var(--netz-border-subtle);
		vertical-align: middle;
	}

	.fund-row:hover {
		background: var(--netz-surface-highlight, color-mix(in srgb, var(--netz-brand-primary) 4%, transparent));
	}

	.th-fund { min-width: 200px; }
	.th-block { min-width: 120px; }
	.th-weight { width: 80px; text-align: right; }
	.th-score { width: 60px; text-align: right; }
	.th-bar { width: 120px; }

	.td-fund { font-weight: 500; color: var(--netz-text-primary); }
	.td-block { color: var(--netz-text-secondary); }
	.td-weight { text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--netz-text-primary); }
	.td-score { text-align: right; font-variant-numeric: tabular-nums; color: var(--netz-text-secondary); }

	.weight-bar-track {
		height: 6px;
		background: var(--netz-surface-alt);
		border-radius: 3px;
		overflow: hidden;
	}

	.weight-bar-fill {
		height: 100%;
		background: var(--netz-brand-primary);
		border-radius: 3px;
		transition: width 200ms ease;
	}
</style>
