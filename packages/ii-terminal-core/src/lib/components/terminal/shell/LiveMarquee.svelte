<!-- Live price marquee for the Terminal shell. -->
<script lang="ts">
	import { getContext, onDestroy, onMount } from "svelte";
	import { createTickBuffer, type TickBuffer } from "@investintell/ui/runtime";
	import { formatNumber } from "@investintell/ui";
	import type { EChartsOption } from "echarts";
	import TerminalChart from "../charts/TerminalChart.svelte";
	import { TERMINAL_MARKET_DATA_KEY } from "../../portfolio/live/workbench-state";
	import type { MarketDataStore, PriceTick } from "../../../stores/market-data.svelte";

	interface Props {
		tickers: string[];
	}

	let { tickers }: Props = $props();

	interface MarqueePoint {
		id: string;
		ticker: string;
		time: number;
		price: number;
		changePct: number;
	}

	const marketStore = getContext<MarketDataStore>(TERMINAL_MARKET_DATA_KEY);
	const pointBuffer: TickBuffer<MarqueePoint> = createTickBuffer<MarqueePoint>({
		keyOf: (point) => point.id,
		maxKeys: 1200,
		evictionPolicy: "drop_oldest",
		clock: { intervalMs: 500 },
	});

	let successColor = $state("var(--terminal-status-success)");
	let errorColor = $state("var(--terminal-status-error)");

	onMount(() => {
		const style = getComputedStyle(document.documentElement);
		successColor = style.getPropertyValue("--terminal-status-success").trim() || successColor;
		errorColor = style.getPropertyValue("--terminal-status-error").trim() || errorColor;
	});

	onDestroy(() => {
		pointBuffer.dispose();
	});

	const normalizedTickers = $derived(
		tickers.map((ticker) => ticker.toUpperCase()).filter((ticker) => ticker.length > 0),
	);

	$effect(() => {
		if (normalizedTickers.length === 0) return;
		marketStore.subscribe(normalizedTickers);
		return () => marketStore.unsubscribe(normalizedTickers);
	});

	$effect(() => {
		const snapshot = marketStore.priceMap;
		for (const ticker of normalizedTickers) {
			const tick = snapshot.get(ticker);
			if (!tick) continue;
			const time = Date.parse(tick.timestamp) || Date.now();
			pointBuffer.write({
				id: `${ticker}:${time}`,
				ticker,
				time,
				price: tick.price,
				changePct: tick.change_pct,
			});
		}
	});

	function latestTick(ticker: string): PriceTick | undefined {
		return marketStore.priceMap.get(ticker);
	}

	function seriesFor(ticker: string): Array<[number, number]> {
		return Array.from(pointBuffer.snapshot.values())
			.filter((point) => point.ticker === ticker)
			.sort((a, b) => a.time - b.time)
			.slice(-100)
			.map((point) => [point.time, point.price]);
	}

	function optionFor(ticker: string, up: boolean): EChartsOption {
		const data = seriesFor(ticker);
		return {
			animation: false,
			grid: { left: 0, right: 0, top: 2, bottom: 2 },
			xAxis: { type: "time", show: false },
			yAxis: { type: "value", show: false, scale: true },
			series: [
				{
					name: ticker,
					type: "line",
					data,
					showSymbol: false,
					sampling: "lttb",
					lineStyle: { width: 1, color: up ? successColor : errorColor },
					areaStyle: { opacity: 0.08, color: up ? successColor : errorColor },
				},
			],
		};
	}
</script>

<div class="lm-root" role="list" aria-label="Live prices">
	{#each normalizedTickers as ticker (ticker)}
		{@const tick = latestTick(ticker)}
		{@const changePct = tick?.change_pct ?? 0}
		{@const up = changePct >= 0}
		<div class="lm-item" role="listitem">
			<div class="lm-quote">
				<span class="lm-ticker">{ticker}</span>
				<span class="lm-price">{tick ? formatNumber(tick.price, 2) : "--"}</span>
				<span class="lm-change" class:lm-change--up={up} class:lm-change--down={!up}>
					{tick ? `${up ? "+" : ""}${formatNumber(changePct, 2)}%` : "--"}
				</span>
			</div>
			<div class="lm-chart">
				<TerminalChart
					option={optionFor(ticker, up)}
					renderer="svg"
					height={28}
					ariaLabel={`${ticker} live sparkline`}
					empty={seriesFor(ticker).length === 0}
					emptyMessage="--"
				/>
			</div>
		</div>
	{/each}

	{#if normalizedTickers.length === 0}
		<span class="lm-empty">NO LIVE TICKERS</span>
	{/if}
</div>

<style>
	.lm-root {
		display: flex;
		align-items: stretch;
		gap: var(--terminal-space-2);
		width: 100%;
		height: 100%;
		max-height: 88px;
		min-height: 0;
		overflow: hidden;
		font-family: var(--terminal-font-mono);
	}

	.lm-item {
		display: grid;
		grid-template-columns: minmax(86px, auto) 92px;
		align-items: center;
		gap: var(--terminal-space-2);
		min-width: 196px;
		padding: 0 var(--terminal-space-2);
		border-right: var(--terminal-border-hairline);
	}

	.lm-quote {
		display: grid;
		grid-template-columns: 44px 1fr;
		grid-template-rows: 1fr 1fr;
		align-items: center;
		column-gap: var(--terminal-space-2);
		min-width: 0;
	}

	.lm-ticker {
		grid-row: 1 / 3;
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-11);
		font-weight: 700;
		letter-spacing: 0;
	}

	.lm-price,
	.lm-change {
		text-align: right;
		font-variant-numeric: tabular-nums;
		letter-spacing: 0;
	}

	.lm-price {
		color: var(--terminal-fg-secondary);
		font-size: var(--terminal-text-10);
	}

	.lm-change {
		font-size: var(--terminal-text-10);
	}

	.lm-change--up {
		color: var(--terminal-status-success);
	}

	.lm-change--down {
		color: var(--terminal-status-error);
	}

	.lm-chart {
		width: 92px;
		height: 28px;
		overflow: hidden;
	}

	.lm-chart :global(.terminal-chart) {
		background: transparent;
		border: 0;
	}

	.lm-empty {
		display: inline-flex;
		align-items: center;
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
	}
</style>
