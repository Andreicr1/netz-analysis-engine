<!--
  Unified Screener — Dual mode: Instrument Search (flat) + Manager Screener (hierarchical).
  Left sidebar: context-aware filters (instrument search OR manager filters).
  Right surface: paginated instrument table OR manager→fund hierarchy.
  Peer comparison mode + 4-tab manager detail + fund detail panel.
-->
<script lang="ts">
	import { getContext, untrack } from "svelte";
	import { goto, invalidateAll } from "$app/navigation";
	import { PageHeader, Button, ContextPanel } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { ScreeningResult, ScreenerFilterConfig, InstrumentSearchPage, ScreenerFacets, InstrumentSearchItem } from "$lib/types/screening";
	import { EMPTY_FILTERS, EMPTY_SEARCH_PAGE, EMPTY_FACETS } from "$lib/types/screening";
	import type { ManagerRow, ScreenerPage, CompareResult } from "$lib/types/manager-screener";
	import { EMPTY_SCREENER } from "$lib/types/manager-screener";
	import {
		InstrumentFilterSidebar, ManagerFilterSidebar,
		InstrumentTable, PeerComparisonView, ManagerHierarchyTable,
		ManagerDetailPanel, InstrumentDetailPanel, FundDetailPanel,
	} from "$lib/components/screener";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	let { data }: { data: PageData } = $props();

	// ── Mode toggle ──
	type ScreenerMode = "instruments" | "managers";
	const initParams = (untrack(() => data.currentParams) as Record<string, string>) ?? {};
	let activeMode = $state<ScreenerMode>((initParams.mode as ScreenerMode) ?? "instruments");

	function switchMode(mode: ScreenerMode) {
		activeMode = mode;
		goto(`/screener?mode=${mode}`, { invalidateAll: true });
	}

	// ── SSR data ──
	let screener = $derived((data.screener ?? EMPTY_SCREENER) as ScreenerPage);
	let results = $derived((data.results ?? []) as ScreeningResult[]);
	let lastRun = $derived(data.lastRun as import("$lib/types/screening").ScreeningRun | null);
	let searchResults = $derived((data.searchResults ?? EMPTY_SEARCH_PAGE) as InstrumentSearchPage);
	let facets = $derived((data.facets ?? EMPTY_FACETS) as ScreenerFacets);

	// ── Fund filter state ──
	let fundFilters = $state<ScreenerFilterConfig>({ ...EMPTY_FILTERS });

	let filteredResults = $derived.by(() => {
		let rows = results;
		if (fundFilters.status) rows = rows.filter((r) => r.overall_status === fundFilters.status);
		if (fundFilters.instrument_type) rows = rows.filter((r) => r.instrument_type === fundFilters.instrument_type);
		if (fundFilters.block_id) rows = rows.filter((r) => r.block_id === fundFilters.block_id);
		if (fundFilters.search) {
			const q = fundFilters.search.toLowerCase();
			rows = rows.filter((r) =>
				(r.name?.toLowerCase().includes(q)) ||
				(r.isin?.toLowerCase().includes(q)) ||
				(r.ticker?.toLowerCase().includes(q)) ||
				(r.manager?.toLowerCase().includes(q))
			);
		}
		return rows;
	});

	const hasFundFilters = $derived(
		fundFilters.status !== null ||
		fundFilters.instrument_type !== null ||
		fundFilters.block_id !== null ||
		fundFilters.search !== ""
	);

	// ── Expand / collapse managers ──
	let expandedManagers = $state<Set<string>>(new Set());

	function toggleExpand(crd: string) {
		const next = new Set(expandedManagers);
		if (next.has(crd)) next.delete(crd); else next.add(crd);
		expandedManagers = next;
	}

	// ── Selection (peer comparison) ──
	let selectedManagers = $state<Set<string>>(new Set());

	function toggleSelection(crd: string) {
		const next = new Set(selectedManagers);
		if (next.has(crd)) next.delete(crd); else if (next.size < 5) next.add(crd);
		selectedManagers = next;
	}

	let selectionCount = $derived(selectedManagers.size);
	let canCompare = $derived(selectionCount >= 2 && selectionCount <= 5);

	// ── Peer comparison ──
	let compareResult = $state<CompareResult | null>(null);
	let comparing = $state(false);
	let compareError = $state<string | null>(null);

	async function runCompare() {
		if (!canCompare) return;
		comparing = true;
		compareError = null;
		try {
			const api = createClientApiClient(getToken);
			compareResult = await api.post<CompareResult>("/manager-screener/managers/compare", {
				crd_numbers: Array.from(selectedManagers),
			});
		} catch (e) {
			compareError = e instanceof Error ? e.message : "Compare failed";
		} finally {
			comparing = false;
		}
	}

	function clearCompare() {
		selectedManagers = new Set();
		compareResult = null;
	}

	// ── Panel state ──
	let panelMode = $state<"manager" | "fund" | "instrument" | null>(null);
	let panelOpen = $state(false);
	let panelCrd = $state<string | null>(null);
	let panelFirm = $state("");
	let selectedFund = $state<ScreeningResult | null>(null);
	let selectedInstrument = $state<InstrumentSearchItem | null>(null);

	function openManagerDetail(manager: ManagerRow) {
		panelMode = "manager";
		panelCrd = manager.crd_number;
		panelFirm = manager.firm_name;
		panelOpen = true;
	}

	function openFundDetail(fund: ScreeningResult) {
		panelMode = "fund";
		selectedFund = fund;
		panelOpen = true;
	}

	function openInstrumentDetail(item: InstrumentSearchItem) {
		panelMode = "instrument";
		selectedInstrument = item;
		panelOpen = true;
	}

	function closePanel() {
		panelOpen = false;
		panelMode = null;
		panelCrd = null;
		selectedFund = null;
		selectedInstrument = null;
	}

	let panelTitle = $derived.by(() => {
		if (panelMode === "manager") return panelFirm;
		if (panelMode === "fund" && selectedFund) return selectedFund.name ?? selectedFund.instrument_id.slice(0, 8).toUpperCase();
		if (panelMode === "instrument" && selectedInstrument) return selectedInstrument.name ?? "";
		return "";
	});

	let panelWidth = $derived(panelMode === "manager" ? "min(50vw, 720px)" : "min(40vw, 600px)");

	// ── Run detail expand ──
	let runDetailData = $state<Record<string, unknown> | null>(null);
	let runDetailLoading = $state(false);
	let runDetailOpen = $state(false);

	async function toggleRunDetail() {
		if (runDetailOpen) {
			runDetailOpen = false;
			return;
		}
		if (!lastRun) return;
		runDetailOpen = true;
		runDetailLoading = true;
		try {
			const api = createClientApiClient(getToken);
			runDetailData = await api.get<Record<string, unknown>>(`/screener/runs/${lastRun.run_id}`);
		} catch {
			runDetailData = null;
		} finally {
			runDetailLoading = false;
		}
	}

	// ── Batch screening ──
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
</script>

