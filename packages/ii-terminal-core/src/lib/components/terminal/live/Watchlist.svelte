<!--
  Watchlist — left panel of the Live Workbench.

  4-col layout (TICKER · NAME · LAST · CHG%) matches
  docs/ux/Netz Terminal/terminal-panels.jsx Watchlist component.
  Rows flash up/down on price tick (D-3).

  Consumes bundle classes from @investintell/ui/styles/surfaces/
  terminal.css: .panel, .phead, .wl-header, .wl-row (+ .tk .nm .px
  .chg / .flash-up / .flash-down). Footer ticker search is retained
  over the bundle's decorative `+` button — it actually looks up
  Tiingo-available instruments.
-->
<script lang="ts">
	import { getContext, untrack } from "svelte";
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

	// ── Price-tick flash (D-3) ──────────────────────────────────
	// Tracks previous price per ticker (non-reactive map) and flags
	// the row with "flash-up" / "flash-down" for 500ms when the
	// store's priceMap snapshot reassigns. The effect runs at most
	// once per tickBuffer flush (250ms), not per render.
	const prevPrices = new Map<string, number>();
	// eslint-disable-next-line svelte/prefer-svelte-reactivity -- transient UI animation state driven by store flushes; full reassignment only fires on genuine change.
	let flashMap = $state<Map<string, "up" | "down">>(new Map());

	$effect(() => {
		const snap = marketStore.priceMap;
		const changes: Array<[string, "up" | "down"]> = [];
		for (const [t, tick] of snap) {
			const prev = prevPrices.get(t);
			if (prev !== undefined && tick.price !== prev) {
				changes.push([t, tick.price > prev ? "up" : "down"]);
			}
			prevPrices.set(t, tick.price);
		}
		if (changes.length === 0) return;
		const nextFlash = new Map(untrack(() => flashMap));
		for (const [k, v] of changes) nextFlash.set(k, v);
		flashMap = nextFlash;
		const changedKeys = changes.map(([k]) => k);
		const id = setTimeout(() => {
			const cleared = new Map(untrack(() => flashMap));
			for (const k of changedKeys) cleared.delete(k);
			flashMap = cleared;
		}, 500);
		return () => clearTimeout(id);
	});

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

<div class="panel watchlist-panel">
	<div class="phead">
		<div>
			<span class="title">Watchlist</span>
			<span class="counter">{allItems.length}</span>
		</div>
		<div class="actions wl-portfolio-tag" title={portfolioName}>
			{portfolioName}
		</div>
	</div>

	<div class="wl-header">
		<span>TICKER</span>
		<span>NAME</span>
		<span style="text-align: right">LAST</span>
		<span style="text-align: right">CHG%</span>
	</div>

	<div class="wl-body">
		{#each allItems as item (item.ticker)}
			{@const tkUpper = item.ticker.toUpperCase()}
			{@const tick = getTickData(item.ticker)}
			{@const price = tick?.price ?? 0}
			{@const changePct = tick?.change_pct ?? 0}
			{@const flash = flashMap.get(tkUpper)}
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<div
				class="wl-row"
				class:selected={selectedTicker?.toUpperCase() === tkUpper}
				class:flash-up={flash === "up"}
				class:flash-down={flash === "down"}
				onclick={() => onSelect(item.ticker)}
				role="button"
				tabindex="0"
				onkeydown={(e) => e.key === "Enter" && onSelect(item.ticker)}
			>
				<span class="tk">{item.ticker}</span>
				<span class="nm" title={item.name}>{item.name}</span>
				<span class="px">
					{price > 0 ? price.toFixed(2) : "\u2014"}
				</span>
				<span class="chg" class:up={changePct >= 0} class:down={changePct < 0}>
					{changePct !== 0
						? (changePct >= 0 ? "+" : "") + changePct.toFixed(2)
						: "\u2014"}
				</span>
			</div>
		{/each}

		{#if allItems.length === 0}
			<div class="wl-empty">No instruments</div>
		{/if}
	</div>

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
	.watchlist-panel {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		overflow: hidden;
	}

	.wl-portfolio-tag {
		font-size: 9px;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		text-transform: uppercase;
		max-width: 120px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.wl-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.wl-empty {
		padding: 24px 12px;
		text-align: center;
		font-family: var(--ii-terminal-font-mono, var(--terminal-font-mono));
		font-size: 10px;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
	}

	.wl-search {
		flex-shrink: 0;
		height: 28px;
		border-top: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		position: relative;
	}

	.wl-search-input {
		appearance: none;
		width: 100%;
		height: 100%;
		padding: 0 10px;
		font-family: var(--ii-terminal-font-mono, var(--terminal-font-mono));
		font-size: 10px;
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		background: var(--ii-surface-alt, var(--terminal-bg-panel-raised));
		border: none;
		outline: none;
	}

	.wl-search-input::placeholder {
		color: var(--ii-text-muted, var(--terminal-fg-muted));
	}

	.wl-search-input:focus {
		box-shadow: inset 0 0 0 1px var(--ii-brand-primary, var(--terminal-accent-amber));
	}

	.wl-search-error {
		position: absolute;
		top: -18px;
		left: 10px;
		font-size: 9px;
		color: var(--ii-danger, var(--terminal-status-error));
	}
</style>
