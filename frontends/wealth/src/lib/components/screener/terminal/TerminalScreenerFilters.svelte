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
	}

	export const DEFAULT_FILTERS: FilterState = {
		fundUniverse: new Set<string>(),
		strategies: new Set<string>(),
		geographies: new Set<string>(),
		aumMin: 0,
		returnMin: -999,
		expenseMax: 10,
		eliteOnly: false,
	};
</script>

<script lang="ts">
	import { formatNumber } from "@investintell/ui";

	interface Props {
		filters: FilterState;
		onFiltersChange: (filters: FilterState) => void;
	}

	let { filters, onFiltersChange }: Props = $props();

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

	let sectionOpen = $state({ universe: true, strategy: true, geography: true, metrics: true });

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
		onFiltersChange({
			fundUniverse: new Set(),
			strategies: new Set(),
			geographies: new Set(),
			aumMin: 0,
			returnMin: -999,
			expenseMax: 10,
			eliteOnly: false,
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
