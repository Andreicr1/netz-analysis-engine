<!--
  eVestment-style faceted filter sidebar for the Unified Fund Catalog.
  Hierarchical tree: Universes > Regions > Fund Types > Domiciles.
  Consumes GET /screener/catalog/facets.
-->
<script lang="ts">
	import "./screener.css";
	import type { CatalogFacets, CatalogFacetItem } from "$lib/types/catalog";
	import { EMPTY_FACETS, UNIVERSE_LABELS } from "$lib/types/catalog";

	interface Props {
		facets: CatalogFacets;
		selectedUniverses: string[];
		selectedRegions: string[];
		selectedFundTypes: string[];
		selectedDomiciles: string[];
		searchQ: string;
		aumMin: string;
		onFilterChange: () => void;
	}

	let {
		facets = EMPTY_FACETS,
		selectedUniverses = $bindable([]),
		selectedRegions = $bindable([]),
		selectedFundTypes = $bindable([]),
		selectedDomiciles = $bindable([]),
		searchQ = $bindable(""),
		aumMin = $bindable(""),
		onFilterChange,
	}: Props = $props();

	// Toggle helpers
	function toggleValue(arr: string[], val: string): string[] {
		return arr.includes(val) ? arr.filter((v) => v !== val) : [...arr, val];
	}

	function toggleUniverse(val: string) {
		selectedUniverses = toggleValue(selectedUniverses, val);
		onFilterChange();
	}

	function toggleRegion(val: string) {
		selectedRegions = toggleValue(selectedRegions, val);
		onFilterChange();
	}

	function toggleFundType(val: string) {
		selectedFundTypes = toggleValue(selectedFundTypes, val);
		onFilterChange();
	}

	function toggleDomicile(val: string) {
		selectedDomiciles = toggleValue(selectedDomiciles, val);
		onFilterChange();
	}

	function clearAll() {
		selectedUniverses = [];
		selectedRegions = [];
		selectedFundTypes = [];
		selectedDomiciles = [];
		searchQ = "";
		aumMin = "";
		onFilterChange();
	}

	let hasActiveFilters = $derived(
		selectedUniverses.length > 0 ||
		selectedRegions.length > 0 ||
		selectedFundTypes.length > 0 ||
		selectedDomiciles.length > 0 ||
		searchQ.length > 0 ||
		aumMin.length > 0
	);

	// Debounce for text inputs
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;
	function debouncedChange() {
		if (debounceTimer) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => onFilterChange(), 400);
	}

	function handleSearchKeydown(e: KeyboardEvent) {
		if (e.key === "Enter") {
			if (debounceTimer) clearTimeout(debounceTimer);
			onFilterChange();
		}
	}
</script>

