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
		aumMax: number;              // USD absolute, 0 = no filter
		returnMin: number;           // % annualised 1Y, null/-999 = no filter
		returnMax: number;           // % annualised 1Y, 999 = no filter
		expenseMax: number;          // % annual fee, 10 = no filter
		eliteOnly: boolean;          // ELITE-flagged funds only
		managerNames: string[];      // multi-select exact manager names
		sharpeMin: string;           // Sharpe ratio (1Y) min — string for input binding
		sharpeMax: string;
		drawdownMinPct: string;      // Positive %, converted to negative for backend
		drawdownMaxPct: string;
		volatilityMax: string;       // Annualized vol (1Y)
		return10yMin: string;        // % annualised 10Y
		return10yMax: string;
	}

	export const DEFAULT_FILTERS: FilterState = {
		fundUniverse: new Set<string>(),
		strategies: new Set<string>(),
		geographies: new Set<string>(),
		aumMin: 0,
		aumMax: 0,
		returnMin: -999,
		returnMax: 999,
		expenseMax: 10,
		eliteOnly: false,
		managerNames: [],
		sharpeMin: "",
		sharpeMax: "",
		drawdownMinPct: "",
		drawdownMaxPct: "",
		volatilityMax: "",
		return10yMin: "",
		return10yMax: "",
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

	let sectionOpen = $state({ manager: false, universe: false, strategy: false, geography: false, metrics: false });

	// Active filter counts for collapsed section badges
	const activeManagerCount = $derived(filters.managerNames.length);
	const activeUniverseCount = $derived(filters.fundUniverse.size);
	const activeStrategyCount = $derived(filters.strategies.size);
	const activeGeographyCount = $derived(filters.geographies.size);
	const activeMetricsCount = $derived(
		(filters.aumMin > 0 ? 1 : 0) +
		(filters.aumMax > 0 ? 1 : 0) +
		(filters.sharpeMin !== "" ? 1 : 0) +
		(filters.sharpeMax !== "" ? 1 : 0) +
		(filters.drawdownMinPct !== "" ? 1 : 0) +
		(filters.drawdownMaxPct !== "" ? 1 : 0) +
		(filters.volatilityMax !== "" ? 1 : 0) +
		(filters.expenseMax < 10 ? 1 : 0) +
		(filters.returnMin > -999 ? 1 : 0) +
		(filters.returnMax < 999 ? 1 : 0) +
		(filters.return10yMin !== "" ? 1 : 0) +
		(filters.return10yMax !== "" ? 1 : 0)
	);

	function expandAll() {
		sectionOpen = { manager: true, universe: true, strategy: true, geography: true, metrics: true };
	}
	function collapseAll() {
		sectionOpen = { manager: false, universe: false, strategy: false, geography: false, metrics: false };
	}

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

	function setRange<K extends "aumMin" | "aumMax" | "returnMin" | "returnMax" | "expenseMax">(field: K, value: number) {
		onFiltersChange({ ...filters, [field]: value });
	}

	function toggleEliteOnly() {
		onFiltersChange({ ...filters, eliteOnly: !filters.eliteOnly });
	}

	// ── Debounced metric input handler ────────────────────
	type MetricKey = "sharpeMin" | "sharpeMax" | "drawdownMinPct" | "drawdownMaxPct" | "volatilityMax" | "return10yMin" | "return10yMax";
	let metricDebounce: ReturnType<typeof setTimeout> | null = null;

	function debouncedMetric(field: MetricKey, value: string) {
		if (metricDebounce) clearTimeout(metricDebounce);
		metricDebounce = setTimeout(() => {
			onFiltersChange({ ...filters, [field]: value });
		}, 500);
	}

	function clearAll() {
		managerQuery = "";
		managerSuggestions = [];
		onFiltersChange({
			fundUniverse: new Set(),
			strategies: new Set(),
			geographies: new Set(),
			aumMin: 0,
			aumMax: 0,
			returnMin: -999,
			returnMax: 999,
			expenseMax: 10,
			eliteOnly: false,
			managerNames: [],
			sharpeMin: "",
			sharpeMax: "",
			drawdownMinPct: "",
			drawdownMaxPct: "",
			volatilityMax: "",
			return10yMin: "",
			return10yMax: "",
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
		<div class="sf-header-actions">
			<button class="sf-action" onclick={expandAll} title="Expand all sections">ALL</button>
			<button class="sf-action" onclick={collapseAll} title="Collapse all sections">NONE</button>
			<button class="sf-clear" onclick={clearAll}>Clear</button>
		</div>
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
				{#if activeManagerCount > 0}<span class="sf-active-count">{activeManagerCount}</span>{/if}
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
				{#if activeUniverseCount > 0}<span class="sf-active-count">{activeUniverseCount}</span>{/if}
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
				{#if activeStrategyCount > 0}<span class="sf-active-count">{activeStrategyCount}</span>{/if}
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
				{#if activeGeographyCount > 0}<span class="sf-active-count">{activeGeographyCount}</span>{/if}
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
				{#if activeMetricsCount > 0}<span class="sf-active-count">{activeMetricsCount}</span>{/if}
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

					<div class="sf-metric-row">
						<span class="sf-metric-label">SHARPE (1Y)</span>
						<div class="sf-metric-inputs">
							<input type="number" step="0.1" placeholder="min" class="sf-metric-input" value={filters.sharpeMin}
								oninput={(e) => debouncedMetric("sharpeMin", e.currentTarget.value)} />
							<span class="sf-metric-sep">&mdash;</span>
							<input type="number" step="0.1" placeholder="max" class="sf-metric-input" value={filters.sharpeMax}
								oninput={(e) => debouncedMetric("sharpeMax", e.currentTarget.value)} />
						</div>
					</div>

					<div class="sf-metric-row">
						<span class="sf-metric-label">MAX DRAWDOWN (%)</span>
						<div class="sf-metric-inputs">
							<input type="number" step="1" placeholder="min" class="sf-metric-input" value={filters.drawdownMinPct}
								oninput={(e) => debouncedMetric("drawdownMinPct", e.currentTarget.value)} />
							<span class="sf-metric-sep">&mdash;</span>
							<input type="number" step="1" placeholder="max" class="sf-metric-input" value={filters.drawdownMaxPct}
								oninput={(e) => debouncedMetric("drawdownMaxPct", e.currentTarget.value)} />
						</div>
					</div>

					<div class="sf-metric-row">
						<span class="sf-metric-label">VOLATILITY (MAX)</span>
						<div class="sf-metric-inputs">
							<input type="number" step="0.01" placeholder="max" class="sf-metric-input" value={filters.volatilityMax}
								oninput={(e) => debouncedMetric("volatilityMax", e.currentTarget.value)} />
						</div>
					</div>

					<div class="sf-metric-row">
						<span class="sf-metric-label">EXPENSE RATIO (MAX %)</span>
						<div class="sf-metric-inputs">
							<input type="number" step="0.05" placeholder="max" class="sf-metric-input"
								value={filters.expenseMax >= 10 ? "" : String(filters.expenseMax)}
								oninput={(e) => {
									const v = e.currentTarget.value;
									setRange("expenseMax", v === "" ? 10 : +v);
								}} />
						</div>
					</div>

					<div class="sf-metric-row">
						<span class="sf-metric-label">1Y RETURN (%)</span>
						<div class="sf-metric-inputs">
							<input type="number" step="1" placeholder="min" class="sf-metric-input"
								value={filters.returnMin <= -999 ? "" : String(filters.returnMin)}
								oninput={(e) => {
									const v = e.currentTarget.value;
									setRange("returnMin", v === "" ? -999 : +v);
								}} />
							<span class="sf-metric-sep">&mdash;</span>
							<input type="number" step="1" placeholder="max" class="sf-metric-input"
								value={filters.returnMax >= 999 ? "" : String(filters.returnMax)}
								oninput={(e) => {
									const v = e.currentTarget.value;
									setRange("returnMax", v === "" ? 999 : +v);
								}} />
						</div>
					</div>

					<div class="sf-metric-row">
						<span class="sf-metric-label">10Y RETURN (%)</span>
						<div class="sf-metric-inputs">
							<input type="number" step="1" placeholder="min" class="sf-metric-input" value={filters.return10yMin}
								oninput={(e) => debouncedMetric("return10yMin", e.currentTarget.value)} />
							<span class="sf-metric-sep">&mdash;</span>
							<input type="number" step="1" placeholder="max" class="sf-metric-input" value={filters.return10yMax}
								oninput={(e) => debouncedMetric("return10yMax", e.currentTarget.value)} />
						</div>
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
		background: var(--terminal-bg-panel);
		border-right: 1px solid var(--terminal-fg-muted);
		font-family: var(--terminal-font-mono);
		font-size: 11px;
		color: var(--terminal-fg-primary);
	}

	.sf-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 12px 8px;
		border-bottom: 1px solid var(--terminal-fg-muted);
		flex-shrink: 0;
	}

	.sf-title {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.1em;
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}

	.sf-header-actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.sf-action {
		font-size: 9px;
		color: var(--terminal-fg-tertiary);
		background: none;
		border: none;
		cursor: pointer;
		padding: 0;
		font-family: var(--terminal-font-mono);
		letter-spacing: 0.06em;
		text-transform: uppercase;
	}
	.sf-action:hover {
		color: var(--terminal-fg-secondary);
	}

	.sf-clear {
		font-size: 10px;
		color: var(--terminal-accent-cyan);
		background: none;
		border: none;
		cursor: pointer;
		padding: 0;
		font-family: inherit;
	}
	.sf-clear:hover {
		color: var(--terminal-accent-cyan);
	}

	.sf-elite-chip-row {
		padding: 8px 12px;
		border-bottom: 1px solid var(--terminal-fg-muted);
		flex-shrink: 0;
	}

	.sf-elite-chip {
		font-family: var(--terminal-font-mono);
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		padding: 4px 12px;
		background: transparent;
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-secondary);
		cursor: pointer;
		transition: all 80ms ease;
	}
	.sf-elite-chip:hover {
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
	}
	.sf-elite-chip--active {
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
		background: color-mix(in srgb, var(--terminal-accent-amber) 8%, transparent);
	}

	.sf-scroll {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
		min-height: 0;
	}

	.sf-section {
		border-bottom: 1px solid var(--terminal-fg-disabled);
	}

	.sf-section-toggle {
		display: flex;
		align-items: center;
		gap: 6px;
		width: 100%;
		padding: 8px 12px;
		background: none;
		border: none;
		color: var(--terminal-fg-secondary);
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		cursor: pointer;
		font-family: inherit;
		text-align: left;
	}
	.sf-section-toggle:hover {
		color: var(--terminal-fg-primary);
	}

	.sf-section-arrow {
		font-size: 9px;
		transition: transform 120ms ease;
		display: inline-block;
	}
	.sf-section-arrow.open {
		transform: rotate(90deg);
	}

	.sf-active-count {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 16px;
		height: 16px;
		border-radius: var(--terminal-radius-none);
		background: var(--terminal-accent-cyan);
		color: var(--terminal-fg-inverted);
		font-family: var(--terminal-font-mono);
		font-size: 9px;
		font-weight: 700;
		margin-left: 4px;
		padding: 0 3px;
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
		accent-color: var(--terminal-accent-cyan);
		margin: 0;
		flex-shrink: 0;
	}

	.sf-check-label {
		font-size: 11px;
		color: var(--terminal-fg-secondary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* ── Metric range inputs ─────────────────────────── */
	.sf-metric-row {
		display: flex;
		flex-direction: column;
		gap: 3px;
		margin-bottom: 8px;
	}

	.sf-metric-label {
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
	}

	.sf-metric-inputs {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.sf-metric-input {
		flex: 1;
		min-width: 0;
		width: 56px;
		background: transparent;
		border: 1px solid var(--terminal-fg-disabled);
		border-radius: 0;
		color: var(--terminal-fg-primary);
		font-family: var(--terminal-font-mono);
		font-size: 11px;
		padding: 4px 6px;
		text-align: right;
		outline: none;
		box-sizing: border-box;
		-moz-appearance: textfield;
	}
	.sf-metric-input::-webkit-inner-spin-button,
	.sf-metric-input::-webkit-outer-spin-button {
		-webkit-appearance: none;
		margin: 0;
	}
	.sf-metric-input::placeholder {
		color: var(--terminal-fg-muted);
		text-align: right;
	}
	.sf-metric-input:focus {
		border-color: color-mix(in srgb, var(--terminal-accent-cyan) 40%, transparent);
	}

	.sf-metric-sep {
		color: var(--terminal-fg-muted);
		font-size: 10px;
		flex-shrink: 0;
	}

	/* ── Manager typeahead ────────────────────────────── */
	.sf-manager-typeahead {
		position: relative;
	}

	.sf-manager-input {
		width: 100%;
		background: transparent;
		border: 1px solid var(--terminal-fg-disabled);
		border-radius: 0;
		color: var(--terminal-fg-primary);
		font-family: var(--terminal-font-mono);
		font-size: 11px;
		padding: 5px 8px;
		outline: none;
		box-sizing: border-box;
	}
	.sf-manager-input::placeholder {
		color: var(--terminal-fg-muted);
	}
	.sf-manager-input:focus {
		border-color: color-mix(in srgb, var(--terminal-accent-cyan) 40%, transparent);
	}

	.sf-manager-suggestions {
		position: absolute;
		left: 0;
		right: 0;
		z-index: 20;
		background: var(--terminal-bg-overlay);
		border: 1px solid var(--terminal-fg-disabled);
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
		color: var(--terminal-fg-secondary);
		cursor: pointer;
	}
	.sf-manager-suggestion:hover {
		background: color-mix(in srgb, var(--terminal-accent-cyan) 8%, transparent);
		color: var(--terminal-fg-primary);
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
		font-family: var(--terminal-font-mono);
		font-size: 10px;
		color: var(--terminal-accent-cyan);
		border: 1px solid color-mix(in srgb, var(--terminal-accent-cyan) 30%, transparent);
		padding: 2px 6px;
		white-space: nowrap;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.sf-manager-chip-x {
		background: none;
		border: none;
		color: var(--terminal-accent-cyan);
		font-size: 10px;
		cursor: pointer;
		padding: 0;
		line-height: 1;
		font-family: var(--terminal-font-mono);
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
		color: var(--terminal-fg-secondary);
		font-size: 10px;
	}

	.sf-range-value {
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
	}

	.sf-slider {
		width: 100%;
		-webkit-appearance: none;
		appearance: none;
		height: 3px;
		background: var(--terminal-bg-panel-raised);
		border-radius: var(--terminal-radius-none);
		outline: none;
	}
	.sf-slider::-webkit-slider-thumb {
		-webkit-appearance: none;
		appearance: none;
		width: 10px;
		height: 10px;
		border-radius: var(--terminal-radius-none);
		background: var(--terminal-accent-cyan);
		cursor: pointer;
		border: none;
	}
	.sf-slider::-moz-range-thumb {
		width: 10px;
		height: 10px;
		border-radius: var(--terminal-radius-none);
		background: var(--terminal-accent-cyan);
		cursor: pointer;
		border: none;
	}
</style>
