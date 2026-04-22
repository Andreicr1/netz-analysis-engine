<!--
  ChartToolbar -- 32px bar above the hero chart.

  Displays: ticker name, instrument name, live price, change%.
  Controls: timeframe buttons, compare toggle, indicators stub.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { formatCurrency, formatPercent } from "@investintell/ui";
	import { TerminalPill } from "../primitives";
	import type { MarketDataStore, PriceTick } from "../../../stores/market-data.svelte";
	import { TERMINAL_MARKET_DATA_KEY } from "../../../components/portfolio/live/workbench-state";
	import { createClientApiClient } from "../../../api/client";
	import type { Timeframe } from "../../../components/portfolio/live/charts/TerminalPriceChart.svelte";

	export type ChartMode = "candle" | "line";

	interface Props {
		ticker: string;
		instrumentName: string;
		timeframe: Timeframe;
		onTimeframeChange: (tf: Timeframe) => void;
		onCompare: (ticker: string) => void;
		compareTicker: string | null;
		onClearCompare: () => void;
		mode?: ChartMode;
		onModeChange?: (m: ChartMode) => void;
		/** Opens the Rebalance FocusMode. Bundle renders the same primary
		 * CTA in the chart toolbar; terminal routes it to the /live page's
		 * URL-driven rebalance handler. */
		onRebalance?: () => void;
	}

	let {
		ticker,
		instrumentName,
		timeframe,
		onTimeframeChange,
		onCompare,
		compareTicker,
		onClearCompare,
		mode = "line",
		onModeChange,
		onRebalance,
	}: Props = $props();

	const marketStore = getContext<MarketDataStore>(TERMINAL_MARKET_DATA_KEY);
	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	const TIMEFRAMES: Timeframe[] = ["1D", "1W", "1M", "3M", "6M", "1Y", "5Y", "MAX"];

	const CHART_MODES: { id: ChartMode; label: string }[] = [
		{ id: "candle", label: "CANDLE" },
		{ id: "line", label: "LINE" },
	];

	function setMode(m: ChartMode) {
		if (onModeChange) onModeChange(m);
	}

	function isEditableTarget(target: EventTarget | null): boolean {
		if (!(target instanceof HTMLElement)) return false;
		const tag = target.tagName;
		if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
		if (target.isContentEditable) return true;
		const role = target.getAttribute("role");
		if (role === "textbox" || role === "searchbox" || role === "combobox") {
			return true;
		}
		return false;
	}

	$effect(() => {
		if (typeof window === "undefined") return;
		const handler = (event: KeyboardEvent) => {
			if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
			if (isEditableTarget(event.target)) return;
			if (event.key === "c" || event.key === "C") {
				event.preventDefault();
				setMode("candle");
			} else if (event.key === "l" || event.key === "L") {
				event.preventDefault();
				setMode("line");
			}
		};
		window.addEventListener("keydown", handler);
		return () => window.removeEventListener("keydown", handler);
	});

	// Live price from MarketDataStore
	const tickData = $derived<PriceTick | undefined>(
		marketStore.priceMap.get(ticker.toUpperCase()),
	);
	const price = $derived(tickData?.price ?? 0);
	const changePct = $derived(tickData?.change_pct ?? 0);
	const isPositive = $derived(changePct >= 0);

	// Compare dropdown
	let compareOpen = $state(false);
	let compareInput = $state("");
	let compareSearching = $state(false);
	let compareError = $state<string | null>(null);

	function toggleCompare() {
		if (compareTicker) {
			onClearCompare();
			return;
		}
		compareOpen = !compareOpen;
		if (compareOpen) {
			compareInput = "";
			compareError = null;
		}
	}

	async function handleCompareSubmit(e: SubmitEvent) {
		e.preventDefault();
		const q = compareInput.trim().toUpperCase();
		if (!q) return;

		compareSearching = true;
		compareError = null;

		try {
			await api.get<{ ticker: string; bars: unknown[] }>(`/market-data/historical/${encodeURIComponent(q)}?start_date=${new Date(Date.now() - 86400000 * 5).toISOString().slice(0, 10)}`);
			marketStore.subscribe([q]);
			onCompare(q);
			compareOpen = false;
			compareInput = "";
		} catch {
			compareError = "Not found";
			setTimeout(() => (compareError = null), 2000);
		} finally {
			compareSearching = false;
		}
	}
