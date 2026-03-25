<!--
  Instrument search results table with infinite scroll pagination.
-->
<script lang="ts">
	import "./screener.css";
	import { getContext } from "svelte";
	import { page } from "$app/stores";
	import { Button, StatusBadge, formatAUM, formatPercent } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { InstrumentSearchPage, InstrumentSearchItem } from "$lib/types/screening";
	import { EMPTY_SEARCH_PAGE } from "$lib/types/screening";

	interface Props {
		searchResults: InstrumentSearchPage;
		searchQ: string;
		onOpenInstrumentDetail?: (item: InstrumentSearchItem) => void;
	}

	let { searchResults = EMPTY_SEARCH_PAGE, searchQ = "", onOpenInstrumentDetail }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// ── Accumulated items for infinite scroll ──
	let allItems = $state<InstrumentSearchItem[]>([]);
	let currentPage = $state(1);
	let hasMore = $state(false);
	let totalCount = $state(0);
	let loading = $state(false);
	let sentinelEl: HTMLDivElement | undefined = $state(undefined);
	let prevSearchKey = $state("");

	// Reset when SSR data changes (new filters / search)
	$effect(() => {
		const key = JSON.stringify({
			total: searchResults.total,
			page: searchResults.page,
			firstItem: searchResults.items[0]?.isin ?? searchResults.items[0]?.name ?? "",
		});
		if (key !== prevSearchKey) {
			prevSearchKey = key;
			allItems = [...searchResults.items];
			currentPage = searchResults.page;
			hasMore = searchResults.has_next;
			totalCount = searchResults.total;
		}
	});

	// ── IntersectionObserver for sentinel ──
	$effect(() => {
		if (!sentinelEl) return;
		const observer = new IntersectionObserver(
			(entries) => {
				if (entries[0]?.isIntersecting && hasMore && !loading) {
					loadNextPage();
				}
			},
			{ rootMargin: "200px" },
		);
		observer.observe(sentinelEl);
		return () => observer.disconnect();
	});

	let abortController: AbortController | null = null;

	async function loadNextPage() {
		if (loading || !hasMore) return;
		loading = true;

		abortController?.abort();
		abortController = new AbortController();

		try {
			const api = createClientApiClient(getToken);
			const nextPage = currentPage + 1;

			// Build params from current URL search params
			const params: Record<string, string> = {};
			const urlParams = $page.url.searchParams;
			for (const key of ["q", "instrument_type", "asset_class", "geography", "domicile", "currency", "strategy", "source", "approval_status", "block_id", "aum_min"]) {
				const val = urlParams.get(key);
				if (val) params[key] = val;
			}
			params.page = String(nextPage);
			params.page_size = urlParams.get("page_size") ?? "50";

			const result = await api.get<InstrumentSearchPage>("/screener/search", params);

			if (!abortController.signal.aborted) {
				allItems = [...allItems, ...result.items];
				currentPage = result.page;
				hasMore = result.has_next;
				totalCount = result.total;
			}
		} catch (e) {
			if (e instanceof DOMException && e.name === "AbortError") return;
		} finally {
			loading = false;
		}
	}

	function sourceBadgeClass(source: string): string {
		switch (source) {
			case "internal": return "source-badge--internal";
			case "esma": return "source-badge--esma";
			case "sec": return "source-badge--sec";
			default: return "";
		}
	}

	function typeBadgeClass(type: string): string {
		switch (type) {
			case "fund": return "type-badge--fund";
			case "etf": return "type-badge--etf";
			case "bond": return "type-badge--bond";
			case "equity": return "type-badge--equity";
			case "hedge_fund": return "type-badge--hedge";
			default: return "";
		}
	}
</script>

