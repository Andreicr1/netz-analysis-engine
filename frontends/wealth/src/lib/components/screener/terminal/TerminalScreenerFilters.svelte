<!--
  TerminalScreenerFilters — left panel with collapsible filter sections.
  Accordion-style, all open by default. Compact 11px terminal aesthetic.
-->
<script lang="ts">
	interface FilterState {
		sectors: Set<string>;
		assetClasses: Set<string>;
		returnMin: number;
		returnMax: number;
		volMin: number;
		volMax: number;
		drawdownMin: number;
		drawdownMax: number;
	}

	interface Props {
		filters: FilterState;
		onFiltersChange: (filters: FilterState) => void;
	}

	let { filters, onFiltersChange }: Props = $props();

	const SECTORS = [
		"Technology", "Healthcare", "Financials", "Energy",
		"Consumer Discretionary", "Industrials", "Real Estate",
		"Materials", "Utilities", "Communication",
	];

	const ASSET_CLASSES = [
		"Equity", "Fixed Income", "Multi-Asset",
		"Alternative", "Money Market", "Commodity",
	];

	let sectionOpen = $state({ categories: true, metrics: true });

	function toggleSector(sector: string) {
		const next = new Set(filters.sectors);
		if (next.has(sector)) next.delete(sector);
		else next.add(sector);
		onFiltersChange({ ...filters, sectors: next });
	}

	function toggleAssetClass(ac: string) {
		const next = new Set(filters.assetClasses);
		if (next.has(ac)) next.delete(ac);
		else next.add(ac);
		onFiltersChange({ ...filters, assetClasses: next });
	}

	function handleRange(field: "returnMin" | "returnMax" | "volMin" | "volMax" | "drawdownMin" | "drawdownMax", value: number) {
		onFiltersChange({ ...filters, [field]: value });
	}

	function clearAll() {
		onFiltersChange({
			sectors: new Set(),
			assetClasses: new Set(),
			returnMin: -50,
			returnMax: 100,
			volMin: 0,
			volMax: 60,
			drawdownMin: -80,
			drawdownMax: 0,
		});
	}
</script>

<div class="sf-root">
	<div class="sf-header">
		<span class="sf-title">FILTERS</span>
		<button class="sf-clear" onclick={clearAll}>Clear</button>
	</div>

	<div class="sf-scroll">
		<!-- Categories -->
		<div class="sf-section">
			<button
				class="sf-section-toggle"
				onclick={() => (sectionOpen.categories = !sectionOpen.categories)}
			>
				<span class="sf-section-arrow" class:open={sectionOpen.categories}>&#9656;</span>
				CATEGORIES
			</button>

			{#if sectionOpen.categories}
				<div class="sf-section-body">
					<label class="sf-group-label">Sector</label>
					<div class="sf-check-grid">
						{#each SECTORS as sector}
							<label class="sf-check">
								<input
									type="checkbox"
									checked={filters.sectors.has(sector)}
									onchange={() => toggleSector(sector)}
								/>
								<span class="sf-check-label">{sector}</span>
							</label>
						{/each}
					</div>

					<label class="sf-group-label" style="margin-top:10px">Asset Class</label>
					<div class="sf-check-grid">
						{#each ASSET_CLASSES as ac}
							<label class="sf-check">
								<input
									type="checkbox"
									checked={filters.assetClasses.has(ac)}
									onchange={() => toggleAssetClass(ac)}
								/>
								<span class="sf-check-label">{ac}</span>
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
							<span>1Y Return (%)</span>
							<span class="sf-range-value">{filters.returnMin} to {filters.returnMax}</span>
						</div>
						<div class="sf-range-row">
							<input
								type="range"
								min={-50}
								max={100}
								step={1}
								value={filters.returnMin}
								oninput={(e) => handleRange("returnMin", +e.currentTarget.value)}
								class="sf-slider"
							/>
							<input
								type="range"
								min={-50}
								max={100}
								step={1}
								value={filters.returnMax}
								oninput={(e) => handleRange("returnMax", +e.currentTarget.value)}
								class="sf-slider"
							/>
						</div>
					</div>

					<div class="sf-range-group">
						<div class="sf-range-header">
							<span>Volatility (%)</span>
							<span class="sf-range-value">{filters.volMin} to {filters.volMax}</span>
						</div>
						<div class="sf-range-row">
							<input
								type="range"
								min={0}
								max={60}
								step={1}
								value={filters.volMin}
								oninput={(e) => handleRange("volMin", +e.currentTarget.value)}
								class="sf-slider"
							/>
							<input
								type="range"
								min={0}
								max={60}
								step={1}
								value={filters.volMax}
								oninput={(e) => handleRange("volMax", +e.currentTarget.value)}
								class="sf-slider"
							/>
						</div>
					</div>

					<div class="sf-range-group">
						<div class="sf-range-header">
							<span>Max Drawdown (%)</span>
							<span class="sf-range-value">{filters.drawdownMin} to {filters.drawdownMax}</span>
						</div>
						<div class="sf-range-row">
							<input
								type="range"
								min={-80}
								max={0}
								step={1}
								value={filters.drawdownMin}
								oninput={(e) => handleRange("drawdownMin", +e.currentTarget.value)}
								class="sf-slider"
							/>
							<input
								type="range"
								min={-80}
								max={0}
								step={1}
								value={filters.drawdownMax}
								oninput={(e) => handleRange("drawdownMax", +e.currentTarget.value)}
								class="sf-slider"
							/>
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

	.sf-group-label {
		display: block;
		font-size: 10px;
		font-weight: 600;
		color: #5a6577;
		margin-bottom: 4px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
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

	.sf-range-row {
		display: flex;
		gap: 6px;
	}

	.sf-slider {
		flex: 1;
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
