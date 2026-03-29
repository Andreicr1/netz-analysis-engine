<!--
  Model Portfolio Workbench — Committee view with backtest, stress scenarios, fund selection, fact sheets.
  Top: Equity curve placeholder + stress bar chart.
  Bottom: Fund Selection Schema + Fact Sheets.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { invalidateAll } from "$app/navigation";
	import {
		PageHeader, StatusBadge, EmptyState, ActionButton,
		formatNumber, formatPercent, formatDateTime, formatDate,
	} from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { ModelPortfolio, TrackRecord, InstrumentWeight, BacktestFold, StressScenario, PortfolioView, ParametricStressResult } from "$lib/types/model-portfolio";
	import type { UniverseAsset } from "$lib/types/universe";
	import ICViewsPanel from "$lib/components/model-portfolio/ICViewsPanel.svelte";
	import { instrumentTypeLabel, instrumentTypeColor } from "$lib/types/universe";
	import { scenarioLabel, profileColor, blockLabel } from "$lib/types/model-portfolio";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let portfolio = $derived(data.portfolio as ModelPortfolio);
	let trackRecord = $derived(data.trackRecord as TrackRecord | null);
	let portfolioId = $derived(data.portfolioId as string);

	let actorRole = $derived((data.actorRole ?? null) as string | null);
	let views = $derived((data.views ?? []) as PortfolioView[]);
	let instruments = $derived((data.instruments ?? []) as UniverseAsset[]);

	const IC_ROLES = ["investment_team", "director", "admin"];
	let canEdit = $derived(actorRole !== null && IC_ROLES.includes(actorRole));

	let backtest = $derived(trackRecord?.backtest ?? null);
	let stress = $derived(trackRecord?.stress ?? null);
	let funds = $derived(portfolio.fund_selection_schema?.funds ?? [] as InstrumentWeight[]);

	// ── Fact Sheets ──────────────────────────────────────────────────────

	interface FactSheet {
		path: string;
		portfolio_name: string;
		portfolio_id: string;
		period: string | null;
		language: string | null;
		created_at: string | null;
		format: string | null;
	}

	let factSheets = $derived((data.factSheets ?? []) as FactSheet[]);

	let generating = $state(false);
	let generateLang = $state<"pt" | "en">("pt");
	let downloadingPath = $state<string | null>(null);
	let factSheetError = $state<string | null>(null);

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

	async function generateFactSheet() {
		generating = true;
		factSheetError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/fact-sheets/model-portfolios/${portfolioId}`, { language: generateLang });
			await invalidateAll();
		} catch (e) {
			factSheetError = e instanceof Error ? e.message : "Failed to generate fact sheet";
		} finally {
			generating = false;
		}
	}

	async function downloadFactSheet(path: string) {
		downloadingPath = path;
		factSheetError = null;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(`/fact-sheets/${encodeURIComponent(path)}/download`);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `fact-sheet-${portfolio.display_name.toLowerCase().replace(/\s+/g, "-")}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			factSheetError = e instanceof Error ? e.message : "Download failed";
		} finally {
			downloadingPath = null;
		}
	}

	// ── Stress scenario bar width ─────────────────────────────────────────

	function stressBarWidth(scenarios: StressScenario[], s: StressScenario): number {
		const maxAbs = Math.max(...scenarios.map((x) => Math.abs(x.portfolio_return)), 0.01);
		return (Math.abs(s.portfolio_return) / maxAbs) * 100;
	}

	// ── Custom Parametric Stress ──────────────────────────────────────────

	/** Block IDs present in current portfolio fund selection */
	let portfolioBlocks: string[] = $derived.by(() => {
		const blocks = new Set<string>();
		for (const f of funds) {
			if (f.block_id) blocks.add(f.block_id);
		}
		return [...blocks].sort();
	});

	type ShockEntry = { block_id: string; shock_pct: string };

	let customShocks = $state<ShockEntry[]>([]);
	let customPreset = $state<string>("custom");
	let customRunning = $state(false);
	let customResult = $state<ParametricStressResult | null>(null);
	let customError = $state<string | null>(null);

	const PRESETS: { value: string; label: string }[] = [
		{ value: "custom", label: "Custom" },
		{ value: "gfc_2008", label: "GFC 2008" },
		{ value: "covid_2020", label: "COVID 2020" },
		{ value: "taper_2013", label: "Taper 2013" },
		{ value: "rate_shock_200bps", label: "Rate Shock +200bp" },
	];

	function initCustomShocks() {
		if (portfolioBlocks.length > 0 && customShocks.length === 0) {
			customShocks = portfolioBlocks.map((b: string) => ({ block_id: b, shock_pct: "0" }));
		}
	}

	// Initialize shocks when portfolio blocks become available
	$effect(() => {
		initCustomShocks();
	});

	async function runCustomStress() {
		customRunning = true;
		customError = null;
		customResult = null;
		try {
			const api = createClientApiClient(getToken);
			const payload: { scenario_name: string; shocks?: Record<string, number> } = {
				scenario_name: customPreset,
			};
			if (customPreset === "custom") {
				const shocks: Record<string, number> = {};
				for (const entry of customShocks) {
					const val = parseFloat(entry.shock_pct);
					if (!isNaN(val) && val !== 0) {
						shocks[entry.block_id] = val / 100; // convert % to decimal
					}
				}
				if (Object.keys(shocks).length === 0) {
					customError = "Enter at least one non-zero shock value.";
					customRunning = false;
					return;
				}
				payload.shocks = shocks;
			}
			customResult = await api.post<ParametricStressResult>(
				`/model-portfolios/${portfolioId}/stress-test`,
				payload,
			);
		} catch (e) {
			customError = e instanceof Error ? e.message : "Stress test failed";
		} finally {
			customRunning = false;
		}
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
	<!-- PARAMETRIC STRESS (custom shocks)                                  -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	{#if portfolio.fund_selection_schema && canEdit}
		<section class="mp-section mp-section--full">
			<h3 class="mp-section-title">Custom Stress Scenario</h3>
			<div class="cs-content">
				<div class="cs-controls">
					<label class="cs-label">
						Preset
						<select class="cs-select" bind:value={customPreset}>
							{#each PRESETS as p (p.value)}
								<option value={p.value}>{p.label}</option>
							{/each}
						</select>
					</label>
					<Button size="sm" onclick={runCustomStress} disabled={customRunning || !portfolio.fund_selection_schema}>
						{customRunning ? "Running…" : "Run Scenario"}
					</Button>
				</div>

				{#if customPreset === "custom"}
					<div class="cs-shocks-grid">
						{#each customShocks as entry (entry.block_id)}
							<label class="cs-shock-field">
								<span class="cs-shock-label">{blockLabel(entry.block_id)}</span>
								<div class="cs-shock-input-wrap">
									<input
										type="number"
										step="1"
										class="cs-shock-input"
										bind:value={entry.shock_pct}
										placeholder="0"
									/>
									<span class="cs-shock-unit">%</span>
								</div>
							</label>
						{/each}
					</div>
					<p class="cs-hint">Negative = loss. E.g. -38 means -38% shock to that block.</p>
				{/if}

				{#if customError}
					<div class="cs-error">{customError}</div>
				{/if}

				{#if customResult}
					<div class="cs-result">
						<div class="cs-result-header">
							<span class="cs-result-scenario">{customResult.scenario_name.replace(/_/g, " ")}</span>
							<span
								class="cs-result-nav"
								class:stress-negative={customResult.nav_impact_pct < 0}
							>
								NAV Impact: {formatPercent(customResult.nav_impact_pct)}
							</span>
							{#if customResult.cvar_stressed !== null}
								<span class="cs-result-cvar">CVaR 95%: {formatPercent(customResult.cvar_stressed)}</span>
							{/if}
						</div>
						<div class="cs-block-impacts">
							{#each Object.entries(customResult.block_impacts) as [blockId, impact] (blockId)}
								<div class="cs-block-row">
									<span class="cs-block-name"
										class:cs-block-worst={blockId === customResult.worst_block}
										class:cs-block-best={blockId === customResult.best_block}
									>{blockLabel(blockId)}</span>
									<div class="stress-bar-track">
										<div
											class="stress-bar-fill"
											class:stress-bar-negative={impact < 0}
											style:width="{Math.min(Math.abs(impact) / Math.max(...Object.values(customResult.block_impacts).map(Math.abs), 0.001) * 100, 100)}%"
										></div>
									</div>
									<span class="stress-value" class:stress-negative={impact < 0}>
										{formatPercent(impact)}
									</span>
								</div>
							{/each}
						</div>
						{#if customResult.worst_block || customResult.best_block}
							<div class="cs-extremes">
								{#if customResult.worst_block}
									<span class="cs-extreme cs-extreme-worst">Worst: {blockLabel(customResult.worst_block)}</span>
								{/if}
								{#if customResult.best_block}
									<span class="cs-extreme cs-extreme-best">Best: {blockLabel(customResult.best_block)}</span>
								{/if}
							</div>
						{/if}
					</div>
				{/if}
			</div>
		</section>
	{/if}

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
							<th class="th-fund">Instrument</th>
							<th class="th-itype">Type</th>
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
								<td class="td-itype">
									<span class="itype-badge" style:color={instrumentTypeColor(fund.instrument_type)} style:background="color-mix(in srgb, {instrumentTypeColor(fund.instrument_type)} 12%, transparent)">
										{instrumentTypeLabel(fund.instrument_type)}
									</span>
								</td>
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

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- IC VIEWS (Black-Litterman)                                         -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<ICViewsPanel {portfolioId} {views} {instruments} {canEdit} />

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- FACT SHEETS                                                        -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<section class="mp-section mp-section--full">
		<h3 class="mp-section-title">
			Fact Sheets
			{#if factSheets.length > 0}
				<span class="mp-section-count">{factSheets.length} generated</span>
			{/if}
		</h3>

		{#if factSheetError}
			<div class="fs-error">
				{factSheetError}
				<button class="fs-error-dismiss" onclick={() => factSheetError = null}>dismiss</button>
			</div>
		{/if}

		<div class="fs-content">
			<div class="fs-generate">
				<select class="fs-lang-select" bind:value={generateLang}>
					<option value="pt">Portugues</option>
					<option value="en">English</option>
				</select>
				<Button size="sm" onclick={generateFactSheet} disabled={generating}>
					{generating ? "Generating…" : "Generate Fact Sheet"}
				</Button>
			</div>

			{#if factSheets.length === 0}
				<div class="mp-empty">
					<p>No fact sheets generated yet.</p>
				</div>
			{:else}
				<div class="fs-list">
					{#each factSheets as fs (fs.path)}
						<div class="fs-row">
							<div class="fs-info">
								<span class="fs-format">{fs.format ?? "Fact Sheet"}</span>
								{#if fs.language}
									<span class="fs-lang-badge">{fs.language.toUpperCase()}</span>
								{/if}
								{#if fs.period}
									<span class="fs-period">{fs.period}</span>
								{/if}
								{#if fs.created_at}
									<span class="fs-date">{formatDate(fs.created_at)}</span>
								{/if}
							</div>
							<Button
								size="sm"
								variant="outline"
								onclick={() => downloadFactSheet(fs.path)}
								disabled={downloadingPath === fs.path}
							>
								{downloadingPath === fs.path ? "…" : "Download"}
							</Button>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	</section>
</div>

<style>
	/* ── Actions bar ─────────────────────────────────────────────────────── */
	.mp-actions {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 10px);
	}

	.mp-profile-badge {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.mp-error {
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-lg, 24px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	/* ── Workbench layout ────────────────────────────────────────────────── */
	.mp-workbench {
		padding: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px);
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-md, 16px);
	}

	.mp-charts {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--ii-space-stack-md, 16px);
	}

	@media (max-width: 900px) {
		.mp-charts {
			grid-template-columns: 1fr;
		}
	}

	.mp-section {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		overflow: hidden;
	}

	.mp-section--full {
		grid-column: 1 / -1;
	}

	.mp-section-title {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.mp-section-count {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 400;
		color: var(--ii-text-muted);
	}

	.mp-empty {
		padding: var(--ii-space-stack-lg, 32px);
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	/* ── Backtest metrics ────────────────────────────────────────────────── */
	.backtest-metrics {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 1px;
		background: var(--ii-border-subtle);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.metric-card {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-sm, 12px);
		background: var(--ii-surface-elevated);
	}

	.metric-label {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.metric-value {
		font-size: var(--ii-text-h4, 1.125rem);
		font-weight: 700;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}

	/* ── Folds table ─────────────────────────────────────────────────────── */
	.folds-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.folds-table th {
		padding: var(--ii-space-stack-2xs, 5px) var(--ii-space-inline-sm, 10px);
		text-align: left;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.02em;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.folds-table td {
		padding: var(--ii-space-stack-2xs, 5px) var(--ii-space-inline-sm, 10px);
		border-bottom: 1px solid var(--ii-border-subtle);
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-secondary);
	}

	.fold-num {
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	/* ── Stress bars ─────────────────────────────────────────────────────── */
	.stress-bars {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-2xs, 4px);
	}

	.stress-row {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 10px);
	}

	.stress-label {
		width: 120px;
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--ii-text-primary);
		flex-shrink: 0;
	}

	.stress-bar-track {
		flex: 1;
		height: 18px;
		background: var(--ii-surface-alt);
		border-radius: 4px;
		overflow: hidden;
	}

	.stress-bar-fill {
		height: 100%;
		border-radius: 4px;
		background: var(--ii-success);
		transition: width 300ms ease;
	}

	.stress-bar-negative {
		background: var(--ii-danger);
	}

	.stress-value {
		width: 70px;
		text-align: right;
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
	}

	.stress-negative {
		color: var(--ii-danger);
	}

	.stress-detail {
		padding-left: 130px;
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		margin-bottom: var(--ii-space-stack-xs, 8px);
	}

	/* ── Custom Stress Scenario ──────────────────────────────────────────── */
	.cs-content {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-sm, 12px);
	}

	.cs-controls {
		display: flex;
		align-items: flex-end;
		gap: var(--ii-space-inline-md, 16px);
	}

	.cs-label {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.02em;
	}

	.cs-select {
		height: var(--ii-space-control-height-sm, 32px);
		padding: 0 var(--ii-space-inline-sm, 10px);
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 6px);
		background: var(--ii-surface);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-family: var(--ii-font-sans);
	}

	.cs-shocks-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
		gap: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 16px);
	}

	.cs-shock-field {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}

	.cs-shock-label {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-weight: 500;
	}

	.cs-shock-input-wrap {
		display: flex;
		align-items: center;
	}

	.cs-shock-input {
		width: 80px;
		height: var(--ii-space-control-height-sm, 32px);
		padding: 0 var(--ii-space-inline-xs, 8px);
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 6px) 0 0 var(--ii-radius-sm, 6px);
		background: var(--ii-surface);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-variant-numeric: tabular-nums;
		font-family: var(--ii-font-sans);
		text-align: right;
	}

	.cs-shock-input:focus {
		outline: none;
		border-color: var(--ii-brand-primary);
	}

	.cs-shock-unit {
		height: var(--ii-space-control-height-sm, 32px);
		display: flex;
		align-items: center;
		padding: 0 6px;
		border: 1px solid var(--ii-border);
		border-left: none;
		border-radius: 0 var(--ii-radius-sm, 6px) var(--ii-radius-sm, 6px) 0;
		background: var(--ii-surface-alt);
		color: var(--ii-text-muted);
		font-size: var(--ii-text-label, 0.75rem);
	}

	.cs-hint {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.cs-error {
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-sm, 10px);
		border-radius: var(--ii-radius-sm, 6px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.cs-result {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-xs, 8px);
		padding: var(--ii-space-stack-sm, 12px);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 10px);
		background: var(--ii-surface-alt);
	}

	.cs-result-header {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-md, 16px);
		flex-wrap: wrap;
	}

	.cs-result-scenario {
		font-weight: 600;
		font-size: var(--ii-text-body, 0.9375rem);
		color: var(--ii-text-primary);
		text-transform: capitalize;
	}

	.cs-result-nav {
		font-size: var(--ii-text-h4, 1.125rem);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-success);
	}

	.cs-result-nav.stress-negative {
		color: var(--ii-danger);
	}

	.cs-result-cvar {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.cs-block-impacts {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-2xs, 4px);
	}

	.cs-block-row {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 10px);
	}

	.cs-block-name {
		width: 120px;
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-secondary);
		flex-shrink: 0;
	}

	.cs-block-worst {
		color: var(--ii-danger);
		font-weight: 600;
	}

	.cs-block-best {
		color: var(--ii-success);
		font-weight: 600;
	}

	.cs-extremes {
		display: flex;
		gap: var(--ii-space-inline-lg, 24px);
		padding-top: var(--ii-space-stack-2xs, 4px);
		border-top: 1px solid var(--ii-border-subtle);
	}

	.cs-extreme {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
	}

	.cs-extreme-worst { color: var(--ii-danger); }
	.cs-extreme-best { color: var(--ii-success); }

	/* ── Fund selection table ────────────────────────────────────────────── */
	.fund-table-wrap {
		overflow-x: auto;
	}

	.fund-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.fund-table th {
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-sm, 12px);
		text-align: left;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.02em;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.fund-table td {
		padding: var(--ii-space-stack-2xs, 8px) var(--ii-space-inline-sm, 12px);
		border-bottom: 1px solid var(--ii-border-subtle);
		vertical-align: middle;
	}

	.fund-row:hover {
		background: var(--ii-surface-highlight, color-mix(in srgb, var(--ii-brand-primary) 4%, transparent));
	}

	.th-fund { min-width: 200px; }
	.th-itype { min-width: 90px; }
	.th-block { min-width: 120px; }
	.th-weight { width: 80px; text-align: right; }
	.th-score { width: 60px; text-align: right; }
	.th-bar { width: 120px; }

	.td-fund { font-weight: 500; color: var(--ii-text-primary); }

	.itype-badge {
		display: inline-block;
		padding: 1px 8px;
		border-radius: var(--ii-radius-pill, 999px);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 500;
		white-space: nowrap;
	}

	.td-block { color: var(--ii-text-secondary); }
	.td-weight { text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--ii-text-primary); }
	.td-score { text-align: right; font-variant-numeric: tabular-nums; color: var(--ii-text-secondary); }

	.weight-bar-track {
		height: 6px;
		background: var(--ii-surface-alt);
		border-radius: 3px;
		overflow: hidden;
	}

	.weight-bar-fill {
		height: 100%;
		background: var(--ii-brand-primary);
		border-radius: 3px;
		transition: width 200ms ease;
	}

	/* ── Fact Sheets ─────────────────────────────────────────────────────── */
	.fs-error {
		margin: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px) 0;
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 12px);
		border-radius: var(--ii-radius-sm, 8px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.fs-error-dismiss {
		margin-left: var(--ii-space-inline-sm, 8px);
		text-decoration: underline;
		cursor: pointer;
		background: none;
		border: none;
		color: inherit;
		font-size: inherit;
	}

	.fs-content {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
	}

	.fs-generate {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 8px);
		margin-bottom: var(--ii-space-stack-sm, 12px);
	}

	.fs-lang-select {
		height: var(--ii-space-control-height-sm, 32px);
		padding: 0 var(--ii-space-inline-sm, 10px);
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 6px);
		background: var(--ii-surface);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-family: var(--ii-font-sans);
	}

	.fs-list {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-2xs, 4px);
	}

	.fs-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-sm, 10px);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-sm, 8px);
	}

	.fs-info {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 8px);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.fs-format {
		font-weight: 500;
		color: var(--ii-text-primary);
	}

	.fs-lang-badge {
		display: inline-block;
		padding: 1px 6px;
		border-radius: var(--ii-radius-pill, 999px);
		background: color-mix(in srgb, var(--ii-brand-primary) 10%, transparent);
		color: var(--ii-brand-primary);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
	}

	.fs-period {
		color: var(--ii-text-secondary);
	}

	.fs-date {
		color: var(--ii-text-muted);
	}
</style>