<div class="scr-data-header">
	<span class="scr-data-count">
		Results
		<span class="scr-count-badge">{totalCount} INSTRUMENT{totalCount !== 1 ? "S" : ""}</span>
	</span>
	{#if searchQ}
		<span class="scr-data-count-muted">matching "{searchQ}"</span>
	{/if}
</div>

{#if allItems.length === 0 && !loading}
	<div class="scr-empty">No instruments found. Adjust filters or search.</div>
{:else}
	<div class="scr-table-wrap">
		<table class="scr-table">
			<thead>
				<tr>
					<th class="sth-name">Name</th>
					<th>Type</th>
					<th>Source</th>
					<th>Manager</th>
					<th class="sth-aum">AUM</th>
					<th>Geography</th>
					<th>Currency</th>
					<th class="sth-score">Score</th>
					<th class="sth-status">Status</th>
					<th>Action</th>
				</tr>
			</thead>
			<tbody>
				{#each allItems as item (item.isin ?? item.instrument_id ?? item.name)}
					<tr class="scr-inst-row" onclick={() => onOpenInstrumentDetail?.(item)}>
						<td class="std-name">
							<span class="inst-name">{item.name}</span>
							{#if item.isin || item.ticker}
								<span class="inst-ids">
									{#if item.isin}{item.isin}{/if}
									{#if item.isin && item.ticker} · {/if}
									{#if item.ticker}{item.ticker}{/if}
								</span>
							{/if}
						</td>
						<td>
							<span class="type-badge {typeBadgeClass(item.instrument_type)}">
								{item.instrument_type}
							</span>
						</td>
						<td>
							<span class="source-badge {sourceBadgeClass(item.source)}">
								{item.source}
							</span>
						</td>
						<td class="std-manager">{item.manager_name ?? "—"}</td>
						<td class="std-aum">{item.aum ? formatAUM(item.aum) : "—"}</td>
						<td>{item.geography}{item.domicile ? ` / ${item.domicile}` : ""}</td>
						<td>{item.currency}</td>
						<td class="std-score">
							{#if item.screening_score !== null}
								<span>{formatPercent(item.screening_score)}</span>
							{:else}
								<span class="score-na">—</span>
							{/if}
						</td>
						<td class="std-status">
							{#if item.screening_status}
								<StatusBadge status={item.screening_status} />
							{:else if item.approval_status}
								<StatusBadge status={item.approval_status} />
							{:else}
								<span class="score-na">—</span>
							{/if}
						</td>
						<td onclick={(e) => e.stopPropagation()}>
							{#if item.source === "esma" && !item.instrument_id}
								<Button size="sm" variant="outline" onclick={() => onOpenInstrumentDetail?.(item)}>
									Add to Review
								</Button>
							{:else if item.instrument_id}
								<Button size="sm" variant="ghost" onclick={() => onOpenInstrumentDetail?.(item)}>
									View
								</Button>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>

		<!-- Infinite scroll sentinel -->
		<div bind:this={sentinelEl} class="scr-scroll-sentinel">
			{#if loading}
				<div class="scr-scroll-loader">
					<span class="scr-spinner"></span>
					<span>Loading more…</span>
				</div>
			{:else if !hasMore && allItems.length > 0}
				<div class="scr-scroll-end">
					{totalCount} instrument{totalCount !== 1 ? "s" : ""} loaded
				</div>
			{/if}
		</div>
	</div>
{/if}

<style>
	.scr-count-badge {
		display: inline-flex;
		align-items: center;
		padding: 3px 10px;
		background: #eff6ff;
		border-radius: 8px;
		font-size: 11px;
		font-weight: 700;
		color: #1447e6;
		text-transform: uppercase;
		letter-spacing: 0.55px;
	}

	.scr-scroll-sentinel {
		padding: var(--netz-space-stack-sm, 12px) 0;
		min-height: 1px;
	}

	.scr-scroll-loader {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--netz-space-inline-xs, 8px);
		color: var(--netz-text-muted);
		font-size: var(--netz-text-small, 0.8125rem);
		padding: var(--netz-space-stack-xs, 8px);
	}

	.scr-spinner {
		display: inline-block;
		width: 16px;
		height: 16px;
		border: 2px solid var(--netz-border);
		border-top-color: var(--netz-brand-primary);
		border-radius: 50%;
		animation: scr-spin 600ms linear infinite;
	}

	@keyframes scr-spin {
		to { transform: rotate(360deg); }
	}

	.scr-scroll-end {
		text-align: center;
		color: var(--netz-text-muted);
		font-size: var(--netz-text-small, 0.8125rem);
		padding: var(--netz-space-stack-xs, 8px);
	}
</style>
