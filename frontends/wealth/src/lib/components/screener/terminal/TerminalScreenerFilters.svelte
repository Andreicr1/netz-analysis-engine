<!--
  TerminalScreenerFilters — left panel, collapsible sections.

  Drives the `/screener/catalog` backend query directly. Every option
  here maps 1:1 to a backend query parameter — the filtering happens
  server-side on the TimescaleDB-backed materialized view.
-->
<script module lang="ts">
	export interface FilterState {
		fundUniverse: Set<string>;   // fund_universe: mutual_fund,etf,closed_end,bdc,money_market,hedge_fund,private_fund,ucits
		strategies: Set<string>;     // strategy_label
		geographies: Set<string>;    // investment_geography
		aumMin: number;              // USD absolute, 0 = no filter
		returnMin: number;           // % annualised 1Y, null/-999 = no filter
		expenseMax: number;          // % annual fee, 10 = no filter
		eliteOnly: boolean;          // ELITE-flagged funds only
		managerNames: string[];      // multi-select exact manager names
	}

	export const DEFAULT_FILTERS: FilterState = {
		fundUniverse: new Set<string>(),
		strategies: new Set<string>(),
		geographies: new Set<string>(),
		aumMin: 0,
		returnMin: -999,
		expenseMax: 10,
		eliteOnly: false,
		managerNames: [],
	};
</script>

<script lang="ts">
	import { getContext } from "svelte";
	import { formatNumber } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	interface Props {
		filters: FilterState;
		onFiltersChange: (filters: FilterState) => void;
	}

	let { filters, onFiltersChange }: Props = $props();

	// ── Manager typeahead ────────────────────────────────
	let managerQuery = $state("");
	let managerSuggestions = $state<string[]>([]);
	let managerDebounce: ReturnType<typeof setTimeout> | null = null;

	function fetchManagerSuggestions() {
		if (managerDebounce) clearTimeout(managerDebounce);
		if (managerQuery.length < 2) {
			managerSuggestions = [];
			return;
		}
		managerDebounce = setTimeout(async () => {
			try {
				const results = await api.get<string[]>("/screener/managers", {
					q: managerQuery,
					limit: "10",
				});
				// Exclude already-selected managers
				managerSuggestions = results.filter(
					(n) => !filters.managerNames.includes(n),
				);
			} catch {
				managerSuggestions = [];
			}
		}, 200);
	}

	function addManager(name: string) {
		if (!filters.managerNames.includes(name)) {
			onFiltersChange({
				...filters,
				managerNames: [...filters.managerNames, name],
			});
		}
		managerQuery = "";
		managerSuggestions = [];
	}

	function removeManager(name: string) {
		onFiltersChange({
			...filters,
			managerNames: filters.managerNames.filter((n) => n !== name),
		});
	}

	// Universe labels mirror the CatalogFilters backend contract.
	const FUND_UNIVERSE: { key: string; label: string }[] = [
		{ key: "mutual_fund",  label: "Mutual Fund" },
		{ key: "etf",          label: "ETF" },
		{ key: "closed_end",   label: "Closed-End" },
		{ key: "interval_fund",label: "Interval" },
		{ key: "bdc",          label: "BDC" },
		{ key: "money_market", label: "Money Market" },
		{ key: "hedge_fund",   label: "Hedge Fund" },
		{ key: "private_fund", label: "Private Fund" },
		{ key: "ucits",        label: "UCITS (EU)" },
	];

	// Subset of the most common strategy_label values — the full list is
	// ~37 categories, we surface the ones that matter most to asset
	// allocators first.
	const STRATEGIES = [
		"Equity",
		"Fixed Income",
		"Multi-Asset",
		"Money Market",
		"Alternatives",
		"Real Estate",
		"Commodities",
		"Private Credit",
		"Infrastructure",
		"Long/Short Equity",
		"Buyout",
		"Venture Capital",
	];

	const GEOGRAPHIES = [
		"US",
		"Europe",
		"Emerging Markets",
		"Asia Pacific",
		"Global",
		"Latin America",
	];

	let sectionOpen = $state({ manager: true, universe: true, strategy: true, geography: true, metrics: true });

	function toggleUniverse(key: string) {
		const next = new Set(filters.fundUniverse);
		if (next.has(key)) next.delete(key);
		else next.add(key);
		onFiltersChange({ ...filters, fundUniverse: next });
	}

	function toggleStrategy(key: string) {
		const next = new Set(filters.strategies);
		if (next.has(key)) next.delete(key);
		else next.add(key);
		onFiltersChange({ ...filters, strategies: next });
	}

	function toggleGeography(key: string) {
		const next = new Set(filters.geographies);
		if (next.has(key)) next.delete(key);
		else next.add(key);
		onFiltersChange({ ...filters, geographies: next });
	}

	function setRange<K extends "aumMin" | "returnMin" | "expenseMax">(field: K, value: number) {
		onFiltersChange({ ...filters, [field]: value });
	}

	function toggleEliteOnly() {
		onFiltersChange({ ...filters, eliteOnly: !filters.eliteOnly });
	}

	function clearAll() {
		managerQuery = "";
		managerSuggestions = [];
		onFiltersChange({
			fundUniverse: new Set(),
			strategies: new Set(),
			geographies: new Set(),
			aumMin: 0,
			returnMin: -999,
			expenseMax: 10,
			eliteOnly: false,
			managerNames: [],
		});
	}

	// AUM slider uses log10 ticks: 0 → $0, 6 → $1M, 9 → $1B, 12 → $1T.
	function aumToLog(n: number): number {
		if (n <= 0) return 0;
		return Math.log10(Math.max(1, n));
	}
	function logToAum(l: number): number {
		if (l <= 0) return 0;
		return Math.pow(10, l);
	}
	function fmtAum(n: number): string {
		if (n <= 0) return "any";
		if (n >= 1e12) return "$" + formatNumber(n / 1e12, 1) + "T";
		if (n >= 1e9) return "$" + formatNumber(n / 1e9, 1) + "B";
		if (n >= 1e6) return "$" + formatNumber(n / 1e6, 0) + "M";
		return "$" + formatNumber(n, 0);
	}

	const aumLogValue = $derived(aumToLog(filters.aumMin));