<aside class="cfs-sidebar">
	<!-- Search -->
	<div class="cfs-section">
		<input
			class="cfs-search"
			type="text"
			placeholder="Search funds, managers..."
			bind:value={searchQ}
			oninput={debouncedChange}
			onkeydown={handleSearchKeydown}
		/>
	</div>

	<!-- Universe -->
	<div class="cfs-section">
		<h4 class="cfs-group-title">Universe</h4>
		{#each facets.universes as item (item.value)}
			<label class="cfs-check">
				<input
					type="checkbox"
					checked={selectedUniverses.includes(item.value)}
					onchange={() => toggleUniverse(item.value)}
				/>
				<span class="cfs-check-label">{item.label}</span>
				<span class="cfs-check-count">{item.count.toLocaleString()}</span>
			</label>
		{/each}
	</div>

	<!-- Region -->
	<div class="cfs-section">
		<h4 class="cfs-group-title">Region</h4>
		{#each facets.regions as item (item.value)}
			<label class="cfs-check">
				<input
					type="checkbox"
					checked={selectedRegions.includes(item.value)}
					onchange={() => toggleRegion(item.value)}
				/>
				<span class="cfs-check-label">{item.label}</span>
				<span class="cfs-check-count">{item.count.toLocaleString()}</span>
			</label>
		{/each}
	</div>

	<!-- Fund Type -->
	<div class="cfs-section">
		<h4 class="cfs-group-title">Fund Type</h4>
		{#each facets.fund_types as item (item.value)}
			<label class="cfs-check">
				<input
					type="checkbox"
					checked={selectedFundTypes.includes(item.value)}
					onchange={() => toggleFundType(item.value)}
				/>
				<span class="cfs-check-label">{item.label}</span>
				<span class="cfs-check-count">{item.count.toLocaleString()}</span>
			</label>
		{/each}
	</div>

	<!-- Domicile -->
	{#if facets.domiciles.length > 0}
		<div class="cfs-section">
			<h4 class="cfs-group-title">Domicile</h4>
			{#each facets.domiciles.slice(0, 15) as item (item.value)}
				<label class="cfs-check">
					<input
						type="checkbox"
						checked={selectedDomiciles.includes(item.value)}
						onchange={() => toggleDomicile(item.value)}
					/>
					<span class="cfs-check-label">{item.label}</span>
					<span class="cfs-check-count">{item.count.toLocaleString()}</span>
				</label>
			{/each}
		</div>
	{/if}

	<!-- AUM Min -->
	<div class="cfs-section">
		<h4 class="cfs-group-title">AUM Minimum</h4>
		<select class="cfs-select" bind:value={aumMin} onchange={() => onFilterChange()}>
			<option value="">Any</option>
			<option value="100000000">$100M+</option>
			<option value="500000000">$500M+</option>
			<option value="1000000000">$1B+</option>
			<option value="5000000000">$5B+</option>
			<option value="10000000000">$10B+</option>
			<option value="50000000000">$50B+</option>
		</select>
	</div>

	<!-- Clear -->
	{#if hasActiveFilters}
		<div class="cfs-section cfs-section--actions">
			<button class="cfs-clear-btn" onclick={clearAll}>Clear All Filters</button>
		</div>
	{/if}
</aside>

<style>
	.cfs-sidebar {
		width: 260px;
		min-width: 260px;
		background: white;
		border: 1px solid #e2e8f0;
		border-radius: 16px;
		overflow-y: auto;
		max-height: calc(100vh - 140px);
		position: sticky;
		top: 80px;
		box-shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px -1px rgba(0,0,0,0.1);
	}

	.cfs-section {
		padding: 16px;
		border-bottom: 1px solid #f1f5f9;
	}

	.cfs-section:last-child {
		border-bottom: none;
	}

	.cfs-search {
		width: 100%;
		height: 38px;
		padding: 0 12px 0 36px;
		border: 1px solid #e2e8f0;
		border-radius: 10px;
		background: #f8fafc;
		font-size: 13px;
		color: var(--netz-text-primary);
		font-family: var(--netz-font-sans);
		background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%2390a1b9' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.3-4.3'/%3E%3C/svg%3E");
		background-repeat: no-repeat;
		background-position: 10px center;
	}

	.cfs-search::placeholder { color: #90a1b9; }
	.cfs-search:focus { outline: none; border-color: #155dfc; box-shadow: 0 0 0 3px rgba(21,93,252,0.1); }

	.cfs-group-title {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 1.2px;
		color: #62748e;
		margin-bottom: 10px;
	}

	.cfs-check {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 4px 0;
		cursor: pointer;
		font-size: 13px;
	}

	.cfs-check input[type="checkbox"] {
		width: 15px;
		height: 15px;
		border-radius: 4px;
		accent-color: #155dfc;
		cursor: pointer;
		flex-shrink: 0;
	}

	.cfs-check-label {
		flex: 1;
		color: #314158;
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.cfs-check-count {
		font-size: 11px;
		font-variant-numeric: tabular-nums;
		color: #90a1b9;
		font-weight: 600;
	}

	.cfs-select {
		width: 100%;
		height: 36px;
		padding: 0 10px;
		border: 1px solid #e2e8f0;
		border-radius: 10px;
		background: #f8fafc;
		font-size: 13px;
		color: var(--netz-text-primary);
		font-family: var(--netz-font-sans);
	}

	.cfs-select:focus { outline: none; border-color: #155dfc; }

	.cfs-section--actions { border-bottom: none; }

	.cfs-clear-btn {
		width: 100%;
		padding: 8px;
		border: 1px solid #e2e8f0;
		border-radius: 10px;
		background: white;
		font-size: 13px;
		font-weight: 600;
		color: #62748e;
		cursor: pointer;
		font-family: var(--netz-font-sans);
		transition: all 120ms;
	}

	.cfs-clear-btn:hover {
		background: #f8fafc;
		color: #1d293d;
	}
</style>
