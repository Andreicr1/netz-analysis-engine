<!--
  HoldingsTable — 8-column Bloomberg-style holdings grid.

  Structure mirrors docs/ux/Netz Terminal/terminal-panels.jsx's
  `Holdings` component: TK · NAME/SECTOR · LAST · CHG% · WT ·
  DRIFT-BAR · Δpp · TGT. Sortable columns, client-side filter,
  drift visualized with a ±4pp centered bar.

  Consumes bundle surface classes from
  @investintell/ui/styles/surfaces/terminal.css (globally imported
  by frontends/terminal/src/app.css): .panel, .phead, .holdings-head,
  .holdings-row, .drift-bar-wrap, .drift-mid, .drift-bar,
  .sortable, .sort-active.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { formatPercent, formatCurrency } from "@investintell/ui";
	import type { MarketDataStore, PriceTick } from "../../../stores/market-data.svelte";
	import { TERMINAL_MARKET_DATA_KEY } from "../../../components/portfolio/live/workbench-state";

	export interface HoldingRow {
		instrument_id: string;
		fund_name: string;
		ticker: string;
		weight: number;
		target_weight: number;
		/** Optional asset class / sector label shown as a sub-line on the NAME cell. */
		asset_class?: string;
	}

	interface Props {
		holdings: HoldingRow[];
		selectedTicker: string | null;
		onSelect: (ticker: string) => void;
	}

	let { holdings, selectedTicker, onSelect }: Props = $props();

	const marketStore = getContext<MarketDataStore>(TERMINAL_MARKET_DATA_KEY);

	function getTickData(ticker: string): PriceTick | undefined {
		return marketStore.priceMap.get(ticker.toUpperCase());
	}

	type SortKey =
		| "ticker"
		| "name"
		| "price"
		| "change"
		| "weight"
		| "drift"
		| "target";
	type SortDir = "asc" | "desc";

	let sortKey = $state<SortKey>("weight");
	let sortDir = $state<SortDir>("desc");
	let filter = $state("");

	function toggleSort(k: SortKey) {
		if (sortKey === k) {
			sortDir = sortDir === "asc" ? "desc" : "asc";
		} else {
			sortKey = k;
			sortDir = "desc";
		}
	}

	function sortIndicator(k: SortKey): string {
		if (sortKey !== k) return "";
		return sortDir === "asc" ? "\u25B2" : "\u25BC";
	}

	const filteredSorted = $derived.by<HoldingRow[]>(() => {
		const q = filter.trim().toUpperCase();
		let list = holdings;
		if (q) {
			list = list.filter(
				(r) =>
					r.ticker.toUpperCase().includes(q) ||
					r.fund_name.toUpperCase().includes(q) ||
					(r.asset_class ?? "").toUpperCase().includes(q),
			);
		}
		const arr = list.slice();
		arr.sort((a, b) => {
			let av: number | string;
			let bv: number | string;
			if (sortKey === "ticker") {
				av = a.ticker;
				bv = b.ticker;
			} else if (sortKey === "name") {
				av = a.fund_name;
				bv = b.fund_name;
			} else if (sortKey === "price") {
				av = getTickData(a.ticker)?.price ?? 0;
				bv = getTickData(b.ticker)?.price ?? 0;
			} else if (sortKey === "change") {
				av = getTickData(a.ticker)?.change_pct ?? 0;
				bv = getTickData(b.ticker)?.change_pct ?? 0;
			} else if (sortKey === "weight") {
				av = a.weight;
				bv = b.weight;
			} else if (sortKey === "target") {
				av = a.target_weight;
				bv = b.target_weight;
			} else {
				av = Math.abs(a.weight - a.target_weight);
				bv = Math.abs(b.weight - b.target_weight);
			}
			if (typeof av === "string" && typeof bv === "string") {
				return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
			}
			const an = av as number;
			const bn = bv as number;
			return sortDir === "asc" ? an - bn : bn - an;
		});
		return arr;
	});

	/** ±4pp visual cap — bundle default. */
	const DRIFT_VISUAL_CAP_PP = 4;
</script>

