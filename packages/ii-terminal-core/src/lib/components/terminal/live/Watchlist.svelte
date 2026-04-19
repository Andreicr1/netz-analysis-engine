<!--
  Watchlist -- left panel of the Live Workbench.

  Shows portfolio holdings as live tickers with prices from
  MarketDataStore. Footer has a ticker search input to look up
  any Tiingo-available instrument via REST quote endpoint.

  Layout: 240px fixed-width sidebar, scrollable items, sticky
  header + footer.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { formatPercent, formatCurrency } from "@investintell/ui";
	import type { MarketDataStore, PriceTick } from "../../../stores/market-data.svelte";
	import { TERMINAL_MARKET_DATA_KEY } from "../../../components/portfolio/live/workbench-state";
	import { createClientApiClient } from "../../../api/client";

	export interface WatchlistItem {
		ticker: string;
		name: string;
		instrument_id: string;
		weight: number;
	}

	interface Props {
		items: WatchlistItem[];
		selectedTicker: string | null;
		onSelect: (ticker: string) => void;
		portfolioName: string;
	}

	let { items, selectedTicker, onSelect, portfolioName }: Props = $props();

	const marketStore = getContext<MarketDataStore>(TERMINAL_MARKET_DATA_KEY);
	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	// Ad-hoc tickers added via search (not part of portfolio)
	let adHocItems = $state<WatchlistItem[]>([]);
	let searchQuery = $state("");
	let searching = $state(false);
	let searchError = $state<string | null>(null);

	const allItems = $derived([...items, ...adHocItems]);

	function getTickData(ticker: string): PriceTick | undefined {
		return marketStore.priceMap.get(ticker.toUpperCase());
	}

	async function handleSearch(e: SubmitEvent) {
		e.preventDefault();
		const q = searchQuery.trim().toUpperCase();
		if (!q) return;

		// Already in the list?
		if (allItems.some((i) => i.ticker.toUpperCase() === q)) {
			onSelect(q);
			searchQuery = "";
			return;
		}

		searching = true;
		searchError = null;

		try {
			const res = await api.get<{
				ticker: string;
				interval: string;
				bars: Array<{ timestamp: string; close: number | null }>;
				source: string;
			}>(`/market-data/historical/${encodeURIComponent(q)}?start_date=${new Date(Date.now() - 86400000 * 5).toISOString().slice(0, 10)}`);
			adHocItems = [
				...adHocItems,
				{
					ticker: res.ticker ?? q,
					name: q,
					instrument_id: "",
					weight: 0,
				},
			];
			marketStore.subscribe([res.ticker ?? q]);
			onSelect(res.ticker ?? q);
			searchQuery = "";
		} catch {
			searchError = "Ticker not found";
			setTimeout(() => (searchError = null), 2000);
		} finally {
			searching = false;
		}
	}
</script>

<div class="wl-root">
	<!-- Header -->
	<div class="wl-header">
		<span class="wl-label">WATCHLIST</span>
		<span class="wl-portfolio" title={portfolioName}>{portfolioName}</span>
	</div>

	<!-- Items -->
	<div class="wl-items">
		{#each allItems as item (item.ticker)}
			{@const tick = getTickData(item.ticker)}
			{@const price = tick?.price ?? 0}
			{@const changePct = tick?.change_pct ?? 0}
			{@const isPositive = changePct >= 0}
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<button
				type="button"
				class="wl-row"
				class:wl-row--selected={selectedTicker?.toUpperCase() === item.ticker.toUpperCase()}
				onclick={() => onSelect(item.ticker)}
			>
				<div class="wl-row-left">
					<span class="wl-ticker">{item.ticker}</span>
					<span class="wl-name" title={item.name}>{item.name}</span>
					{#if item.weight > 0}
						<span class="wl-weight">{formatPercent(item.weight, 1)}</span>
					{/if}
				</div>
				<div class="wl-row-right">
					<span
						class="wl-change"
						class:wl-up={isPositive}
						class:wl-down={!isPositive}
					>
						{isPositive ? "\u25B2" : "\u25BC"}
						{formatPercent(Math.abs(changePct), 2)}
					</span>
					<span class="wl-price">
						{price > 0 ? formatCurrency(price) : "\u2014"}
					</span>
				</div>
			</button>
		{/each}

		{#if allItems.length === 0}
			<div class="wl-empty">No instruments</div>
		{/if}
	</div>

	<!-- Footer: search -->
	<form class="wl-search" onsubmit={handleSearch}>
		<input
			type="text"
			class="wl-search-input"
			placeholder="Search ticker..."
			bind:value={searchQuery}
			disabled={searching}
		/>
		{#if searchError}
			<span class="wl-search-error">{searchError}</span>
		{/if}
	</form>
</div>

<style>
	.wl-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}

	/* -- Header -- */
	.wl-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
		height: 28px;
		padding: 0 var(--terminal-space-2);
		border-bottom: var(--terminal-border-hairline);
	}

	.wl-label {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}

	.wl-portfolio {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
		max-width: 120px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	/* -- Items -- */
	.wl-items {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.wl-row {
		appearance: none;
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		height: 36px;
		padding: 0 var(--terminal-space-2);
		background: transparent;
		border: none;
		border-bottom: 1px solid var(--terminal-fg-muted);
		border-left: 2px solid transparent;
		cursor: pointer;
		transition: background var(--terminal-motion-tick);
		text-align: left;
	}

	.wl-row:hover {
		background: var(--terminal-bg-panel-raised);
	}

	.wl-row--selected {
		background: var(--terminal-bg-panel-raised);
		border-left-color: var(--terminal-accent-amber);
	}

	.wl-row-left {
		display: flex;
		flex-direction: column;
		gap: 1px;
		min-width: 0;
	}

	.wl-ticker {
		font-size: var(--terminal-text-11);
		font-weight: 700;
		color: var(--terminal-fg-primary);
		letter-spacing: var(--terminal-tracking-caps);
	}

	.wl-name {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 110px;
	}

	.wl-weight {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
	}

	.wl-row-right {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 1px;
		flex-shrink: 0;
	}

	.wl-change {
		font-size: var(--terminal-text-10);
		font-variant-numeric: tabular-nums;
	}

	.wl-up {
		color: var(--terminal-status-success);
	}

	.wl-down {
		color: var(--terminal-status-error);
	}

	.wl-price {
		font-size: var(--terminal-text-11);
		font-weight: 600;
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
	}

	.wl-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 80px;
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
	}

	/* -- Search footer -- */
	.wl-search {
		flex-shrink: 0;
		height: 28px;
		border-top: var(--terminal-border-hairline);
		position: relative;
	}

	.wl-search-input {
		appearance: none;
		width: 100%;
		height: 100%;
		padding: 0 var(--terminal-space-2);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-primary);
		background: var(--terminal-bg-panel-sunken);
		border: none;
		outline: none;
	}

	.wl-search-input::placeholder {
		color: var(--terminal-fg-muted);
	}

	.wl-search-input:focus {
		box-shadow: inset 0 0 0 1px var(--terminal-accent-amber);
	}

	.wl-search-error {
		position: absolute;
		top: -20px;
		left: var(--terminal-space-2);
		font-size: 9px;
		color: var(--terminal-status-error);
	}
</style>
