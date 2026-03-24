<!--
  Instrument search results table with pagination.
-->
<script lang="ts">
	import "./screener.css";
	import { goto } from "$app/navigation";
	import { page } from "$app/stores";
	import { Button, StatusBadge, formatAUM, formatPercent } from "@netz/ui";
	import type { InstrumentSearchPage, InstrumentSearchItem } from "$lib/types/screening";
	import { EMPTY_SEARCH_PAGE } from "$lib/types/screening";

	interface Props {
		searchResults: InstrumentSearchPage;
		searchQ: string;
		onOpenInstrumentDetail?: (item: InstrumentSearchItem) => void;
	}

	let { searchResults = EMPTY_SEARCH_PAGE, searchQ = "", onOpenInstrumentDetail }: Props = $props();

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

	function goToSearchPage(p: number) {
		const params = new URLSearchParams($page.url.searchParams);
		params.set("page", String(p));
		goto(`/screener?${params.toString()}`, { invalidateAll: true });
	}
</script>

<div class="scr-data-header">
	<span class="scr-data-count">
		{searchResults.total} instrument{searchResults.total !== 1 ? "s" : ""}
		{#if searchQ}
			<span class="scr-data-count-muted">matching "{searchQ}"</span>
		{/if}
	</span>
</div>

{#if searchResults.items.length === 0}
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
				{#each searchResults.items as item (item.isin ?? item.instrument_id ?? item.name)}
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
									Add
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
	</div>

	<!-- Pagination -->
	<div class="scr-pagination">
		<button class="scr-page-btn" disabled={searchResults.page <= 1} onclick={() => goToSearchPage(searchResults.page - 1)}>Previous</button>
		<span class="scr-page-info">Page {searchResults.page} · {searchResults.total} total</span>
		<button class="scr-page-btn" disabled={!searchResults.has_next} onclick={() => goToSearchPage(searchResults.page + 1)}>Next</button>
	</div>
{/if}
