<!--
  Instrument Screener — Figma frame "Instrument Screener" (node 1:3)
  Funnel sidebar + status tabs + results table + ContextPanel detail panel.
-->
<script lang="ts">
	import { PageHeader, Card, EmptyState, StatusBadge, ContextPanel, Button, formatDateTime, formatNumber } from "@netz/ui";
	import { ActionButton } from "@netz/ui";
	import { createVirtualizer } from "@tanstack/svelte-virtual";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import { get as getStore } from "svelte/store";
	import { resolveWealthStatus } from "$lib/utils/status-maps";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	// ── Types ──────────────────────────────────────────────────────────────────

	type CriterionResult = {
		criterion: string;
		expected: string;
		actual: string;
		passed: boolean;
		layer: number;
	};

	type ScreeningResult = {
		id: string;
		instrument_id: string;
		run_id: string;
		overall_status: string;           // PASS | FAIL | WATCHLIST
		score: number | null;
		failed_at_layer: number | null;   // 1 | 2 | 3 | null
		layer_results: CriterionResult[];
		required_analysis_type: string;   // dd_report | bond_brief | none
		screened_at: string;
		is_current: boolean;
		// Instrument fields joined by server (may be absent)
		name?: string;
		isin?: string;
		ticker?: string;
		instrument_type?: string;         // fund | bond | equity
		block_id?: string | null;
		manager?: string;
	};

	type ScreeningRun = {
		run_id: string;
		instrument_count: number;
		started_at: string;
		completed_at: string | null;
		status: string;
	};

	// ── Raw API data ───────────────────────────────────────────────────────────

	let results = $derived((data.results ?? []) as ScreeningResult[]);
	let latestRun = $derived(data.latestRun as ScreeningRun | null);

	// ── Status tab state ───────────────────────────────────────────────────────

	type Tab = "todos" | "PASS" | "WATCHLIST" | "FAIL";
	let activeTab = $state<Tab>("todos");

	// ── Funnel counts (computed client-side from failed_at_layer) ──────────────

	let universeCount = $derived(results.length);

	// L1 passed = did not fail at layer 1
	let l1PassCount = $derived(
		results.filter((r) => r.failed_at_layer !== 1).length
	);

	// L2 eligible = passed L1 AND did not fail at layer 2
	let l2EligibleCount = $derived(
		results.filter((r) => r.failed_at_layer !== 1 && r.failed_at_layer !== 2).length
	);

	// L3 outcomes
	let l3PassCount = $derived(results.filter((r) => r.overall_status === "PASS").length);
	let l3WatchlistCount = $derived(results.filter((r) => r.overall_status === "WATCHLIST").length);
	let l3FailCount = $derived(results.filter((r) => r.overall_status === "FAIL").length);

	// ── Tab counts ─────────────────────────────────────────────────────────────

	let tabCounts = $derived({
		todos: results.length,
		PASS: l3PassCount,
		WATCHLIST: l3WatchlistCount,
		FAIL: l3FailCount,
	});

	// ── Filtered table rows ────────────────────────────────────────────────────

	let filteredResults = $derived(
		activeTab === "todos"
			? results
			: results.filter((r) => r.overall_status === activeTab)
	);

	// ── Row virtualization ─────────────────────────────────────────────────────

	let scrollContainer = $state<HTMLDivElement>(null!);
	const virtualizerStore = $derived(
		createVirtualizer({
			get count() {
				return filteredResults.length;
			},
			getScrollElement: () => scrollContainer,
			estimateSize: () => 44,
			overscan: 10,
		})
	);
	// Unwrap the Svelte readable store to get the virtualizer instance
	let virtualizer = $derived(getStore(virtualizerStore));

	// ── Detail panel state ─────────────────────────────────────────────────────

	let panelOpen = $state(false);
	let selectedResult = $state<ScreeningResult | null>(null);

	function openPanel(result: ScreeningResult) {
		selectedResult = result;
		panelOpen = true;
	}

	function closePanel() {
		panelOpen = false;
		selectedResult = null;
	}

	// ── Batch execution state ──────────────────────────────────────────────────

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

	// ── Helpers ────────────────────────────────────────────────────────────────

	function formatDate(iso: string | null | undefined): string {
		return formatDateTime(iso);
	}

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

	function typeBadgeClass(type: string | undefined): string {
		switch (type) {
			case "fund":   return "tipo-fund";
			case "bond":   return "tipo-bond";
			case "equity": return "tipo-equity";
			default:       return "tipo-other";
		}
	}

	function typeLabel(type: string | undefined): string {
		switch (type) {
			case "fund":   return "Fund";
			case "bond":   return "Fixed Income";
			case "equity": return "Equity";
			default:       return type ?? "—";
		}
	}

	// Layer dot: green=passed, red=failed-at-that-layer, gray=not-reached
	function layerDotStatus(r: ScreeningResult, layer: number): "pass" | "fail" | "none" {
		if (r.failed_at_layer === layer) return "fail";
		if (r.failed_at_layer !== null && r.failed_at_layer < layer) return "none";
		// Reached this layer and didn't fail here
		return "pass";
	}

	// BL-16: Check if an instrument was eliminated at L1 or L2
	function isEliminated(r: ScreeningResult): boolean {
		return r.failed_at_layer === 1 || r.failed_at_layer === 2;
	}

	// BL-16: Get the elimination reason (first failing criterion at the failed layer)
	function eliminationReason(r: ScreeningResult): string | null {
		if (r.failed_at_layer === null) return null;
		const failing = r.layer_results.find(
			(c) => c.layer === r.failed_at_layer && !c.passed
		);
		return failing ? failing.criterion : null;
	}

	function scoreColor(score: number | null): string {
		if (score === null) return "var(--netz-text-muted)";
		if (score >= 0.7) return "var(--netz-success)";
		if (score >= 0.4) return "var(--netz-warning)";
		return "var(--netz-danger)";
	}

	function statusVariant(status: string): string {
		switch (status) {
			case "PASS":      return "success";
			case "WATCHLIST": return "warning";
			case "FAIL":      return "danger";
			default:          return "neutral";
		}
	}

	function ddLabel(type: string): string {
		switch (type) {
			case "dd_report":  return "DD Report";
			case "bond_brief": return "Bond Brief";
			case "none":       return "—";
			default:           return type;
		}
	}

	// Layer results grouped by layer number
	function layerCriteria(r: ScreeningResult, layer: number): CriterionResult[] {
		return r.layer_results.filter((c) => c.layer === layer);
	}

	// L3 score metrics (layer 3 criteria used as quant metrics)
	function l3Metrics(r: ScreeningResult): CriterionResult[] {
		return r.layer_results.filter((c) => c.layer === 3);
	}

	// ── Run detail drill-down ──────────────────────────────────────────────────
	let runDetailData = $state<Record<string, unknown> | null>(null);
	let runDetailLoading = $state(false);
	let showRunDetail = $state(false);

	async function loadRunDetail(runId: string) {
		runDetailLoading = true;
		showRunDetail = true;
		try {
			const api = createClientApiClient(getToken);
			runDetailData = await api.get(`/screener/runs/${runId}`);
		} catch {
			runDetailData = null;
		} finally {
			runDetailLoading = false;
		}
	}

	// ── Instrument screening history ──────────────────────────────────────────
	let historyData = $state<Array<Record<string, unknown>>>([]);
	let historyLoading = $state(false);
	let showHistory = $state(false);
	let historyInstrumentName = $state("");

	async function loadInstrumentHistory(instrumentId: string, name: string) {
		historyInstrumentName = name;
		historyLoading = true;
		showHistory = true;
		try {
			const api = createClientApiClient(getToken);
			const res = await api.get<{ results?: Array<Record<string, unknown>> }>(`/screener/results/${instrumentId}`);
			historyData = res.results ?? (Array.isArray(res) ? res : []);
		} catch {
			historyData = [];
		} finally {
			historyLoading = false;
		}
	}
