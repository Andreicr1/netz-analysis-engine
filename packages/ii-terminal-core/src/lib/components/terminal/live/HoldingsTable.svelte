<!--
  HoldingsTable -- portfolio positions with live prices.

  Bottom-right panel. Columns: Fund, Ticker, Weight, Target,
  Drift, Price, Change. Row click selects ticker for chart.
  Sticky header, scrollable body.
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

	function driftStatus(drift: number): "aligned" | "watch" | "breach" {
		const abs = Math.abs(drift);
		if (abs >= 0.03) return "breach";
		if (abs >= 0.02) return "watch";
		return "aligned";
	}
</script>

<div class="ht-root">
	<div class="ht-header">
		<span class="ht-label">HOLDINGS</span>
		<span class="ht-count">{holdings.length}</span>
	</div>

	<div class="ht-body">
		<table class="ht-table">
			<thead>
				<tr>
					<th class="ht-th ht-th--name" scope="col">Fund</th>
					<th class="ht-th ht-th--ticker" scope="col">Ticker</th>
					<th class="ht-th ht-th--num" scope="col">Weight</th>
					<th class="ht-th ht-th--num" scope="col">Target</th>
					<th class="ht-th ht-th--num" scope="col">Drift</th>
					<th class="ht-th ht-th--num" scope="col">Price</th>
					<th class="ht-th ht-th--num" scope="col">Change</th>
				</tr>
			</thead>
			<tbody>
				{#each holdings as h (h.instrument_id)}
					{@const tick = getTickData(h.ticker)}
					{@const drift = h.weight - h.target_weight}
					{@const ds = driftStatus(drift)}
					{@const changePct = tick?.change_pct ?? 0}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<tr
						class="ht-row"
						class:ht-row--selected={selectedTicker?.toUpperCase() === h.ticker.toUpperCase()}
						onclick={() => onSelect(h.ticker)}
					>
						<td class="ht-td ht-td--name" title={h.fund_name}>{h.fund_name}</td>
						<td class="ht-td ht-td--ticker">{h.ticker}</td>
						<td class="ht-td ht-td--num">{formatPercent(h.weight, 1)}</td>
						<td class="ht-td ht-td--num ht-muted">{formatPercent(h.target_weight, 1)}</td>
						<td
							class="ht-td ht-td--num"
							class:ht-drift-aligned={ds === "aligned"}
							class:ht-drift-watch={ds === "watch"}
							class:ht-drift-breach={ds === "breach"}
						>
							{drift >= 0 ? "+" : ""}{formatPercent(drift, 2)}
						</td>
						<td class="ht-td ht-td--num">
							{tick?.price ? formatCurrency(tick.price) : "\u2014"}
						</td>
						<td
							class="ht-td ht-td--num"
							class:ht-up={changePct >= 0}
							class:ht-down={changePct < 0}
						>
							{changePct !== 0 ? formatPercent(changePct, 2) : "\u2014"}
						</td>
					</tr>
				{/each}

				{#if holdings.length === 0}
					<tr>
						<td class="ht-td ht-empty" colspan="7">No holdings</td>
					</tr>
				{/if}
			</tbody>
		</table>
	</div>
</div>

<style>
	.ht-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}

	.ht-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
		height: 28px;
		padding: 0 var(--terminal-space-2);
		border-bottom: var(--terminal-border-hairline);
	}

	.ht-label {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}

	.ht-count {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		color: var(--terminal-fg-tertiary);
	}

	.ht-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.ht-table {
		width: 100%;
		border-collapse: collapse;
		font-variant-numeric: tabular-nums;
	}

	/* -- Headers -- */
	.ht-th {
		position: sticky;
		top: 0;
		z-index: 2;
		padding: var(--terminal-space-1) var(--terminal-space-2);
		font-size: 9px;
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-muted);
		background: var(--terminal-bg-panel);
		border-bottom: var(--terminal-border-hairline);
		white-space: nowrap;
	}

	.ht-th--name {
		text-align: left;
	}

	.ht-th--ticker {
		text-align: left;
	}

	.ht-th--num {
		text-align: right;
	}

	/* -- Cells -- */
	.ht-td {
		padding: var(--terminal-space-1) var(--terminal-space-2);
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-secondary);
		border-bottom: var(--terminal-border-hairline);
		white-space: nowrap;
	}

	.ht-td--name {
		text-align: left;
		font-size: var(--terminal-text-11);
		font-weight: 500;
		color: var(--terminal-fg-primary);
		max-width: 200px;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.ht-td--ticker {
		text-align: left;
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
	}

	.ht-td--num {
		text-align: right;
	}

	.ht-muted {
		color: var(--terminal-fg-tertiary);
	}

	.ht-empty {
		text-align: center;
		padding: var(--terminal-space-6);
		color: var(--terminal-fg-muted);
	}

	/* -- Row interaction -- */
	.ht-row {
		cursor: pointer;
		transition: background var(--terminal-motion-tick);
	}

	.ht-row:hover {
		background: var(--terminal-bg-panel-raised);
	}

	.ht-row--selected {
		background: var(--terminal-bg-panel-raised);
	}

	/* -- Drift colors -- */
	.ht-drift-aligned {
		color: var(--terminal-status-success);
	}

	.ht-drift-watch {
		color: var(--terminal-status-warn);
	}

	.ht-drift-breach {
		color: var(--terminal-status-error);
	}

	/* -- P&L colors -- */
	.ht-up {
		color: var(--terminal-status-success);
	}

	.ht-down {
		color: var(--terminal-status-error);
	}
</style>
