<!--
  Filter sidebar for global securities discovery (equities/ETFs).
  Consumes GET /screener/securities/facets.
-->
<script lang="ts">
	import type { SecurityFacets } from "$lib/types/catalog";
	import { EMPTY_SECURITY_FACETS } from "$lib/types/catalog";

	interface Props {
		facets: SecurityFacets;
		selectedTypes: string[];
		selectedExchanges: string[];
		searchQ: string;
		onFilterChange: () => void;
	}

	let {
		facets = EMPTY_SECURITY_FACETS,
		selectedTypes = $bindable([]),
		selectedExchanges = $bindable([]),
		searchQ = $bindable(""),
		onFilterChange,
	}: Props = $props();

	function toggle(arr: string[], val: string): string[] {
		return arr.includes(val) ? arr.filter(v => v !== val) : [...arr, val];
	}

	function toggleType(val: string) { selectedTypes = toggle(selectedTypes, val); onFilterChange(); }
	function toggleExchange(val: string) { selectedExchanges = toggle(selectedExchanges, val); onFilterChange(); }

	function clearAll() {
		selectedTypes = [];
		selectedExchanges = [];
		searchQ = "";
		onFilterChange();
	}

	let hasFilters = $derived(selectedTypes.length > 0 || selectedExchanges.length > 0 || searchQ.length > 0);

	let debounceTimer: ReturnType<typeof setTimeout> | null = null;
	function debouncedChange() {
		if (debounceTimer) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => onFilterChange(), 400);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Enter") { if (debounceTimer) clearTimeout(debounceTimer); onFilterChange(); }
	}
</script>

<aside class="cfs-sidebar">
	<div class="cfs-section">
		<input class="cfs-search" type="text" placeholder="Search by name, ticker, CUSIP..." bind:value={searchQ} oninput={debouncedChange} onkeydown={handleKeydown} />
	</div>

	<div class="cfs-section">
		<h4 class="cfs-group-title">Security Type</h4>
		{#each facets.security_types as item (item.value)}
			<label class="cfs-check">
				<input type="checkbox" checked={selectedTypes.includes(item.value)} onchange={() => toggleType(item.value)} />
				<span class="cfs-check-label">{item.label}</span>
				<span class="cfs-check-count">{item.count?.toLocaleString() ?? "—"}</span>
			</label>
		{/each}
	</div>

	{#if facets.exchanges.length > 0}
		<div class="cfs-section">
			<h4 class="cfs-group-title">Exchange</h4>
			{#each facets.exchanges.slice(0, 12) as item (item.value)}
				<label class="cfs-check">
					<input type="checkbox" checked={selectedExchanges.includes(item.value)} onchange={() => toggleExchange(item.value)} />
					<span class="cfs-check-label">{item.label}</span>
					<span class="cfs-check-count">{item.count?.toLocaleString() ?? "—"}</span>
				</label>
			{/each}
		</div>
	{/if}

	{#if hasFilters}
		<div class="cfs-section cfs-section--actions">
			<button class="cfs-clear-btn" onclick={clearAll}>Clear All Filters</button>
		</div>
	{/if}
</aside>

<style>
	.cfs-sidebar { width: 260px; min-width: 260px; background: white; border: 1px solid #e2e8f0; border-radius: 16px; overflow-y: auto; max-height: calc(100vh - 140px); position: sticky; top: 80px; box-shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px -1px rgba(0,0,0,0.1); }
	.cfs-section { padding: 16px; border-bottom: 1px solid #f1f5f9; }
	.cfs-section:last-child { border-bottom: none; }
	.cfs-search { width: 100%; height: 38px; padding: 0 12px 0 36px; border: 1px solid #e2e8f0; border-radius: 10px; background: #f8fafc; font-size: 13px; color: var(--ii-text-primary); font-family: var(--ii-font-sans); background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%2390a1b9' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.3-4.3'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: 10px center; }
	.cfs-search::placeholder { color: #90a1b9; }
	.cfs-search:focus { outline: none; border-color: #155dfc; box-shadow: 0 0 0 3px rgba(21,93,252,0.1); }
	.cfs-group-title { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px; color: #62748e; margin-bottom: 10px; }
	.cfs-check { display: flex; align-items: center; gap: 8px; padding: 4px 0; cursor: pointer; font-size: 13px; }
	.cfs-check input[type="checkbox"] { width: 15px; height: 15px; border-radius: 4px; accent-color: #155dfc; cursor: pointer; flex-shrink: 0; }
	.cfs-check-label { flex: 1; color: #314158; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.cfs-check-count { font-size: 11px; font-variant-numeric: tabular-nums; color: #90a1b9; font-weight: 600; }
	.cfs-section--actions { border-bottom: none; }
	.cfs-clear-btn { width: 100%; padding: 8px; border: 1px solid #e2e8f0; border-radius: 10px; background: white; font-size: 13px; font-weight: 600; color: #62748e; cursor: pointer; font-family: var(--ii-font-sans); transition: all 120ms; }
	.cfs-clear-btn:hover { background: #f8fafc; color: #1d293d; }
</style>