</script>

<div class="screener-layout">
	<!-- ── Funnel Sidebar ────────────────────────────────────────────────────── -->
	<aside class="funnel-sidebar">
		<h3 class="funnel-title">Screening Pipeline</h3>

		<div class="funnel-stages">
			<!-- Universe -->
			<div class="funnel-stage funnel-stage--universe">
				<span class="funnel-stage__label">Universe</span>
				<span class="funnel-stage__count">{universeCount}</span>
			</div>

			<div class="funnel-connector"></div>

			<!-- L1 -->
			<div class="funnel-stage funnel-stage--l1">
				<span class="funnel-stage__label">L1 Knockout</span>
				<span class="funnel-stage__count">{l1PassCount}</span>
				<span class="funnel-stage__sublabel">passed</span>
			</div>

			<div class="funnel-connector"></div>

			<!-- L2 -->
			<div class="funnel-stage funnel-stage--l2">
				<span class="funnel-stage__label">L2 Eligible</span>
				<span class="funnel-stage__count">{l2EligibleCount}</span>
				<span class="funnel-stage__sublabel">eligible</span>
			</div>

			<div class="funnel-connector"></div>

			<!-- L3 outcomes -->
			<div class="funnel-stage funnel-stage--l3">
				<span class="funnel-stage__label">L3 Score Quant</span>
				<div class="funnel-outcomes">
					<div class="funnel-outcome funnel-outcome--pass">
						<span class="funnel-outcome__dot"></span>
						<span class="funnel-outcome__label">PASS</span>
						<span class="funnel-outcome__count">{l3PassCount}</span>
					</div>
					<div class="funnel-outcome funnel-outcome--watch">
						<span class="funnel-outcome__dot"></span>
						<span class="funnel-outcome__label">WATCH</span>
						<span class="funnel-outcome__count">{l3WatchlistCount}</span>
					</div>
					<div class="funnel-outcome funnel-outcome--fail">
						<span class="funnel-outcome__dot"></span>
						<span class="funnel-outcome__label">FAIL</span>
						<span class="funnel-outcome__count">{l3FailCount}</span>
					</div>
				</div>
			</div>
		</div>
	</aside>

	<!-- ── Main Content ──────────────────────────────────────────────────────── -->
	<main class="screener-main">
		<!-- Header -->
		<PageHeader title="Instrument Screener">
			{#snippet actions()}
				<div class="header-meta">
					{#if latestRun}
						<span class="header-meta__run">
							Last batch: {formatDate(latestRun.completed_at ?? latestRun.started_at)}
						</span>
						<span class="header-meta__count">
							{latestRun.instrument_count} screened
						</span>
					{/if}
					{#if runError}
						<span class="header-meta__error">{runError}</span>
					{/if}
					<Button
						size="sm"
						onclick={executeBatch}
						disabled={isRunning}
					>
						{isRunning ? "Running..." : "Run Batch"}
					</Button>
				</div>
			{/snippet}
		</PageHeader>

		<!-- Status Tabs -->
		<div class="status-tabs" role="tablist">
			{#each (["todos", "PASS", "WATCHLIST", "FAIL"] as Tab[]) as tab (tab)}
				<button
					class="status-tab"
					class:status-tab--active={activeTab === tab}
					role="tab"
					aria-selected={activeTab === tab}
					onclick={() => (activeTab = tab)}
				>
					{tab === "todos" ? "All" : tab}
					<span class="status-tab__badge">{tabCounts[tab]}</span>
				</button>
			{/each}
		</div>

		<!-- Results Table (virtualized) -->
		{#if filteredResults.length > 0}
			<Card>
				<div bind:this={scrollContainer} class="table-scroll-container">
					<table class="results-table">
						<thead>
							<tr>
								<th class="col-instrumento">Instrument</th>
								<th class="col-tipo">Type</th>
								<th class="col-bloco">Eligible Block</th>
								<th class="col-layers">L1</th>
								<th class="col-layers">L2</th>
								<th class="col-layers">L3</th>
								<th class="col-score">Score L3</th>
								<th class="col-status">Status</th>
								<th class="col-dd">DD Requerido</th>
							</tr>
						</thead>
						<tbody style="height: {virtualizer.getTotalSize()}px; position: relative;">
							{#each virtualizer.getVirtualItems() as virtualRow (virtualRow.index)}
								{@const result = filteredResults[virtualRow.index]!}
								<tr
									class="result-row virtual-row"
									class:result-row--eliminated={isEliminated(result)}
									style="position: absolute; top: 0; left: 0; width: 100%; height: {virtualRow.size}px; transform: translateY({virtualRow.start}px);"
									onclick={() => openPanel(result)}
									role="button"
									tabindex="0"
									onkeydown={(e) => e.key === "Enter" && openPanel(result)}
								>
									<!-- Instrumento -->
									<td class="col-instrumento">
										<div class="instrument-cell">
											<span class="instrument-name" class:instrument-name--eliminated={isEliminated(result)}>
												{instrumentLabel(result)}
											</span>
											{#if isEliminated(result) && eliminationReason(result)}
												<span class="elimination-reason">
													L{result.failed_at_layer} fail: {eliminationReason(result)}
												</span>
											{:else if instrumentSubtitle(result)}
												<span class="instrument-sub">{instrumentSubtitle(result)}</span>
											{/if}
										</div>
									</td>

									<!-- Tipo -->
									<td class="col-tipo">
										<span class="tipo-badge {typeBadgeClass(result.instrument_type)}">
											{typeLabel(result.instrument_type)}
										</span>
									</td>

									<!-- Eligible Block -->
									<td class="col-bloco">
										<span class="bloco-label">{result.block_id ?? "—"}</span>
									</td>

									<!-- L1 dot -->
									<td class="col-layers">
										<span class="layer-dot layer-dot--{layerDotStatus(result, 1)}" title="L1: {layerDotStatus(result, 1)}"></span>
										{#if layerDotStatus(result, 1) === "pass"}
											<span class="layer-pass-label">OK</span>
										{/if}
									</td>

									<!-- L2 dot -->
									<td class="col-layers">
										<span class="layer-dot layer-dot--{layerDotStatus(result, 2)}" title="L2: {layerDotStatus(result, 2)}"></span>
									</td>

									<!-- L3 dot -->
									<td class="col-layers">
										<span class="layer-dot layer-dot--{layerDotStatus(result, 3)}" title="L3: {layerDotStatus(result, 3)}"></span>
									</td>

									<!-- Score L3 -->
									<td class="col-score">
										{#if result.score !== null}
											<span class="score-value" style:color={scoreColor(result.score)}>
												{formatNumber(result.score, 3, "en-US")}
											</span>
										{:else}
											<span class="score-value score-value--empty">—</span>
										{/if}
									</td>

									<!-- Status badge -->
									<td class="col-status">
										<StatusBadge status={result.overall_status} resolve={resolveWealthStatus} />
									</td>

									<!-- DD Requerido -->
									<td class="col-dd">
										<span class="dd-label">{ddLabel(result.required_analysis_type)}</span>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</Card>
		{:else}
			<EmptyState
				title="No results"
				message="Run the screening batch to classify instruments in the universe."
			/>
		{/if}
	</main>
</div>

<!-- ── Instrument Detail Panel ─────────────────────────────────────────────── -->
<ContextPanel
	open={panelOpen}
	onClose={closePanel}
	title={selectedResult ? instrumentLabel(selectedResult) : "Instrument"}
	width="480px"
>
	{#if selectedResult}
		{@const r = selectedResult}

		<!-- Score badge -->
		<div class="panel-score-section">
				<div
					class="score-circle"
					style:border-color={scoreColor(r.score)}
					style:color={scoreColor(r.score)}
				>
					{#if r.score !== null}
						<span class="score-circle__value">{formatNumber(r.score, 3, "en-US")}</span>
						<span class="score-circle__label">Score L3</span>
					{:else}
					<span class="score-circle__value">—</span>
					<span class="score-circle__label">N/A</span>
				{/if}
			</div>
			<div class="panel-meta">
				<StatusBadge status={r.overall_status} resolve={resolveWealthStatus} />
				<span class="panel-meta__type">{typeLabel(r.instrument_type)}</span>
				{#if r.block_id}
					<span class="panel-meta__block">{r.block_id}</span>
				{/if}
				<span class="panel-meta__date">Screened: {formatDate(r.screened_at)}</span>
			</div>
		</div>

		<!-- Layer 1 — Eliminatórios -->
		<div class="panel-layer-section">
			<h4 class="panel-layer-title">
				<span class="panel-layer-badge panel-layer-badge--l1">L1</span>
				Knockout Criteria
			</h4>
			{#if layerCriteria(r, 1).length > 0}
				<ul class="criteria-list">
					{#each layerCriteria(r, 1) as c (c.criterion)}
						<li class="criteria-item" class:criteria-item--fail={!c.passed}>
							<span class="criteria-dot criteria-dot--{c.passed ? 'pass' : 'fail'}"></span>
							<div class="criteria-content">
								<span class="criteria-criterion">{c.criterion}</span>
								<span class="criteria-detail">
									Expected: <strong>{c.expected}</strong>
									· Actual: <strong>{c.actual}</strong>
								</span>
							</div>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="panel-empty-note">No L1 criteria recorded.</p>
			{/if}
		</div>

		<!-- Layer 2 — Mandato + Eligible Block -->
		<div class="panel-layer-section">
			<h4 class="panel-layer-title">
				<span class="panel-layer-badge panel-layer-badge--l2">L2</span>
				Mandate Fit
			</h4>
			{#if r.block_id}
				<div class="block-badge-row">
					<span class="block-chip">{r.block_id}</span>
				</div>
			{/if}
			{#if layerCriteria(r, 2).length > 0}
				<ul class="criteria-list">
					{#each layerCriteria(r, 2) as c (c.criterion)}
						<li class="criteria-item" class:criteria-item--fail={!c.passed}>
							<span class="criteria-dot criteria-dot--{c.passed ? 'pass' : 'fail'}"></span>
							<div class="criteria-content">
								<span class="criteria-criterion">{c.criterion}</span>
								<span class="criteria-detail">
									Expected: <strong>{c.expected}</strong>
									· Actual: <strong>{c.actual}</strong>
								</span>
							</div>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="panel-empty-note">No L2 criteria recorded.</p>
			{/if}
		</div>

		<!-- Layer 3 — Score Quant table -->
		<div class="panel-layer-section">
			<h4 class="panel-layer-title">
				<span class="panel-layer-badge panel-layer-badge--l3">L3</span>
				Quantitative Score
			</h4>
			{#if l3Metrics(r).length > 0}
				<table class="l3-table">
					<thead>
						<tr>
							<th>Metric</th>
							<th>Expected</th>
							<th>Actual</th>
							<th>Status</th>
						</tr>
					</thead>
					<tbody>
						{#each l3Metrics(r) as m (m.criterion)}
							<tr class:l3-row--fail={!m.passed}>
								<td class="l3-metric">{m.criterion}</td>
								<td class="l3-expected">{m.expected}</td>
								<td class="l3-actual">{m.actual}</td>
								<td class="l3-status">
									<span class="criteria-dot criteria-dot--{m.passed ? 'pass' : 'fail'}"></span>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{:else}
				<p class="panel-empty-note">L3 Score not calculated (instrument eliminated at L1 or L2).</p>
			{/if}
		</div>

		<!-- CTAs -->
		<div class="panel-ctas">
			{#if r.required_analysis_type === "dd_report"}
				<a href="/dd-reports/{r.instrument_id}" class="cta-primary">
					Start DD Report
				</a>
			{:else if r.required_analysis_type === "bond_brief"}
				<a href="/dd-reports/{r.instrument_id}" class="cta-primary">
					Start Bond Brief
				</a>
			{/if}
			<button class="cta-secondary" onclick={() => loadInstrumentHistory(r.instrument_id, instrumentLabel(r))}>
				History
			</button>
			{#if latestRun}
				<button class="cta-secondary" onclick={() => loadRunDetail(latestRun!.run_id)}>
					Run Details
				</button>
			{/if}
		</div>
	{/if}
</ContextPanel>

<!-- Run Detail Panel -->
{#if showRunDetail}
	<ContextPanel
		open={showRunDetail}
		title="Run Detail"
		onClose={() => { showRunDetail = false; runDetailData = null; }}
		width="480px"
	>
		<div class="p-4">
			{#if runDetailLoading}
				<p class="text-sm text-(--netz-text-muted)">Loading...</p>
			{:else if runDetailData}
				{#each Object.entries(runDetailData) as [key, value]}
					<div class="mb-2">
						<p class="text-xs text-(--netz-text-muted)">{key}</p>
						<p class="text-sm text-(--netz-text-primary)">{String(value ?? "—")}</p>
					</div>
				{/each}
			{:else}
				<p class="text-sm text-(--netz-text-muted)">No run data available.</p>
			{/if}
		</div>
	</ContextPanel>
{/if}

<!-- Instrument History Panel -->
{#if showHistory}
	<ContextPanel
		open={showHistory}
		title={`History: ${historyInstrumentName}`}
		onClose={() => { showHistory = false; historyData = []; }}
		width="480px"
	>
		<div class="p-4">
			{#if historyLoading}
				<p class="text-sm text-(--netz-text-muted)">Loading...</p>
			{:else if historyData.length > 0}
				<div class="space-y-3">
					{#each historyData as entry}
						<div class="rounded-md border border-(--netz-border) p-3">
							<div class="flex items-center justify-between">
								<StatusBadge status={String(entry.overall_status ?? "")} resolve={resolveWealthStatus} />
								<span class="text-xs text-(--netz-text-muted)">{String(entry.screened_at ?? "")}</span>
							</div>
							{#if entry.score != null}
								<p class="mt-1 text-sm font-mono text-(--netz-text-secondary)">Score: {formatNumber(Number(entry.score), 3, "en-US")}</p>
							{/if}
						</div>
					{/each}
				</div>
			{:else}
				<p class="text-sm text-(--netz-text-muted)">No screening history for this instrument.</p>
			{/if}
		</div>
	</ContextPanel>
{/if}

<style>
	/* TODO: Migrate scoped CSS to Tailwind utilities — tracked as tech debt */

	/* ── Layout ───────────────────────────────────────────────────────────── */

	.screener-layout {
		display: flex;
		gap: 0;
		min-height: 100%;
	}

	.funnel-sidebar {
		width: 200px;
		min-width: 200px;
		padding: 24px 16px;
		border-right: 1px solid var(--netz-border);
		background: var(--netz-surface-elevated);
		display: flex;
		flex-direction: column;
		gap: 0;
	}

	.screener-main {
		flex: 1;
		min-width: 0;
		padding: 24px;
		display: flex;
		flex-direction: column;
		gap: 20px;
	}

	/* ── Funnel Sidebar ───────────────────────────────────────────────────── */

	.funnel-title {
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--netz-text-muted);
		margin: 0 0 16px 0;
	}

	.funnel-stages {
		display: flex;
		flex-direction: column;
	}

	.funnel-stage {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 12px 10px;
		border-radius: 8px;
		border: 1px solid var(--netz-border);
		background: var(--netz-surface);
		text-align: center;
		gap: 2px;
	}

	.funnel-stage__label {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--netz-text-muted);
		line-height: 1.2;
	}

	.funnel-stage__count {
		font-size: 22px;
		font-weight: 700;
		color: var(--netz-text-primary);
		line-height: 1.1;
		font-variant-numeric: tabular-nums;
	}

	.funnel-stage__sublabel {
		font-size: 10px;
		color: var(--netz-text-muted);
	}

	.funnel-stage--universe .funnel-stage__count {
		color: var(--netz-text-secondary);
	}

	.funnel-stage--l1 .funnel-stage__count {
		color: var(--netz-primary);
	}

	.funnel-stage--l2 .funnel-stage__count {
		color: var(--netz-primary);
	}

	.funnel-connector {
		width: 1px;
		height: 14px;
		background: var(--netz-border);
		margin: 0 auto;
	}

	/* L3 outcomes inside funnel stage */
	.funnel-outcomes {
		display: flex;
		flex-direction: column;
		gap: 4px;
		width: 100%;
		margin-top: 6px;
	}

	.funnel-outcome {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 3px 6px;
		border-radius: 4px;
		background: var(--netz-surface-inset);
	}

	.funnel-outcome__dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.funnel-outcome--pass .funnel-outcome__dot { background: var(--netz-success); }
	.funnel-outcome--watch .funnel-outcome__dot { background: var(--netz-warning); }
	.funnel-outcome--fail .funnel-outcome__dot { background: var(--netz-danger); }

	.funnel-outcome__label {
		font-size: 10px;
		font-weight: 600;
		color: var(--netz-text-muted);
		flex: 1;
	}

	.funnel-outcome__count {
		font-size: 12px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}

	.funnel-outcome--pass .funnel-outcome__count { color: var(--netz-success); }
	.funnel-outcome--watch .funnel-outcome__count { color: var(--netz-warning); }
	.funnel-outcome--fail .funnel-outcome__count { color: var(--netz-danger); }

	/* ── Header actions ───────────────────────────────────────────────────── */

	.header-meta {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
	}

	.header-meta__run {
		font-size: 13px;
		color: var(--netz-text-muted);
	}

	.header-meta__count {
		font-size: 13px;
		color: var(--netz-text-secondary);
		font-weight: 500;
	}

	.header-meta__error {
		font-size: 12px;
		color: var(--netz-danger);
	}

	/* ── Status tabs ──────────────────────────────────────────────────────── */

	.status-tabs {
		display: flex;
		gap: 2px;
		border-bottom: 1px solid var(--netz-border);
		padding-bottom: 0;
	}

	.status-tab {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 8px 14px;
		border: none;
		background: transparent;
		font-size: 13px;
		font-weight: 500;
		color: var(--netz-text-muted);
		cursor: pointer;
		border-bottom: 2px solid transparent;
		margin-bottom: -1px;
		transition: color 120ms ease, border-color 120ms ease;
		border-radius: 4px 4px 0 0;
	}

	.status-tab:hover {
		color: var(--netz-text-primary);
		background: var(--netz-surface-inset);
	}

	.status-tab--active {
		color: var(--netz-primary);
		border-bottom-color: var(--netz-primary);
	}

	.status-tab__badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 20px;
		height: 18px;
		padding: 0 5px;
		border-radius: 9px;
		background: var(--netz-surface-inset);
		font-size: 11px;
		font-weight: 600;
		color: var(--netz-text-secondary);
	}

	.status-tab--active .status-tab__badge {
		background: var(--netz-primary-muted, color-mix(in srgb, var(--netz-primary) 15%, transparent));
		color: var(--netz-primary);
	}

	/* ── Results table ────────────────────────────────────────────────────── */

	.table-scroll-container {
		height: 600px;
		overflow: auto;
	}

	.results-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}

	.results-table thead th {
		padding: 8px 12px;
		text-align: left;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--netz-text-muted);
		border-bottom: 1px solid var(--netz-border);
		white-space: nowrap;
		background: var(--netz-surface-elevated);
	}

	.results-table tbody td {
		padding: 10px 12px;
		border-bottom: 1px solid var(--netz-border);
		vertical-align: middle;
	}

	.result-row {
		cursor: pointer;
		transition: background-color 80ms ease;
	}

	.result-row:hover td {
		background: var(--netz-surface-inset);
	}

	/* BL-16: Eliminated row styling */
	.result-row--eliminated td {
		opacity: 0.6;
		background: color-mix(in srgb, var(--netz-danger) 3%, transparent);
	}

	.result-row--eliminated:hover td {
		opacity: 0.8;
		background: color-mix(in srgb, var(--netz-danger) 6%, transparent);
	}

	.instrument-name--eliminated {
		text-decoration: line-through;
		text-decoration-color: var(--netz-danger);
		text-decoration-thickness: 1px;
	}

	.elimination-reason {
		font-size: 10px;
		color: var(--netz-danger);
		font-weight: 500;
		line-height: 1.2;
	}

	.layer-pass-label {
		display: block;
		font-size: 8px;
		font-weight: 600;
		color: var(--netz-success);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		line-height: 1;
		margin-top: 2px;
	}

	.virtual-row {
		display: table-row;
	}

	.results-table thead {
		position: sticky;
		top: 0;
		z-index: 1;
	}

	/* Instrumento cell */
	.instrument-cell {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 160px;
	}

	.instrument-name {
		font-weight: 500;
		color: var(--netz-text-primary);
		line-height: 1.3;
	}

	.instrument-sub {
		font-size: 11px;
		color: var(--netz-text-muted);
		font-family: var(--font-mono, monospace);
	}

	/* Tipo badges */
	.tipo-badge {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 4px;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.02em;
		white-space: nowrap;
	}

	.tipo-fund   { background: color-mix(in srgb, var(--netz-primary) 12%, transparent); color: var(--netz-primary); }
	.tipo-bond   { background: color-mix(in srgb, var(--netz-warning) 15%, transparent); color: var(--netz-warning); }
	.tipo-equity { background: color-mix(in srgb, var(--netz-success) 12%, transparent); color: var(--netz-success); }
	.tipo-other  { background: var(--netz-surface-inset); color: var(--netz-text-muted); }

	/* Bloco */
	.bloco-label {
		font-size: 12px;
		color: var(--netz-text-secondary);
		font-family: var(--font-mono, monospace);
	}

	/* Column widths */
	.col-instrumento { min-width: 180px; }
	.col-tipo        { width: 100px; }
	.col-bloco       { width: 120px; }
	.col-layers      { width: 48px; text-align: center; }
	.col-score       { width: 80px; text-align: right; }
	.col-status      { width: 100px; }
	.col-dd          { width: 100px; }

	/* Layer dots */
	.layer-dot {
		display: inline-block;
		width: 10px;
		height: 10px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.layer-dot--pass { background: var(--netz-success); }
	.layer-dot--fail { background: var(--netz-danger); }
	.layer-dot--none { background: var(--netz-border); }

	/* Score */
	.score-value {
		font-family: var(--font-mono, monospace);
		font-size: 13px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.score-value--empty {
		color: var(--netz-text-muted);
		font-weight: 400;
	}

	/* DD label */
	.dd-label {
		font-size: 12px;
		color: var(--netz-text-secondary);
	}

	/* ── Context Panel styles ─────────────────────────────────────────────── */

	/* Score circle */
	.panel-score-section {
		display: flex;
		align-items: center;
		gap: 16px;
		padding-bottom: 20px;
		border-bottom: 1px solid var(--netz-border);
		margin-bottom: 20px;
	}

	.score-circle {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		width: 72px;
		height: 72px;
		border-radius: 50%;
		border: 3px solid;
		flex-shrink: 0;
	}

	.score-circle__value {
		font-size: 18px;
		font-weight: 700;
		line-height: 1;
		font-variant-numeric: tabular-nums;
	}

	.score-circle__label {
		font-size: 9px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--netz-text-muted);
		margin-top: 2px;
	}

	.panel-meta {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.panel-meta__type {
		font-size: 12px;
		color: var(--netz-text-secondary);
	}

	.panel-meta__block {
		font-size: 11px;
		color: var(--netz-text-muted);
		font-family: var(--font-mono, monospace);
	}

	.panel-meta__date {
		font-size: 11px;
		color: var(--netz-text-muted);
	}

	/* Layer sections */
	.panel-layer-section {
		margin-bottom: 20px;
	}

	.panel-layer-section:last-of-type {
		margin-bottom: 0;
	}

	.panel-layer-title {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 13px;
		font-weight: 600;
		color: var(--netz-text-primary);
		margin: 0 0 10px 0;
	}

	.panel-layer-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		font-size: 10px;
		font-weight: 700;
		flex-shrink: 0;
	}

	.panel-layer-badge--l1 {
		background: color-mix(in srgb, var(--netz-danger) 15%, transparent);
		color: var(--netz-danger);
	}

	.panel-layer-badge--l2 {
		background: color-mix(in srgb, var(--netz-warning) 15%, transparent);
		color: var(--netz-warning);
	}

	.panel-layer-badge--l3 {
		background: color-mix(in srgb, var(--netz-primary) 15%, transparent);
		color: var(--netz-primary);
	}

	/* Block badge row */
	.block-badge-row {
		margin-bottom: 8px;
	}

	.block-chip {
		display: inline-block;
		padding: 3px 10px;
		border-radius: 4px;
		border: 1px solid var(--netz-border);
		background: var(--netz-surface-inset);
		font-size: 11px;
		font-weight: 500;
		color: var(--netz-text-secondary);
		font-family: var(--font-mono, monospace);
	}

	/* Criteria list */
	.criteria-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.criteria-item {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		padding: 8px 10px;
		border-radius: 6px;
		background: var(--netz-surface-inset);
	}

	.criteria-item--fail {
		background: color-mix(in srgb, var(--netz-danger) 6%, transparent);
	}

	.criteria-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		margin-top: 3px;
		flex-shrink: 0;
	}

	.criteria-dot--pass { background: var(--netz-success); }
	.criteria-dot--fail { background: var(--netz-danger); }

	.criteria-content {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.criteria-criterion {
		font-size: 12px;
		font-weight: 500;
		color: var(--netz-text-primary);
	}

	.criteria-detail {
		font-size: 11px;
		color: var(--netz-text-muted);
	}

	/* L3 table */
	.l3-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12px;
	}

	.l3-table th {
		padding: 6px 8px;
		text-align: left;
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--netz-text-muted);
		border-bottom: 1px solid var(--netz-border);
	}

	.l3-table td {
		padding: 7px 8px;
		border-bottom: 1px solid var(--netz-border);
		vertical-align: middle;
	}

	.l3-row--fail td {
		background: color-mix(in srgb, var(--netz-danger) 4%, transparent);
	}

	.l3-metric {
		color: var(--netz-text-primary);
		font-weight: 500;
	}

	.l3-expected,
	.l3-actual {
		font-family: var(--font-mono, monospace);
		color: var(--netz-text-secondary);
	}

	.l3-status {
		text-align: center;
	}

	.panel-empty-note {
		font-size: 12px;
		color: var(--netz-text-muted);
		font-style: italic;
		margin: 0;
		padding: 8px 0;
	}

	/* CTAs */
	.panel-ctas {
		display: flex;
		gap: 8px;
		padding-top: 20px;
		border-top: 1px solid var(--netz-border);
		margin-top: 24px;
		flex-wrap: wrap;
	}

	.cta-primary {
		display: inline-flex;
		align-items: center;
		padding: 8px 16px;
		border-radius: 6px;
		background: var(--netz-primary);
		color: var(--netz-primary-foreground, #fff);
		font-size: 13px;
		font-weight: 500;
		text-decoration: none;
		transition: opacity 120ms ease;
	}

	.cta-primary:hover {
		opacity: 0.88;
	}

	.cta-secondary {
		display: inline-flex;
		align-items: center;
		padding: 8px 16px;
		border-radius: 6px;
		border: 1px solid var(--netz-border);
		background: var(--netz-surface-elevated);
		color: var(--netz-text-secondary);
		font-size: 13px;
		font-weight: 500;
		cursor: pointer;
		transition: background-color 120ms ease;
	}

	.cta-secondary:hover {
		background: var(--netz-surface-inset);
	}
</style>