</script>

<div class="ct-root">
	<!-- Left: ticker info -->
	<div class="ct-info">
		<span class="ct-ticker">{ticker || "---"}</span>
		<span class="ct-sep">//</span>
		<span class="ct-name" title={instrumentName}>{instrumentName}</span>
		<span class="ct-sep">//</span>
		<span class="ct-price">{price > 0 ? formatCurrency(price) : "\u2014"}</span>
		<span
			class="ct-change"
			class:ct-up={isPositive}
			class:ct-down={!isPositive}
		>
			{isPositive ? "+" : ""}{formatPercent(changePct, 2)}
		</span>
	</div>

	<!-- Right: controls -->
	<div class="ct-controls">
		<!-- Chart type toggle (Candle | Line) -->
		<div class="ct-mode" role="radiogroup" aria-label="Chart type">
			{#each CHART_MODES as cm (cm.id)}
				<TerminalPill
					as="button"
					label={cm.label}
					tone={mode === cm.id ? "accent" : "neutral"}
					pressed={mode === cm.id}
					size="sm"
					ariaLabel={`Chart type ${cm.label}`}
					onclick={() => setMode(cm.id)}
				/>
			{/each}
		</div>

		<span class="ct-divider"></span>

		<!-- Timeframe pills -->
		<div class="ct-timeframes" role="group" aria-label="Timeframe">
			{#each TIMEFRAMES as tf}
				<button
					type="button"
					class="ct-tf-btn"
					class:ct-tf-active={timeframe === tf}
					onclick={() => onTimeframeChange(tf)}
					aria-pressed={timeframe === tf}
				>
					{tf}
				</button>
			{/each}
		</div>

		<span class="ct-divider"></span>

		<!-- Compare -->
		<div class="ct-compare-wrap">
			<button
				type="button"
				class="ct-compare-btn"
				class:ct-compare-active={!!compareTicker}
				onclick={toggleCompare}
			>
				{compareTicker ? `vs ${compareTicker}` : "Compare"}
				{#if compareTicker}
					<span class="ct-compare-x" aria-label="Clear comparison">&times;</span>
				{/if}
			</button>

			{#if compareOpen}
				<form class="ct-compare-dropdown" onsubmit={handleCompareSubmit}>
					<input
						type="text"
						class="ct-compare-input"
						placeholder="Ticker..."
						bind:value={compareInput}
						disabled={compareSearching}
					/>
					{#if compareError}
						<span class="ct-compare-error">{compareError}</span>
					{/if}
				</form>
			{/if}
		</div>

		<span class="ct-divider"></span>

		<!-- Indicators stub -->
		<button type="button" class="ct-indicators-btn" disabled title="Coming in Session B">
			Indicators
		</button>

		{#if onRebalance}
			<span class="ct-divider"></span>
			<!-- Rebalance primary CTA — mirrors bundle's toolbar layout (D-11). -->
			<button type="button" class="ct-rebalance-btn" onclick={onRebalance}>
				<span aria-hidden="true">&#x27F2;</span>
				REBALANCE
			</button>
		{/if}
	</div>
</div>

<style>
	.ct-root {
		display: flex;
		align-items: center;
		justify-content: space-between;
		height: 32px;
		padding: 0 var(--terminal-space-2);
		background: var(--terminal-bg-panel);
		border-bottom: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		gap: var(--terminal-space-2);
	}

	/* -- Left info -- */
	.ct-info {
		display: flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
	}

	.ct-ticker {
		font-size: var(--terminal-text-11);
		font-weight: 700;
		color: var(--terminal-fg-primary);
		letter-spacing: var(--terminal-tracking-caps);
	}

	.ct-sep {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
	}

	.ct-name {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 200px;
	}

	.ct-price {
		/* D-12: scale up to approximate the bundle's .chart-price-big
		 * affordance while still fitting the shared 32px toolbar row.
		 * Bundle uses ~22px in a taller 2-line ticker-head; a flat
		 * 16px keeps parity with the "price-is-the-primary-signal"
		 * intent without forcing a toolbar height change. */
		font-size: 16px;
		font-weight: 700;
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
		letter-spacing: -0.01em;
	}

	.ct-change {
		font-size: 12px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.ct-up {
		color: var(--terminal-status-success);
	}

	.ct-down {
		color: var(--terminal-status-error);
	}

	/* -- Right controls -- */
	.ct-controls {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		flex-shrink: 0;
	}

	.ct-divider {
		width: 1px;
		height: 16px;
		background: var(--terminal-fg-muted);
	}

	/* -- Chart mode toggle -- */
	.ct-mode {
		display: inline-flex;
		gap: var(--terminal-space-1);
	}

	/* -- Timeframes -- */
	.ct-timeframes {
		display: flex;
		gap: 2px;
	}

	.ct-tf-btn {
		appearance: none;
		padding: 3px 8px;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: 0.04em;
		color: var(--terminal-fg-tertiary);
		background: transparent;
		border: 1px solid transparent;
		cursor: pointer;
		transition: color var(--terminal-motion-tick), background var(--terminal-motion-tick);
	}

	.ct-tf-btn:hover {
		color: var(--terminal-fg-primary);
		background: var(--terminal-bg-panel-raised);
	}

	.ct-tf-active {
		color: var(--terminal-accent-cyan);
		border-color: var(--terminal-accent-cyan-dim);
		background: var(--terminal-bg-panel-raised);
	}

	.ct-tf-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}

	/* -- Compare -- */
	.ct-compare-wrap {
		position: relative;
	}

	.ct-compare-btn {
		appearance: none;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 3px 8px;
		font-family: var(--terminal-font-mono);
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.04em;
		color: var(--terminal-fg-tertiary);
		background: transparent;
		border: 1px solid var(--terminal-fg-muted);
		cursor: pointer;
		transition: color var(--terminal-motion-tick), background var(--terminal-motion-tick);
	}

	.ct-compare-btn:hover {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber-dim);
	}

	.ct-compare-active {
		color: var(--terminal-accent-amber);
		background: var(--terminal-bg-panel-raised);
		border-color: var(--terminal-accent-amber-dim);
	}

	.ct-compare-x {
		font-size: var(--terminal-text-12);
		line-height: 1;
	}

	.ct-compare-dropdown {
		position: absolute;
		top: calc(100% + 4px);
		right: 0;
		z-index: var(--terminal-z-dropdown);
		background: var(--terminal-bg-overlay);
		border: 1px solid var(--terminal-fg-muted);
		padding: var(--terminal-space-1);
	}

	.ct-compare-input {
		appearance: none;
		width: 120px;
		height: 24px;
		padding: 0 var(--terminal-space-1);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-primary);
		background: var(--terminal-bg-panel-sunken);
		border: none;
		outline: none;
	}

	.ct-compare-input:focus {
		box-shadow: inset 0 0 0 1px var(--terminal-accent-amber);
	}

	.ct-compare-error {
		display: block;
		font-size: 9px;
		color: var(--terminal-status-error);
		padding-top: 2px;
	}

	/* -- Indicators -- */
	.ct-indicators-btn {
		appearance: none;
		padding: 3px 8px;
		font-family: var(--terminal-font-mono);
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.04em;
		color: var(--terminal-fg-disabled);
		background: transparent;
		border: 1px solid transparent;
		cursor: not-allowed;
	}

	/* -- Rebalance primary CTA (D-11) -- */
	.ct-rebalance-btn {
		appearance: none;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 3px 10px;
		font-family: var(--terminal-font-mono);
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--terminal-accent-amber);
		background: transparent;
		border: 1px solid var(--terminal-accent-amber-dim);
		cursor: pointer;
		transition: background var(--terminal-motion-tick), color var(--terminal-motion-tick);
	}

	.ct-rebalance-btn:hover {
		background: var(--terminal-bg-panel-raised);
		color: var(--terminal-fg-primary);
	}

	.ct-rebalance-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}
</style>
