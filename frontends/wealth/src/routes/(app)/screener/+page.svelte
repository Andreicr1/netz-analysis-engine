<!--
  Screener — 3-layer deterministic screening (eliminatory → mandate fit → quant).
  CSS Grid: filter panel (left) + data surface (right).
  Filters: cascading top-down (status → type → block → search).
  Table: keyed iteration on instrument_id.
-->
<script lang="ts">
	import {
		PageHeader, Card, StatusBadge, Button, ContextPanel,
		formatDateTime, formatNumber, formatPercent,
	} from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";
	import type {
		ScreeningResult, ScreeningRun, CriterionResult,
		ScreenerFilterConfig, OverallStatus,
	} from "$lib/types/screening";
	import { EMPTY_FILTERS } from "$lib/types/screening";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	// ── Raw data from SSR ─────────────────────────────────────────────────────

	let results = $derived((data.results ?? []) as ScreeningResult[]);
	let lastRun = $derived(data.lastRun as ScreeningRun | null);

	// ── Filter state (Svelte 5 runes) ─────────────────────────────────────────

	let filters = $state<ScreenerFilterConfig>({ ...EMPTY_FILTERS });

	// Distinct values for filter selectors (derived from loaded results)
	let distinctTypes = $derived(
		[...new Set(results.map((r) => r.instrument_type).filter(Boolean))] as string[]
	);
	let distinctBlocks = $derived(
		[...new Set(results.map((r) => r.block_id).filter(Boolean))] as string[]
	);

	// ── Derived filtered results ──────────────────────────────────────────────

	let filteredResults = $derived.by(() => {
		let rows = results;

		if (filters.status) {
			rows = rows.filter((r) => r.overall_status === filters.status);
		}
		if (filters.instrument_type) {
			rows = rows.filter((r) => r.instrument_type === filters.instrument_type);
		}
		if (filters.block_id) {
			rows = rows.filter((r) => r.block_id === filters.block_id);
		}
		if (filters.search) {
			const q = filters.search.toLowerCase();
			rows = rows.filter((r) =>
				(r.name?.toLowerCase().includes(q)) ||
				(r.isin?.toLowerCase().includes(q)) ||
				(r.ticker?.toLowerCase().includes(q)) ||
				(r.manager?.toLowerCase().includes(q))
			);
		}
		return rows;
	});

	// ── Funnel counts ─────────────────────────────────────────────────────────

	let universeCount = $derived(results.length);
	let l1PassCount = $derived(results.filter((r) => r.failed_at_layer !== 1).length);
	let l2EligibleCount = $derived(
		results.filter((r) => r.failed_at_layer !== 1 && r.failed_at_layer !== 2).length
	);
	let passCount = $derived(results.filter((r) => r.overall_status === "PASS").length);
	let watchlistCount = $derived(results.filter((r) => r.overall_status === "WATCHLIST").length);
	let failCount = $derived(results.filter((r) => r.overall_status === "FAIL").length);

	// ── Detail panel ──────────────────────────────────────────────────────────

	let panelOpen = $state(false);
	let selectedResult = $state<ScreeningResult | null>(null);

	function openDetail(result: ScreeningResult) {
		selectedResult = result;
		panelOpen = true;
	}

	function closeDetail() {
		panelOpen = false;
		selectedResult = null;
	}

	// ── Batch execution ───────────────────────────────────────────────────────

	let isRunning = $state(false);
	let runError = $state<string | null>(null);

	async function executeBatch() {
		isRunning = true;
		runError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post("/screener/run", {});
			await invalidateAll();
		} catch (e) {
			runError = e instanceof Error ? e.message : "Failed to execute screening";
		} finally {
			isRunning = false;
		}
	}

	// ── Helpers ───────────────────────────────────────────────────────────────

	function instrumentLabel(r: ScreeningResult): string {
		return r.name ?? r.instrument_id.slice(0, 8).toUpperCase();
	}

	function instrumentSubtitle(r: ScreeningResult): string {
		const parts: string[] = [];
		if (r.isin) parts.push(r.isin);
		else if (r.ticker) parts.push(r.ticker);
		if (r.manager) parts.push(r.manager);
		return parts.join(" · ");
	}

	function typeLabel(type: string | undefined): string {
		switch (type) {
			case "fund":   return "Fund";
			case "bond":   return "Fixed Income";
			case "equity": return "Equity";
			default:       return type ?? "—";
		}
	}

	function layerDotStatus(r: ScreeningResult, layer: number): "pass" | "fail" | "none" {
		if (r.failed_at_layer === layer) return "fail";
		if (r.failed_at_layer !== null && r.failed_at_layer < layer) return "none";
		return "pass";
	}

	function scoreColor(score: number | null): string {
		if (score === null) return "var(--netz-text-muted)";
		if (score >= 0.7) return "var(--netz-success)";
		if (score >= 0.4) return "var(--netz-warning)";
		return "var(--netz-danger)";
	}

	function ddLabel(type: string): string {
		switch (type) {
			case "dd_report":  return "DD Report";
			case "bond_brief": return "Bond Brief";
			case "none":       return "—";
			default:           return type;
		}
	}

	function layerCriteria(r: ScreeningResult, layer: number): CriterionResult[] {
		return r.layer_results.filter((c) => c.layer === layer);
	}

	function clearFilters() {
		filters = { ...EMPTY_FILTERS };
	}

	function setStatusFilter(status: OverallStatus | null) {
		filters.status = status;
	}

	const hasActiveFilters = $derived(
		filters.status !== null ||
		filters.instrument_type !== null ||
		filters.block_id !== null ||
		filters.search !== ""
	);
