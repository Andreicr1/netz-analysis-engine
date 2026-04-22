<!--
	SparklineWall — grid of macro indicator mini sparklines.

	Each cell: indicator name, latest FRED value + REST-origin trend
	arrow, and the 12-month mini sparkline rendered via the shared
	TerminalMiniSparkline primitive. Indicators with a Tiingo proxy
	(VIXCLS→VXX, DTWEXBGS→UUP, DGS10→IEF) surface an additional
	"LIVE" pill — the proxy tick is NOT merged into the sparkline,
	because the series units don't line up (see macro-sparkline-
	adapter.ts header). The FRED number stays authoritative; the
	proxy is a freshness signal.
-->
<script lang="ts">
	import { getContext, onDestroy } from "svelte";
	import { formatNumber } from "@investintell/ui";
	import { TerminalMiniSparkline } from "../primitives";
	import type { MarketDataStore } from "../../../stores/market-data.svelte";
	import { TERMINAL_MARKET_DATA_KEY } from "../../../components/portfolio/live/workbench-state";
	import {
		proxyFor,
		PROXY_SYMBOLS,
	} from "./macro-sparkline-adapter";

	export interface MacroIndicator {
		/** Optional FRED series id — required for Tiingo proxy lookup. */
		seriesId?: string;
		name: string;
		currentValue: number;
		previousValue: number;
		history: Array<{ date: string; value: number }>;
		unit: string;
	}

	interface Props {
		indicators: MacroIndicator[];
	}

	let { indicators }: Props = $props();

	const marketData = getContext<MarketDataStore | undefined>(
		TERMINAL_MARKET_DATA_KEY,
	);

	// Subscribe once for the three proxy symbols. MarketDataStore
	// dedupes existing subscriptions, so this is safe even when
	// another page (e.g. /portfolio/live) has already subscribed.
	let subscribedOnMount = false;
	$effect(() => {
		if (!marketData || subscribedOnMount) return;
		marketData.subscribe([...PROXY_SYMBOLS]);
		subscribedOnMount = true;
	});
	onDestroy(() => {
		// Let the store manage refcount — we only unsubscribe the
		// symbols we added. If another consumer still needs them,
		// MarketDataStore keeps them live.
		marketData?.unsubscribe([...PROXY_SYMBOLS]);
	});

	function trendArrow(current: number, previous: number): string {
		if (current > previous) return "\u25B2";
		if (current < previous) return "\u25BC";
		return "\u25C6";
	}

	function trendColor(current: number, previous: number): string {
		if (current > previous) return "var(--terminal-status-success)";
		if (current < previous) return "var(--terminal-status-error)";
		return "var(--terminal-fg-secondary)";
	}

	function formatUnit(value: number, unit: string): string {
		if (unit === "%") return formatNumber(value, 1) + "%";
		if (unit === "bps") return formatNumber(value, 0) + " bps";
		if (unit === "idx") return formatNumber(value, 1);
		return formatNumber(value, 2);
	}

	function liveProxyPrice(seriesId: string | undefined): number | null {
		if (!seriesId || !marketData) return null;
		const symbol = proxyFor(seriesId);
		if (!symbol) return null;
		return marketData.priceMap.get(symbol)?.price ?? null;
	}

	function sparklineValues(history: MacroIndicator["history"]): number[] {
		return history.map((pt) => pt.value);
	}
</script>

<div class="sw-root">
	{#each indicators as ind (ind.name)}
		{@const livePx = liveProxyPrice(ind.seriesId)}
		<div class="sw-cell" class:sw-cell--live={livePx !== null}>
			<div class="sw-meta">
				<div class="sw-name-row">
					<span class="sw-name">{ind.name}</span>
					{#if livePx !== null}
						<span class="sw-live" title="Live proxy tick — not merged into sparkline">
							LIVE
						</span>
					{/if}
				</div>
				<div class="sw-value-row">
					<span class="sw-value">{formatUnit(ind.currentValue, ind.unit)}</span>
					<span class="sw-arrow" style:color={trendColor(ind.currentValue, ind.previousValue)}>
						{trendArrow(ind.currentValue, ind.previousValue)}
					</span>
				</div>
				{#if livePx !== null && ind.seriesId}
					<span class="sw-proxy">
						{proxyFor(ind.seriesId)} {formatNumber(livePx, 2)}
					</span>
				{/if}
			</div>
			{#if ind.history.length > 1}
				<div class="sw-chart">
					<TerminalMiniSparkline
						data={sparklineValues(ind.history)}
						width={120}
						height={28}
						ariaLabel="{ind.name} sparkline"
					/>
				</div>
			{/if}
		</div>
	{/each}
</div>

<style>
	.sw-root {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--terminal-space-2);
		font-family: var(--terminal-font-mono);
		width: 100%;
	}

	.sw-cell {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
		padding: var(--terminal-space-2);
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
	}
	.sw-cell--live {
		border-color: var(--terminal-accent-amber-dim);
	}

	.sw-meta {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.sw-name-row {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-1);
	}

	.sw-name {
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.sw-live {
		padding: 0 4px;
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-accent-amber);
		border: 1px solid var(--terminal-accent-amber);
		line-height: 1.4;
	}

	.sw-value-row {
		display: flex;
		align-items: baseline;
		gap: var(--terminal-space-1);
	}

	.sw-value {
		font-size: var(--terminal-text-12);
		font-weight: 600;
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
	}

	.sw-arrow {
		font-size: var(--terminal-text-10);
		font-weight: 700;
	}

	.sw-proxy {
		font-size: var(--terminal-text-10);
		color: var(--terminal-accent-amber);
		font-variant-numeric: tabular-nums;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.sw-chart {
		display: flex;
		justify-content: flex-start;
		min-height: 0;
	}
</style>