</script>

<div class="sf-root">
	<div class="sf-header">
		<span class="sf-title">FILTERS</span>
		<button class="sf-clear" onclick={clearAll}>Clear</button>
	</div>

	<div class="sf-elite-chip-row">
		<button
			class="sf-elite-chip"
			class:sf-elite-chip--active={filters.eliteOnly}
			onclick={toggleEliteOnly}
		>
			ELITE
		</button>
	</div>

	<div class="sf-scroll">
		<!-- Manager typeahead -->
		<div class="sf-section">
			<button
				class="sf-section-toggle"
				onclick={() => (sectionOpen.manager = !sectionOpen.manager)}
			>
				<span class="sf-section-arrow" class:open={sectionOpen.manager}>&#9656;</span>
				MANAGER
			</button>
			{#if sectionOpen.manager}
				<div class="sf-section-body">
					<div class="sf-manager-typeahead">
						<input
							type="text"
							class="sf-manager-input"
							placeholder="Search managers..."
							bind:value={managerQuery}
							oninput={fetchManagerSuggestions}
						/>
						{#if managerSuggestions.length > 0}
							<ul class="sf-manager-suggestions" role="listbox">
								{#each managerSuggestions as name (name)}
									<li
										role="option"
										class="sf-manager-suggestion"
										onclick={() => addManager(name)}
									>
										{name}
									</li>
								{/each}
							</ul>
						{/if}
						{#if filters.managerNames.length > 0}
							<div class="sf-manager-chips">
								{#each filters.managerNames as name (name)}
									<span class="sf-manager-chip">
										{name}
										<button
											class="sf-manager-chip-x"
											onclick={() => removeManager(name)}
											aria-label="Remove {name}"
										>x</button>
									</span>
								{/each}
							</div>
						{/if}
					</div>
				</div>
			{/if}
		</div>

		<!-- Universe -->
		<div class="sf-section">
			<button
				class="sf-section-toggle"
				onclick={() => (sectionOpen.universe = !sectionOpen.universe)}
			>
				<span class="sf-section-arrow" class:open={sectionOpen.universe}>&#9656;</span>
				UNIVERSE
			</button>
			{#if sectionOpen.universe}
				<div class="sf-section-body">
					<div class="sf-check-grid">
						{#each FUND_UNIVERSE as u}
							<label class="sf-check">
								<input
									type="checkbox"
									checked={filters.fundUniverse.has(u.key)}
									onchange={() => toggleUniverse(u.key)}
								/>
								<span class="sf-check-label">{u.label}</span>
							</label>
						{/each}
					</div>
				</div>
			{/if}
		</div>

		<!-- Strategy -->
		<div class="sf-section">
			<button
				class="sf-section-toggle"
				onclick={() => (sectionOpen.strategy = !sectionOpen.strategy)}
			>
				<span class="sf-section-arrow" class:open={sectionOpen.strategy}>&#9656;</span>
				STRATEGY
			</button>
			{#if sectionOpen.strategy}
				<div class="sf-section-body">
					<div class="sf-check-grid">
						{#each STRATEGIES as s}
							<label class="sf-check">
								<input
									type="checkbox"
									checked={filters.strategies.has(s)}
									onchange={() => toggleStrategy(s)}
								/>
								<span class="sf-check-label">{s}</span>
							</label>
						{/each}
					</div>
				</div>
			{/if}
		</div>

		<!-- Geography -->
		<div class="sf-section">
			<button
				class="sf-section-toggle"
				onclick={() => (sectionOpen.geography = !sectionOpen.geography)}
			>
				<span class="sf-section-arrow" class:open={sectionOpen.geography}>&#9656;</span>
				GEOGRAPHY
			</button>
			{#if sectionOpen.geography}
				<div class="sf-section-body">
					<div class="sf-check-grid">
						{#each GEOGRAPHIES as g}
							<label class="sf-check">
								<input
									type="checkbox"
									checked={filters.geographies.has(g)}
									onchange={() => toggleGeography(g)}
								/>
								<span class="sf-check-label">{g}</span>
							</label>
						{/each}
					</div>
				</div>
			{/if}
		</div>

		<!-- Metrics -->
		<div class="sf-section">
			<button
				class="sf-section-toggle"
				onclick={() => (sectionOpen.metrics = !sectionOpen.metrics)}
			>
				<span class="sf-section-arrow" class:open={sectionOpen.metrics}>&#9656;</span>
				METRICS
			</button>
			{#if sectionOpen.metrics}
				<div class="sf-section-body">
					<div class="sf-range-group">
						<div class="sf-range-header">
							<span>Min AUM</span>
							<span class="sf-range-value">{fmtAum(filters.aumMin)}</span>
						</div>
						<input
							type="range"
							min={0}
							max={12}
							step={0.1}
							value={aumLogValue}
							oninput={(e) => setRange("aumMin", logToAum(+e.currentTarget.value))}
							class="sf-slider"
						/>
					</div>

					<div class="sf-range-group">
						<div class="sf-range-header">
							<span>Min 1Y Return (%)</span>
							<span class="sf-range-value">
								{filters.returnMin <= -999 ? "any" : formatNumber(filters.returnMin, 0) + "%"}
							</span>
						</div>
						<input
							type="range"
							min={-50}
							max={100}
							step={1}
							value={filters.returnMin <= -999 ? -50 : filters.returnMin}
							oninput={(e) => setRange("returnMin", +e.currentTarget.value)}
							class="sf-slider"
						/>
					</div>

					<div class="sf-range-group">
						<div class="sf-range-header">
							<span>Max Expense Ratio (%)</span>
							<span class="sf-range-value">{formatNumber(filters.expenseMax, 2)}%</span>
						</div>
						<input
							type="range"
							min={0}
							max={10}
							step={0.05}
							value={filters.expenseMax}
							oninput={(e) => setRange("expenseMax", +e.currentTarget.value)}
							class="sf-slider"
						/>
					</div>
				</div>
			{/if}
		</div>
	</div>
</div>

<style>
	.sf-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: #0c1018;
		border-right: 1px solid rgba(255, 255, 255, 0.06);
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		color: #c8d0dc;
	}

	.sf-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 12px 8px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
		flex-shrink: 0;
	}

	.sf-title {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.1em;
		color: #5a6577;
		text-transform: uppercase;
	}

	.sf-clear {
		font-size: 10px;
		color: #2d7ef7;
		background: none;
		border: none;
		cursor: pointer;
		padding: 0;
		font-family: inherit;
	}
	.sf-clear:hover {
		color: #5a9ef7;
	}

	.sf-elite-chip-row {
		padding: 8px 12px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
		flex-shrink: 0;
	}

	.sf-elite-chip {
		font-family: "JetBrains Mono", monospace;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		padding: 4px 12px;
		background: transparent;
		border: 1px solid rgba(255, 255, 255, 0.12);
		color: #8a94a6;
		cursor: pointer;
		transition: all 80ms ease;
	}
	.sf-elite-chip:hover {
		border-color: #f59e0b;
		color: #f59e0b;
	}
	.sf-elite-chip--active {
		border-color: #f59e0b;
		color: #f59e0b;
		background: rgba(245, 158, 11, 0.08);
	}

	.sf-scroll {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
		min-height: 0;
	}

	.sf-section {
		border-bottom: 1px solid rgba(255, 255, 255, 0.04);
	}

	.sf-section-toggle {
		display: flex;
		align-items: center;
		gap: 6px;
		width: 100%;
		padding: 8px 12px;
		background: none;
		border: none;
		color: #8a94a6;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		cursor: pointer;
		font-family: inherit;
		text-align: left;
	}
	.sf-section-toggle:hover {
		color: #c8d0dc;
	}

	.sf-section-arrow {
		font-size: 9px;
		transition: transform 120ms ease;
		display: inline-block;
	}
	.sf-section-arrow.open {
		transform: rotate(90deg);
	}

	.sf-section-body {
		padding: 0 12px 10px;
	}

	.sf-check-grid {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.sf-check {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 2px 0;
		cursor: pointer;
	}
	.sf-check input[type="checkbox"] {
		width: 12px;
		height: 12px;
		accent-color: #2d7ef7;
		margin: 0;
		flex-shrink: 0;
	}

	.sf-check-label {
		font-size: 11px;
		color: #9aa3b3;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* ── Manager typeahead ────────────────────────────── */
	.sf-manager-typeahead {
		position: relative;
	}

	.sf-manager-input {
		width: 100%;
		background: transparent;
		border: 1px solid rgba(255, 255, 255, 0.08);
		border-radius: 0;
		color: #c8d0dc;
		font-family: "JetBrains Mono", monospace;
		font-size: 11px;
		padding: 5px 8px;
		outline: none;
		box-sizing: border-box;
	}
	.sf-manager-input::placeholder {
		color: #3d4a5c;
	}
	.sf-manager-input:focus {
		border-color: rgba(45, 126, 247, 0.4);
	}

	.sf-manager-suggestions {
		position: absolute;
		left: 0;
		right: 0;
		z-index: 20;
		background: #0d1220;
		border: 1px solid rgba(255, 255, 255, 0.08);
		border-top: none;
		list-style: none;
		margin: 0;
		padding: 0;
		max-height: 200px;
		overflow-y: auto;
	}

	.sf-manager-suggestion {
		padding: 5px 8px;
		font-size: 11px;
		color: #9aa3b3;
		cursor: pointer;
	}
	.sf-manager-suggestion:hover {
		background: rgba(45, 126, 247, 0.08);
		color: #e2e8f0;
	}

	.sf-manager-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-top: 6px;
	}

	.sf-manager-chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-family: "JetBrains Mono", monospace;
		font-size: 10px;
		color: #22d3ee;
		border: 1px solid rgba(34, 211, 238, 0.3);
		padding: 2px 6px;
		white-space: nowrap;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.sf-manager-chip-x {
		background: none;
		border: none;
		color: #22d3ee;
		font-size: 10px;
		cursor: pointer;
		padding: 0;
		line-height: 1;
		font-family: "JetBrains Mono", monospace;
		opacity: 0.6;
	}
	.sf-manager-chip-x:hover {
		opacity: 1;
	}

	/* ── Range sliders ─────────────────────────────────── */
	.sf-range-group {
		margin-bottom: 10px;
	}

	.sf-range-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 4px;
		color: #8a94a6;
		font-size: 10px;
	}

	.sf-range-value {
		color: #c8d0dc;
		font-variant-numeric: tabular-nums;
	}

	.sf-slider {
		width: 100%;
		-webkit-appearance: none;
		appearance: none;
		height: 3px;
		background: #1e293b;
		border-radius: 2px;
		outline: none;
	}
	.sf-slider::-webkit-slider-thumb {
		-webkit-appearance: none;
		appearance: none;
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: #2d7ef7;
		cursor: pointer;
		border: none;
	}
	.sf-slider::-moz-range-thumb {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: #2d7ef7;
		cursor: pointer;
		border: none;
	}
</style>
