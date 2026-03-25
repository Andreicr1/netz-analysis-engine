<!--
  Screener — Tabbed asset-class view with inline filters and multi-select.
  Tabs: Funds / Equities / Fixed Income / ETF.
  Managers moved to US Fund Analysis.
-->
<script lang="ts">
	import { untrack, getContext } from "svelte";
	import { invalidateAll } from "$app/navigation";
	import { PageHeader, Button, ContextPanel } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { InstrumentSearchPage, ScreenerFacets, InstrumentSearchItem, ScreenerTab } from "$lib/types/screening";
	import { EMPTY_SEARCH_PAGE, EMPTY_FACETS } from "$lib/types/screening";
	import { ScreenerFilters, InstrumentTable, InstrumentDetailPanel } from "$lib/components/screener";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	let { data }: { data: PageData } = $props();

	// ── SSR data ──
	let searchResults = $derived((data.searchResults ?? EMPTY_SEARCH_PAGE) as InstrumentSearchPage);
	let facets = $derived((data.facets ?? EMPTY_FACETS) as ScreenerFacets);

	// ── Tab from URL params ──
	const initParams = (untrack(() => data.currentParams) as Record<string, string>) ?? {};
	let activeTab = $state<ScreenerTab>((initParams.tab as ScreenerTab) ?? "fund");

	// ── CSV Export ──
	function exportCSV() {
		const items = searchResults.items;
		if (items.length === 0) return;
		const headers = ["Ticker", "Name", "Manager", "AUM", "Currency", "Geography"];
		const lines = [
			headers.join(","),
			...items.map(r => [
				r.ticker ?? "",
				`"${r.name ?? ""}"`,
				`"${r.manager_name ?? ""}"`,
				r.aum ?? "",
				r.currency ?? "",
				r.geography ?? "",
			].join(","))
		];
		const blob = new Blob([lines.join("\n")], { type: "text/csv" });
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = `screener-${activeTab}-${new Date().toISOString().slice(0,10)}.csv`;
		a.click();
		URL.revokeObjectURL(url);
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
			runError = e instanceof Error ? e.message : "Failed";
		} finally {
			isRunning = false;
		}
	}

	// ── Panel state ──
	let panelOpen = $state(false);
	let selectedItem = $state<InstrumentSearchItem | null>(null);
	let panelTitle = $derived(selectedItem?.name ?? "");

	function openDetail(item: InstrumentSearchItem) {
		selectedItem = item;
		panelOpen = true;
	}

	function closePanel() {
		panelOpen = false;
		selectedItem = null;
	}
</script>

<PageHeader title="Screener">
	{#snippet actions()}
		<div class="scr-actions">
			<button class="scr-btn scr-btn--outline" onclick={exportCSV}>
				<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
				Export
			</button>
			<button class="scr-btn scr-btn--primary" onclick={executeBatch} disabled={isRunning}>
				{isRunning ? "Running\u2026" : "Add to Portfolio"}
			</button>
		</div>
	{/snippet}
</PageHeader>

<div class="scr-page">
	<!-- Filter card with 4 tabs -->
	<ScreenerFilters
		{activeTab}
		{facets}
		{initParams}
	/>

	<!-- Results table -->
	<div class="scr-results">
		<InstrumentTable
			{searchResults}
			searchQ={initParams.q ?? ""}
			onOpenInstrumentDetail={openDetail}
		/>
	</div>

	{#if runError}
		<div class="scr-error">{runError}</div>
	{/if}
</div>

<!-- Context Panel -->
<ContextPanel open={panelOpen} onClose={closePanel} title={panelTitle} width="min(45vw, 680px)">
	{#if selectedItem}
		<InstrumentDetailPanel selectedInstrument={selectedItem} />
	{/if}
</ContextPanel>

<style>
	.scr-page {
		display: flex;
		flex-direction: column;
		gap: 24px;
		padding-bottom: 48px;
	}

	.scr-results {
		background: white;
		border: 1px solid #e2e8f0;
		border-radius: 16px;
		overflow: hidden;
		box-shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px -1px rgba(0,0,0,0.1);
	}

	.scr-actions {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.scr-btn {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 10px 20px;
		border-radius: 14px;
		font-size: 14px;
		font-weight: 600;
		font-family: var(--netz-font-sans);
		cursor: pointer;
		transition: all 120ms ease;
		border: none;
	}

	.scr-btn--outline {
		background: white;
		border: 1px solid #e2e8f0;
		color: #45556c;
		box-shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px -1px rgba(0,0,0,0.1);
	}

	.scr-btn--outline:hover {
		background: #f8fafc;
		border-color: #cbd5e1;
	}

	.scr-btn--primary {
		background: #155dfc;
		color: white;
		box-shadow: 0 2px 8px rgba(37,99,235,0.25);
	}

	.scr-btn--primary:hover {
		background: #1447e6;
	}

	.scr-btn--primary:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.scr-error {
		padding: 10px 16px;
		background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
		color: var(--netz-danger);
		font-size: 13px;
		border-radius: 8px;
	}
</style>