<PageHeader title="Screener">
	{#snippet actions()}
		<div class="scr-actions">
			<div class="mode-toggle">
				<button class="mode-btn" class:mode-btn--active={activeMode === "instruments"} onclick={() => switchMode("instruments")}>Instruments</button>
				<button class="mode-btn" class:mode-btn--active={activeMode === "managers"} onclick={() => switchMode("managers")}>Managers</button>
			</div>
			{#if activeMode === "managers"}
				{#if canCompare}
					<Button size="sm" onclick={runCompare} disabled={comparing}>
						{comparing ? "Comparing…" : `Compare ${selectionCount}`}
					</Button>
				{/if}
				{#if selectionCount > 0}
					<Button size="sm" variant="ghost" onclick={clearCompare}>Clear</Button>
				{/if}
			{/if}
			<Button size="sm" onclick={executeBatch} disabled={isRunning}>
				{isRunning ? "Running…" : "Run Screening"}
			</Button>
		</div>
	{/snippet}
</PageHeader>

<div class="scr-grid">
	<!-- LEFT: FILTER PANEL -->
	<aside class="scr-filters">
		{#if activeMode === "instruments"}
			<InstrumentFilterSidebar {facets} {initParams} />
		{:else}
			<ManagerFilterSidebar {results} {lastRun} {runError} {initParams} bind:fundFilters
				onRunClick={toggleRunDetail} {runDetailOpen} {runDetailLoading} {runDetailData}
			/>
		{/if}
	</aside>

	<!-- RIGHT: DATA SURFACE -->
	<section class="scr-main">
		{#if activeMode === "instruments"}
			<InstrumentTable {searchResults} searchQ={initParams.q ?? ""} onOpenInstrumentDetail={openInstrumentDetail} />
		{:else if compareResult}
			<PeerComparisonView {compareResult} onClear={clearCompare} />
		{:else}
			<ManagerHierarchyTable
				{screener}
				{filteredResults}
				{hasFundFilters}
				{expandedManagers}
				{selectedManagers}
				onToggleExpand={toggleExpand}
				onToggleSelection={toggleSelection}
				onOpenManagerDetail={openManagerDetail}
				onOpenFundDetail={openFundDetail}
			/>
		{/if}

		{#if compareError}
			<div class="scr-error">{compareError}</div>
		{/if}
	</section>
</div>

<!-- CONTEXT PANEL -->
<ContextPanel open={panelOpen} onClose={closePanel} title={panelTitle} width={panelWidth}>
	{#if panelMode === "manager" && panelCrd}
		<ManagerDetailPanel {panelCrd} {panelFirm} />
	{:else if panelMode === "fund" && selectedFund}
		<FundDetailPanel {selectedFund} />
	{:else if panelMode === "instrument" && selectedInstrument}
		<InstrumentDetailPanel {selectedInstrument} />
	{/if}
</ContextPanel>

<style>
	/* ── Grid layout ── */
	.scr-grid {
		display: grid;
		grid-template-columns: 260px 1fr;
		gap: 0;
		height: calc(100vh - 64px);
		overflow: hidden;
	}

	.scr-actions {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-xs, 6px);
	}

	.scr-filters {
		overflow-y: auto;
		border-right: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-elevated);
		padding: 0;
	}

	.scr-main {
		display: flex;
		flex-direction: column;
		overflow: hidden;
		background: var(--netz-surface);
	}

	.scr-error {
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
		color: var(--netz-danger);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	/* ── Mode toggle ── */
	.mode-toggle {
		display: flex;
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 8px);
		overflow: hidden;
	}

	.mode-btn {
		padding: var(--netz-space-stack-2xs, 4px) var(--netz-space-inline-sm, 12px);
		border: none;
		background: transparent;
		color: var(--netz-text-secondary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-sans);
		font-weight: 500;
		cursor: pointer;
		transition: background 120ms ease, color 120ms ease;
	}

	.mode-btn:hover { background: var(--netz-surface-alt); }

	.mode-btn--active {
		background: color-mix(in srgb, var(--netz-brand-primary) 12%, transparent);
		color: var(--netz-brand-primary);
		font-weight: 600;
	}

	/* ── Responsive ── */
	@media (max-width: 768px) {
		.scr-grid {
			grid-template-columns: 1fr;
			grid-template-rows: auto 1fr;
			height: auto;
		}

		.scr-filters {
			border-right: none;
			border-bottom: 1px solid var(--netz-border-subtle);
			max-height: 300px;
		}

		.scr-main {
			min-height: 400px;
		}
	}
</style>