<div class="panel holdings-panel">
	<div class="phead">
		<div>
			<span class="title">Holdings</span>
			<span class="counter">{filteredSorted.length}/{holdings.length}</span>
		</div>
		<div class="actions">
			<input
				class="holdings-filter"
				type="text"
				placeholder="FILTER"
				bind:value={filter}
				aria-label="Filter holdings"
			/>
		</div>
	</div>

	<div class="holdings-head">
		<span
			class="sortable"
			class:sort-active={sortKey === "ticker"}
			onclick={() => toggleSort("ticker")}
			onkeydown={(e) => e.key === "Enter" && toggleSort("ticker")}
			role="button"
			tabindex="0"
		>TK {sortIndicator("ticker")}</span>
		<span
			class="sortable"
			class:sort-active={sortKey === "name"}
			onclick={() => toggleSort("name")}
			onkeydown={(e) => e.key === "Enter" && toggleSort("name")}
			role="button"
			tabindex="0"
		>NAME / SECTOR</span>
		<span
			class="sortable"
			class:sort-active={sortKey === "price"}
			onclick={() => toggleSort("price")}
			onkeydown={(e) => e.key === "Enter" && toggleSort("price")}
			role="button"
			tabindex="0"
			style="text-align: right"
		>LAST {sortIndicator("price")}</span>
		<span
			class="sortable"
			class:sort-active={sortKey === "change"}
			onclick={() => toggleSort("change")}
			onkeydown={(e) => e.key === "Enter" && toggleSort("change")}
			role="button"
			tabindex="0"
			style="text-align: right"
		>CHG% {sortIndicator("change")}</span>
		<span
			class="sortable"
			class:sort-active={sortKey === "weight"}
			onclick={() => toggleSort("weight")}
			onkeydown={(e) => e.key === "Enter" && toggleSort("weight")}
			role="button"
			tabindex="0"
			style="text-align: right"
		>WT {sortIndicator("weight")}</span>
		<span style="text-align: center">DRIFT</span>
		<span
			class="sortable"
			class:sort-active={sortKey === "drift"}
			onclick={() => toggleSort("drift")}
			onkeydown={(e) => e.key === "Enter" && toggleSort("drift")}
			role="button"
			tabindex="0"
			style="text-align: right"
		>Δ pp {sortIndicator("drift")}</span>
		<span style="text-align: right">TGT</span>
	</div>

	<div class="holdings-body">
		{#each filteredSorted as r (r.instrument_id)}
			{@const tick = getTickData(r.ticker)}
			{@const price = tick?.price ?? 0}
			{@const changePct = tick?.change_pct ?? 0}
			{@const driftFrac = r.weight - r.target_weight}
			{@const driftPp = driftFrac * 100}
			{@const absDriftPp = Math.abs(driftPp)}
			{@const barPct = Math.min(1, absDriftPp / DRIFT_VISUAL_CAP_PP)}
			{@const barLeft = driftPp >= 0 ? "50%" : `${50 - barPct * 50}%`}
			{@const barWidth = `${barPct * 50}%`}
			{@const driftTone =
				absDriftPp >= 3 ? "down" : absDriftPp >= 2 ? "warn" : "up"}
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<div
				class="holdings-row"
				class:selected={selectedTicker?.toUpperCase() === r.ticker.toUpperCase()}
				onclick={() => onSelect(r.ticker)}
				role="button"
				tabindex="0"
				onkeydown={(e) => e.key === "Enter" && onSelect(r.ticker)}
			>
				<span class="tk">{r.ticker}</span>
				<span class="nm" title={r.fund_name}>
					<span>{r.fund_name}</span>
					{#if r.asset_class}
						<span class="nm-sector">{r.asset_class}</span>
					{/if}
				</span>
				<span class="px">{price > 0 ? formatCurrency(price) : "\u2014"}</span>
				<span class="dp" class:up={changePct >= 0} class:down={changePct < 0}>
					{changePct !== 0
						? (changePct >= 0 ? "+" : "") + formatPercent(changePct, 2)
						: "\u2014"}
				</span>
				<span class="wt">{formatPercent(r.weight, 1)}</span>
				<span class="drift-bar-wrap">
					<span class="drift-mid"></span>
					<span
						class="drift-bar"
						class:drift-tone-down={driftTone === "down"}
						class:drift-tone-warn={driftTone === "warn"}
						class:drift-tone-up={driftTone === "up"}
						style="left: {barLeft}; width: {barWidth}"
					></span>
				</span>
				<span
					class="tgt drift-delta"
					class:drift-tone-down={driftTone === "down"}
					class:drift-tone-warn={driftTone === "warn"}
					class:drift-tone-up={driftTone === "up"}
				>{driftPp >= 0 ? "+" : ""}{driftPp.toFixed(2)}</span>
				<span class="tgt">{formatPercent(r.target_weight, 1)}</span>
			</div>
		{/each}

		{#if holdings.length === 0}
			<div class="holdings-empty">No holdings</div>
		{/if}
		{#if holdings.length > 0 && filteredSorted.length === 0}
			<div class="holdings-empty">No matches</div>
		{/if}
	</div>
</div>

<style>
	.holdings-panel {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		overflow: hidden;
	}

	.holdings-filter {
		appearance: none;
		width: 110px;
		height: 18px;
		padding: 0 6px;
		font-family: var(--ii-terminal-font-mono, var(--terminal-font-mono));
		font-size: 10px;
		letter-spacing: 0.04em;
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		background: var(--ii-surface-alt, var(--terminal-bg-panel-raised));
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		outline: none;
	}

	.holdings-filter:focus {
		border-color: var(--ii-brand-primary, var(--terminal-accent-amber));
	}

	.holdings-filter::placeholder {
		color: var(--ii-text-muted, var(--terminal-fg-muted));
	}

	/* Per-column name cell: primary text + sector sub-line. */
	.holdings-row .nm {
		display: flex;
		align-items: baseline;
		gap: 6px;
		min-width: 0;
	}

	.holdings-row .nm > span:first-child {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--ii-text-primary, var(--terminal-fg-primary));
	}

	.nm-sector {
		flex-shrink: 0;
		font-size: 9px;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		text-transform: uppercase;
	}

	/* Drift-bar tones — extend the bundle's neutral orange bar with
	   a semantic severity color when drift crosses ±2pp / ±3pp. */
	.holdings-row .drift-bar.drift-tone-up {
		background: var(--ii-success, var(--terminal-status-success));
	}
	.holdings-row .drift-bar.drift-tone-warn {
		background: var(--ii-warning, var(--terminal-status-warn));
	}
	.holdings-row .drift-bar.drift-tone-down {
		background: var(--ii-danger, var(--terminal-status-error));
	}

	/* Δpp text colour */
	.drift-delta.drift-tone-up {
		color: var(--ii-success, var(--terminal-status-success));
		font-weight: 600;
	}
	.drift-delta.drift-tone-warn {
		color: var(--ii-warning, var(--terminal-status-warn));
		font-weight: 600;
	}
	.drift-delta.drift-tone-down {
		color: var(--ii-danger, var(--terminal-status-error));
		font-weight: 600;
	}

	.holdings-empty {
		padding: 24px 12px;
		text-align: center;
		font-family: var(--ii-terminal-font-mono, var(--terminal-font-mono));
		font-size: 10px;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
	}
</style>