</script>

<PageHeader title="Fund Screener">
	{#snippet actions()}
		<Button
			size="sm"
			onclick={executeBatch}
			disabled={isRunning}
		>
			{isRunning ? "Running…" : "Run Screening"}
		</Button>
	{/snippet}
</PageHeader>

<div class="screener-grid">
	<!-- ═══════════════════════════════════════════════════════════════════════ -->
	<!-- LEFT: FILTER PANEL                                                     -->
	<!-- ═══════════════════════════════════════════════════════════════════════ -->
	<aside class="filter-panel">
		<!-- Funnel overview -->
		<div class="filter-section">
			<h3 class="filter-section-title">Screening Funnel</h3>
			<div class="funnel">
				<div class="funnel-row">
					<span class="funnel-label">Universe</span>
					<span class="funnel-value">{universeCount}</span>
				</div>
				<div class="funnel-bar" style:--fill="100%"></div>

				<div class="funnel-row">
					<span class="funnel-label">L1 Passed</span>
					<span class="funnel-value">{l1PassCount}</span>
				</div>
				<div class="funnel-bar" style:--fill="{universeCount ? (l1PassCount / universeCount) * 100 : 0}%"></div>

				<div class="funnel-row">
					<span class="funnel-label">L2 Eligible</span>
					<span class="funnel-value">{l2EligibleCount}</span>
				</div>
				<div class="funnel-bar" style:--fill="{universeCount ? (l2EligibleCount / universeCount) * 100 : 0}%"></div>

				<div class="funnel-row funnel-row--outcomes">
					<button
						class="funnel-outcome"
						class:funnel-outcome--active={filters.status === "PASS"}
						onclick={() => setStatusFilter(filters.status === "PASS" ? null : "PASS")}
					>
						<span class="funnel-dot funnel-dot--pass"></span>
						<span>Pass</span>
						<span class="funnel-count">{passCount}</span>
					</button>
					<button
						class="funnel-outcome"
						class:funnel-outcome--active={filters.status === "WATCHLIST"}
						onclick={() => setStatusFilter(filters.status === "WATCHLIST" ? null : "WATCHLIST")}
					>
						<span class="funnel-dot funnel-dot--watchlist"></span>
						<span>Watch</span>
						<span class="funnel-count">{watchlistCount}</span>
					</button>
					<button
						class="funnel-outcome"
						class:funnel-outcome--active={filters.status === "FAIL"}
						onclick={() => setStatusFilter(filters.status === "FAIL" ? null : "FAIL")}
					>
						<span class="funnel-dot funnel-dot--fail"></span>
						<span>Fail</span>
						<span class="funnel-count">{failCount}</span>
					</button>
				</div>
			</div>
		</div>

		<!-- Cascading filters -->
		<div class="filter-section">
			<h3 class="filter-section-title">Filters</h3>

			<!-- Search -->
			<div class="filter-field">
				<label class="filter-label" for="screener-search">Search</label>
				<input
					id="screener-search"
					type="text"
					class="filter-input"
					placeholder="Name, ISIN, ticker, manager…"
					bind:value={filters.search}
				/>
			</div>

			<!-- Instrument type (Region/Strategy proxy — fund=UCITS/ESMA, equity=OFR) -->
			<div class="filter-field">
				<label class="filter-label" for="screener-type">Instrument Type</label>
				<select
					id="screener-type"
					class="filter-select"
					bind:value={filters.instrument_type}
				>
					<option value={null}>All types</option>
					{#each distinctTypes as t (t)}
						<option value={t}>{typeLabel(t)}</option>
					{/each}
				</select>
			</div>

			<!-- Block / Strategy -->
			<div class="filter-field">
				<label class="filter-label" for="screener-block">Allocation Block</label>
				<select
					id="screener-block"
					class="filter-select"
					bind:value={filters.block_id}
				>
					<option value={null}>All blocks</option>
					{#each distinctBlocks as b (b)}
						<option value={b}>{b}</option>
					{/each}
				</select>
			</div>

			{#if hasActiveFilters}
				<button class="filter-clear" onclick={clearFilters}>
					Clear all filters
				</button>
			{/if}
		</div>

		<!-- Last run metadata -->
		{#if lastRun}
			<div class="filter-section filter-section--meta">
				<h3 class="filter-section-title">Last Run</h3>
				<div class="meta-row">
					<span class="meta-label">Status</span>
					<StatusBadge status={lastRun.status} />
				</div>
				<div class="meta-row">
					<span class="meta-label">Instruments</span>
					<span class="meta-value">{formatNumber(lastRun.instrument_count)}</span>
				</div>
				<div class="meta-row">
					<span class="meta-label">Started</span>
					<span class="meta-value">{formatDateTime(lastRun.started_at)}</span>
				</div>
				{#if lastRun.completed_at}
					<div class="meta-row">
						<span class="meta-label">Completed</span>
						<span class="meta-value">{formatDateTime(lastRun.completed_at)}</span>
					</div>
				{/if}
			</div>
		{/if}

		{#if runError}
			<div class="filter-section filter-error">
				{runError}
			</div>
		{/if}
	</aside>

	<!-- ═══════════════════════════════════════════════════════════════════════ -->
	<!-- RIGHT: DATA SURFACE                                                    -->
	<!-- ═══════════════════════════════════════════════════════════════════════ -->
	<section class="data-surface">
		<div class="data-header">
			<span class="data-count">
				{filteredResults.length} result{filteredResults.length !== 1 ? "s" : ""}
				{#if hasActiveFilters}
					<span class="data-count-filtered">of {universeCount}</span>
				{/if}
			</span>
		</div>

		{#if filteredResults.length === 0}
			<div class="data-empty">
				<p class="data-empty-text">
					{#if universeCount === 0}
						No screening results. Run a batch to populate.
					{:else}
						No results match current filters.
					{/if}
				</p>
			</div>
		{:else}
			<div class="table-wrap">
				<table class="results-table">
					<thead>
						<tr>
							<th class="th-name">Instrument</th>
							<th class="th-type">Type</th>
							<th class="th-layers">L1</th>
							<th class="th-layers">L2</th>
							<th class="th-layers">L3</th>
							<th class="th-score">Score</th>
							<th class="th-status">Status</th>
							<th class="th-dd">Next Step</th>
						</tr>
					</thead>
					<tbody>
						{#each filteredResults as result (result.instrument_id)}
							<tr
								class="results-row"
								onclick={() => openDetail(result)}
							>
								<td class="td-name">
									<span class="instrument-name">{instrumentLabel(result)}</span>
									<span class="instrument-sub">{instrumentSubtitle(result)}</span>
								</td>
								<td class="td-type">
									<span class="type-badge type-badge--{result.instrument_type ?? 'other'}">
										{typeLabel(result.instrument_type)}
									</span>
								</td>
								<td class="td-layer">
									<span class="layer-dot layer-dot--{layerDotStatus(result, 1)}"></span>
								</td>
								<td class="td-layer">
									<span class="layer-dot layer-dot--{layerDotStatus(result, 2)}"></span>
								</td>
								<td class="td-layer">
									<span class="layer-dot layer-dot--{layerDotStatus(result, 3)}"></span>
								</td>
								<td class="td-score">
									{#if result.score !== null}
										<span style:color={scoreColor(result.score)}>
											{formatPercent(result.score)}
										</span>
									{:else}
										<span class="score-na">—</span>
									{/if}
								</td>
								<td class="td-status">
									<StatusBadge
										status={result.overall_status}
																			/>
								</td>
								<td class="td-dd">{ddLabel(result.required_analysis_type)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>
</div>

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- DETAIL PANEL                                                           -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
<ContextPanel open={panelOpen} onClose={closeDetail} title={selectedResult ? instrumentLabel(selectedResult) : ""}>
	{#if selectedResult}
		<div class="detail-content">
			<!-- Header -->
			<div class="detail-header">
				<StatusBadge
					status={selectedResult.overall_status}
				/>
				{#if selectedResult.score !== null}
					<span class="detail-score" style:color={scoreColor(selectedResult.score)}>
						Score: {formatPercent(selectedResult.score)}
					</span>
				{/if}
			</div>

			<div class="detail-meta">
				{#if selectedResult.isin}<span>ISIN: {selectedResult.isin}</span>{/if}
				{#if selectedResult.ticker}<span>Ticker: {selectedResult.ticker}</span>{/if}
				{#if selectedResult.instrument_type}<span>Type: {typeLabel(selectedResult.instrument_type)}</span>{/if}
				{#if selectedResult.manager}<span>Manager: {selectedResult.manager}</span>{/if}
				<span>Screened: {formatDateTime(selectedResult.screened_at)}</span>
				<span>Next: {ddLabel(selectedResult.required_analysis_type)}</span>
			</div>

			<!-- Layer breakdown -->
			{#each [1, 2, 3] as layer (layer)}
				{@const criteria = layerCriteria(selectedResult, layer)}
				{#if criteria.length > 0}
					<div class="detail-layer">
						<h4 class="detail-layer-title">
							<span class="layer-dot layer-dot--{layerDotStatus(selectedResult, layer)}"></span>
							Layer {layer}
							{#if layer === 1}— Eliminatory{:else if layer === 2}— Mandate Fit{:else}— Quant{/if}
						</h4>
						<table class="criteria-table">
							<thead>
								<tr>
									<th>Criterion</th>
									<th>Expected</th>
									<th>Actual</th>
									<th></th>
								</tr>
							</thead>
							<tbody>
								{#each criteria as c (c.criterion)}
									<tr class:criteria-fail={!c.passed}>
										<td class="criteria-name">{c.criterion}</td>
										<td class="criteria-val">{c.expected}</td>
										<td class="criteria-val">{c.actual}</td>
										<td class="criteria-icon">{c.passed ? "✓" : "✗"}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			{/each}
		</div>
	{/if}
</ContextPanel>

<style>
	/* ── Grid layout ─────────────────────────────────────────────────────── */
	.screener-grid {
		display: grid;
		grid-template-columns: 280px 1fr;
		gap: 0;
		height: calc(100vh - 64px);
		overflow: hidden;
	}

	/* ── Filter panel (left) ─────────────────────────────────────────────── */
	.filter-panel {
		overflow-y: auto;
		border-right: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-elevated);
		padding: var(--netz-space-stack-sm, 12px) 0;
	}

	.filter-section {
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.filter-section--meta {
		border-bottom: none;
	}

	.filter-section-title {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--netz-text-muted);
		margin-bottom: var(--netz-space-stack-xs, 8px);
	}

	/* Funnel */
	.funnel {
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-2xs, 4px);
	}

	.funnel-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-secondary);
	}

	.funnel-value {
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--netz-text-primary);
	}

	.funnel-bar {
		height: 4px;
		border-radius: 2px;
		background: var(--netz-border-subtle);
		margin-bottom: var(--netz-space-stack-2xs, 4px);
		position: relative;
		overflow: hidden;
	}

	.funnel-bar::after {
		content: "";
		position: absolute;
		left: 0;
		top: 0;
		bottom: 0;
		width: var(--fill, 100%);
		background: var(--netz-brand-primary);
		border-radius: 2px;
		transition: width 300ms ease;
	}

	.funnel-row--outcomes {
		display: flex;
		gap: var(--netz-space-inline-xs, 8px);
		margin-top: var(--netz-space-stack-xs, 8px);
	}

	.funnel-outcome {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
		padding: var(--netz-space-stack-2xs, 4px);
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-sm, 8px);
		background: transparent;
		color: var(--netz-text-secondary);
		font-size: var(--netz-text-label, 0.75rem);
		cursor: pointer;
		transition: border-color 120ms ease, background-color 120ms ease;
	}

	.funnel-outcome:hover {
		border-color: var(--netz-border);
		background: var(--netz-surface-alt);
	}

	.funnel-outcome--active {
		border-color: var(--netz-brand-primary);
		background: color-mix(in srgb, var(--netz-brand-primary) 8%, transparent);
	}

	.funnel-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
	}

	.funnel-dot--pass { background: var(--netz-success); }
	.funnel-dot--watchlist { background: var(--netz-warning); }
	.funnel-dot--fail { background: var(--netz-danger); }

	.funnel-count {
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--netz-text-primary);
	}

	/* Filter fields */
	.filter-field {
		margin-bottom: var(--netz-space-stack-sm, 12px);
	}

	.filter-label {
		display: block;
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 500;
		color: var(--netz-text-muted);
		margin-bottom: var(--netz-space-stack-2xs, 4px);
	}

	.filter-input,
	.filter-select {
		width: 100%;
		height: var(--netz-space-control-height-sm, 32px);
		padding: 0 var(--netz-space-inline-sm, 10px);
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 8px);
		background: var(--netz-surface);
		color: var(--netz-text-primary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-sans);
		transition: border-color 120ms ease;
	}

	.filter-input:focus,
	.filter-select:focus {
		outline: none;
		border-color: var(--netz-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--netz-brand-secondary) 20%, transparent);
	}

	.filter-input::placeholder {
		color: var(--netz-text-muted);
	}

	.filter-clear {
		width: 100%;
		padding: var(--netz-space-stack-2xs, 6px);
		border: none;
		border-radius: var(--netz-radius-sm, 8px);
		background: transparent;
		color: var(--netz-brand-secondary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-sans);
		cursor: pointer;
		transition: background-color 120ms ease;
	}

	.filter-clear:hover {
		background: var(--netz-surface-alt);
	}

	/* Meta */
	.meta-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: var(--netz-text-small, 0.8125rem);
		padding: 2px 0;
	}

	.meta-label {
		color: var(--netz-text-muted);
	}

	.meta-value {
		color: var(--netz-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.filter-error {
		color: var(--netz-danger);
		font-size: var(--netz-text-small, 0.8125rem);
		background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
		border-radius: var(--netz-radius-sm, 8px);
		padding: var(--netz-space-inline-sm, 10px);
		margin: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		border-bottom: none;
	}

	/* ── Data surface (right) ────────────────────────────────────────────── */
	.data-surface {
		display: flex;
		flex-direction: column;
		overflow: hidden;
		background: var(--netz-surface);
	}

	.data-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
		flex-shrink: 0;
	}

	.data-count {
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--netz-text-secondary);
		font-variant-numeric: tabular-nums;
	}

	.data-count-filtered {
		color: var(--netz-text-muted);
	}

	.data-empty {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--netz-space-stack-xl, 48px);
	}

	.data-empty-text {
		font-size: var(--netz-text-body, 0.9375rem);
		color: var(--netz-text-muted);
	}

	/* ── Results table ───────────────────────────────────────────────────── */
	.table-wrap {
		flex: 1;
		overflow-y: auto;
		overflow-x: auto;
	}

	.results-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.results-table thead {
		position: sticky;
		top: 0;
		z-index: 1;
	}

	.results-table th {
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-sm, 10px);
		text-align: left;
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		letter-spacing: 0.02em;
		text-transform: uppercase;
		color: var(--netz-text-muted);
		background: var(--netz-surface-alt);
		border-bottom: 1px solid var(--netz-border-subtle);
		white-space: nowrap;
	}

	.results-table td {
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-sm, 10px);
		border-bottom: 1px solid var(--netz-border-subtle);
		vertical-align: middle;
	}

	.results-row {
		cursor: pointer;
		transition: background-color 80ms ease;
	}

	.results-row:hover {
		background: var(--netz-surface-highlight, color-mix(in srgb, var(--netz-brand-primary) 4%, transparent));
	}

	.th-name { min-width: 220px; }
	.th-type { min-width: 90px; }
	.th-layers { width: 36px; text-align: center; }
	.th-score { width: 70px; text-align: right; }
	.th-status { width: 90px; }
	.th-dd { width: 100px; }

	/* Name cell */
	.td-name {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.instrument-name {
		font-weight: 500;
		color: var(--netz-text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 300px;
	}

	.instrument-sub {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 300px;
	}

	/* Type badge */
	.type-badge {
		display: inline-block;
		padding: 1px 8px;
		border-radius: var(--netz-radius-pill, 999px);
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 500;
		white-space: nowrap;
	}

	.type-badge--fund {
		background: color-mix(in srgb, var(--netz-brand-primary) 12%, transparent);
		color: var(--netz-brand-primary);
	}
	.type-badge--bond {
		background: color-mix(in srgb, var(--netz-brand-highlight) 12%, transparent);
		color: var(--netz-brand-highlight);
	}
	.type-badge--equity {
		background: color-mix(in srgb, var(--netz-success) 12%, transparent);
		color: var(--netz-success);
	}
	.type-badge--other {
		background: var(--netz-surface-alt);
		color: var(--netz-text-muted);
	}

	/* Layer dots */
	.td-layer {
		text-align: center;
	}

	.layer-dot {
		display: inline-block;
		width: 10px;
		height: 10px;
		border-radius: 50%;
	}

	.layer-dot--pass { background: var(--netz-success); }
	.layer-dot--fail { background: var(--netz-danger); }
	.layer-dot--none { background: var(--netz-border-subtle); }

	/* Score */
	.td-score {
		text-align: right;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.score-na {
		color: var(--netz-text-muted);
	}

	/* DD step */
	.td-dd {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-secondary);
		white-space: nowrap;
	}

	/* ── Detail panel ────────────────────────────────────────────────────── */
	.detail-content {
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px);
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-md, 16px);
	}

	.detail-header {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-sm, 10px);
	}

	.detail-score {
		font-weight: 700;
		font-size: var(--netz-text-body-lg, 1rem);
		font-variant-numeric: tabular-nums;
	}

	.detail-meta {
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-secondary);
	}

	.detail-layer {
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-sm, 8px);
		overflow: hidden;
	}

	.detail-layer-title {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-xs, 6px);
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-sm, 10px);
		background: var(--netz-surface-alt);
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--netz-text-primary);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.criteria-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--netz-text-label, 0.75rem);
	}

	.criteria-table th {
		padding: 4px 8px;
		text-align: left;
		font-weight: 600;
		color: var(--netz-text-muted);
		background: var(--netz-surface);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.criteria-table td {
		padding: 4px 8px;
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.criteria-name {
		color: var(--netz-text-primary);
		font-weight: 500;
	}

	.criteria-val {
		font-variant-numeric: tabular-nums;
		color: var(--netz-text-secondary);
	}

	.criteria-icon {
		text-align: center;
		width: 24px;
	}

	.criteria-fail .criteria-name {
		color: var(--netz-danger);
	}

	.criteria-fail .criteria-icon {
		color: var(--netz-danger);
	}

	/* ── Responsive ──────────────────────────────────────────────────────── */
	@media (max-width: 768px) {
		.screener-grid {
			grid-template-columns: 1fr;
			grid-template-rows: auto 1fr;
			height: auto;
		}

		.filter-panel {
			border-right: none;
			border-bottom: 1px solid var(--netz-border-subtle);
			max-height: 300px;
		}

		.data-surface {
			min-height: 400px;
		}
	}
</style>
