<!--
  eVestment-style faceted filter sidebar for the Unified Fund Catalog.
  7-category universe selector with conditional Fund Type and Strategy filters.
  Consumes GET /screener/catalog/facets.
-->
<script lang="ts">
	import "./screener.css";
	import type { CatalogFacets, CatalogFacetItem, CatalogCategory } from "$lib/types/catalog";
	import { EMPTY_FACETS, CATALOG_CATEGORIES, FUND_TYPE_LABELS } from "$lib/types/catalog";

	interface Props {
		facets: CatalogFacets;
		selectedCategories: CatalogCategory[];
		selectedFundTypes: string[];
		selectedStrategyLabels: string[];
		selectedDomiciles: string[];
		searchQ: string;
		aumMin: string;
		maxExpenseRatio: string;
		minReturn1y: string;
		minReturn10y: string;
		onFilterChange: () => void;
	}

	let {
		facets = EMPTY_FACETS,
		selectedCategories = $bindable([]),
		selectedFundTypes = $bindable([]),
		selectedStrategyLabels = $bindable([]),
		selectedDomiciles = $bindable([]),
		searchQ = $bindable(""),
		aumMin = $bindable(""),
		maxExpenseRatio = $bindable(""),
		minReturn1y = $bindable(""),
		minReturn10y = $bindable(""),
		onFilterChange,
	}: Props = $props();

	// Toggle helpers
	function toggleValue<T extends string>(arr: T[], val: T): T[] {
		return arr.includes(val) ? arr.filter((v) => v !== val) : [...arr, val];
	}

	function toggleCategory(val: CatalogCategory) {
		selectedCategories = toggleValue(selectedCategories, val);
		// Clear dependent filters when universe changes
		selectedFundTypes = [];
		selectedStrategyLabels = [];
		onFilterChange();
	}

	function toggleFundType(val: string) {
		selectedFundTypes = toggleValue(selectedFundTypes, val);
		onFilterChange();
	}

	function toggleStrategy(val: string) {
		selectedStrategyLabels = toggleValue(selectedStrategyLabels, val);
		onFilterChange();
	}

	function toggleDomicile(val: string) {
		selectedDomiciles = toggleValue(selectedDomiciles, val);
		onFilterChange();
	}

	function clearAll() {
		selectedCategories = [];
		selectedFundTypes = [];
		selectedStrategyLabels = [];
		selectedDomiciles = [];
		searchQ = "";
		aumMin = "";
		maxExpenseRatio = "";
		minReturn1y = "";
		minReturn10y = "";
		onFilterChange();
	}

	let hasActiveFilters = $derived(
		selectedCategories.length > 0 ||
		selectedFundTypes.length > 0 ||
		selectedStrategyLabels.length > 0 ||
		selectedDomiciles.length > 0 ||
		searchQ.length > 0 ||
		aumMin.length > 0 ||
		maxExpenseRatio.length > 0 ||
		minReturn1y.length > 0 ||
		minReturn10y.length > 0
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

	// Compute counts per category from facets.fund_types
	// The backend emits fund_type values that map 1:1 to categories for dedicated branches
	// (etf, bdc) and need aggregation for registered_us (mutual_fund + interval_fund → mutual_fund category)
	let categoryCounts = $derived.by(() => {
		const ftMap = new Map(facets.fund_types.map((f) => [f.value, f.count]));
		const uMap = new Map(facets.universes.map((f) => [f.value, f.count]));
		const counts: Record<string, number> = {};

		// mutual_fund: sum of mutual_fund + interval_fund
		counts.mutual_fund = (ftMap.get("mutual_fund") ?? 0) + (ftMap.get("interval_fund") ?? 0);
		counts.etf = ftMap.get("etf") ?? 0;
		counts.closed_end = ftMap.get("closed_end") ?? 0;
		counts.bdc = ftMap.get("bdc") ?? 0;

		// Private categories: use fund_type values from private_us universe
		counts.hedge_fund = ftMap.get("Hedge Fund") ?? 0;

		// private_fund = all private_us minus Hedge Fund
		const totalPrivate = uMap.get("private_us") ?? 0;
		counts.private_fund = Math.max(0, totalPrivate - counts.hedge_fund);

		// UCITS
		counts.ucits = uMap.get("ucits_eu") ?? 0;

		return counts;
	});

	// Show Fund Type filter when relevant fund_types exist for selected categories
	let showFundTypeFilter = $derived(facets.fund_types.length > 0 && selectedCategories.length > 0);

	// Show Strategy filter when strategy_labels exist
	let showStrategyFilter = $derived(facets.strategy_labels.length > 0);

	// Apply human-readable labels to fund_type facets
	function fundTypeLabel(value: string): string {
		return FUND_TYPE_LABELS[value] ?? value;
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

	<!-- Universe (7 categories) -->
	<div class="cfs-section">
		<h4 class="cfs-group-title">Universe</h4>
		{#each CATALOG_CATEGORIES as cat (cat.key)}
			{@const count = categoryCounts[cat.key] ?? 0}
			<label class="cfs-check">
				<input
					type="checkbox"
					checked={selectedCategories.includes(cat.key)}
					onchange={() => toggleCategory(cat.key)}
				/>
				<span class="cfs-check-label">{cat.label}</span>
				<span class="cfs-check-count">{count.toLocaleString()}</span>
			</label>
		{/each}
	</div>

	<!-- Fund Type (conditional — shows types from selected universes) -->
	{#if showFundTypeFilter}
		<div class="cfs-section">
			<h4 class="cfs-group-title">Fund Type</h4>
			{#each facets.fund_types as item (item.value)}
				<label class="cfs-check">
					<input
						type="checkbox"
						checked={selectedFundTypes.includes(item.value)}
						onchange={() => toggleFundType(item.value)}
					/>
					<span class="cfs-check-label">{fundTypeLabel(item.value)}</span>
					<span class="cfs-check-count">{item.count.toLocaleString()}</span>
				</label>
			{/each}
		</div>
	{/if}

	<!-- Strategy Label (conditional) -->
	{#if showStrategyFilter}
		<div class="cfs-section">
			<h4 class="cfs-group-title">Strategy</h4>
			{#each facets.strategy_labels.slice(0, 20) as item (item.value)}
				<label class="cfs-check">
					<input
						type="checkbox"
						checked={selectedStrategyLabels.includes(item.value)}
						onchange={() => toggleStrategy(item.value)}
					/>
					<span class="cfs-check-label">{item.label}</span>
					<span class="cfs-check-count">{item.count.toLocaleString()}</span>
				</label>
			{/each}
		</div>
	{/if}

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

	<!-- Cost & Performance -->
	<div class="cfs-section">
		<h4 class="cfs-group-title">Cost & Performance</h4>
		<div class="cfs-field">
			<label class="cfs-field-label" for="max-er">Max Expense Ratio</label>
			<select id="max-er" class="cfs-select" bind:value={maxExpenseRatio} onchange={() => onFilterChange()}>
				<option value="">Any</option>
				<option value="0.10">≤ 0.10%</option>
				<option value="0.25">≤ 0.25%</option>
				<option value="0.50">≤ 0.50%</option>
				<option value="0.75">≤ 0.75%</option>
				<option value="1.00">≤ 1.00%</option>
				<option value="1.50">≤ 1.50%</option>
			</select>
		</div>
		<div class="cfs-field">
			<label class="cfs-field-label" for="min-1y">Min 1Y Return</label>
			<input
				id="min-1y"
				class="cfs-input"
				type="number"
				step="0.5"
				placeholder="e.g. 5"
				bind:value={minReturn1y}
				oninput={debouncedChange}
			/>
		</div>
		<div class="cfs-field">
			<label class="cfs-field-label" for="min-10y">Min 10Y Return</label>
			<input
				id="min-10y"
				class="cfs-input"
				type="number"
				step="0.5"
				placeholder="e.g. 8"
				bind:value={minReturn10y}
				oninput={debouncedChange}
			/>
		</div>
	</div>

	<!-- Active filter chips -->
	{#if selectedFundTypes.length > 0 || selectedStrategyLabels.length > 0}
		<div class="cfs-section cfs-chips-section">
			<h4 class="cfs-group-title">Active Filters</h4>
			<div class="cfs-chip-grid">
				{#each selectedFundTypes as ft (ft)}
					<button class="cfs-chip" onclick={() => toggleFundType(ft)}>
						{fundTypeLabel(ft)}
						<span class="cfs-chip-x">&times;</span>
					</button>
				{/each}
				{#each selectedStrategyLabels as sl (sl)}
					<button class="cfs-chip" onclick={() => toggleStrategy(sl)}>
						{sl}
						<span class="cfs-chip-x">&times;</span>
					</button>
				{/each}
			</div>
		</div>
	{/if}

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
		color: var(--ii-text-primary);
		font-family: var(--ii-font-sans);
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
		color: var(--ii-text-primary);
		font-family: var(--ii-font-sans);
	}

	.cfs-select:focus { outline: none; border-color: #155dfc; }

	.cfs-field {
		margin-bottom: 10px;
	}

	.cfs-field-label {
		display: block;
		font-size: 12px;
		font-weight: 500;
		color: #62748e;
		margin-bottom: 4px;
	}

	.cfs-input {
		width: 100%;
		height: 36px;
		padding: 0 10px;
		border: 1px solid #e2e8f0;
		border-radius: 10px;
		background: #f8fafc;
		font-size: 13px;
		color: var(--ii-text-primary);
		font-family: var(--ii-font-sans);
	}

	.cfs-input:focus { outline: none; border-color: #155dfc; box-shadow: 0 0 0 3px rgba(21,93,252,0.1); }

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
		font-family: var(--ii-font-sans);
		transition: all 120ms;
	}

	.cfs-clear-btn:hover {
		background: #f8fafc;
		color: #1d293d;
	}

	/* ── Chip grid ── */
	.cfs-chips-section {
		padding-bottom: 8px;
	}

	.cfs-chip-grid {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.cfs-chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 3px 10px;
		border: 1px solid var(--ii-border-subtle, #e2e8f0);
		border-radius: 100px;
		background: color-mix(in srgb, #155dfc 8%, transparent);
		border-color: #155dfc;
		color: #155dfc;
		font-size: 11px;
		font-weight: 600;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		transition: all 120ms ease;
	}

	.cfs-chip:hover {
		background: color-mix(in srgb, #155dfc 16%, transparent);
	}

	.cfs-chip-x {
		font-size: 14px;
		line-height: 1;
		opacity: 0.7;
	}

	.cfs-chip-x:hover {
		opacity: 1;
	}
</style>
