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
	import { ScreenerFilters, InstrumentTable, InstrumentDetailPanel, FundDetailPanel } from "$lib/components/screener";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	let { data }: { data: PageData } = $props();

	// ── SSR data ──
	let searchResults = $derived((data.searchResults ?? EMPTY_SEARCH_PAGE) as InstrumentSearchPage);
	let facets = $derived((data.facets ?? EMPTY_FACETS) as ScreenerFacets);

	// ── Tab from URL params ──
	const initParams = (untrack(() => data.currentParams) as Record<string, string>) ?? {};
	let activeTab = $state<ScreenerTab>((initParams.tab as ScreenerTab) ?? "fund");

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
			<Button size="sm" onclick={executeBatch} disabled={isRunning}>
				{isRunning ? "Running\u2026" : "Run Screening"}
			</Button>
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
		{#if selectedItem.instrument_type === "fund" || selectedItem.instrument_type === "etf"}
			<InstrumentDetailPanel selectedInstrument={selectedItem} />
		{:else}
			<InstrumentDetailPanel selectedInstrument={selectedItem} />
		{/if}
	{/if}
</ContextPanel>

<style>
	.scr-page {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding-bottom: 48px;
	}

	.scr-results {
		background: var(--netz-surface-elevated);
		border: 1px solid var(--netz-border-subtle);
		border-radius: 16px;
		overflow: hidden;
		box-shadow: 0 2px 12px rgba(0,0,0,0.04);
	}

	.scr-actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.scr-error {
		padding: 10px 16px;
		background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
		color: var(--netz-danger);
		font-size: 13px;
		border-radius: 8px;
	}
</style>
