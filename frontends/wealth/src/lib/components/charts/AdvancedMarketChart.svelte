<!--
  AdvancedMarketChart — TradingView Lightweight Charts (Tiingo IEX firehose).

  - Engine: lightweight-charts v5 (canvas-based, ~50 KB gzipped, 60fps).
  - Theme: 100% transparent — inherits the parent panel's glassmorphism.
  - Tick fold: marketStore.priceMap[ticker] → series.update() on every IEX trade.
  - Volume series mounted on a separate price scale (overlay below candles).

  Lifecycle:
    1. onMount → createChart() once, attach ResizeObserver.
    2. $effect(ticker, interval) → fetch /market-data/historical, series.setData().
    3. $effect(priceMap[ticker]) → series.update({ ...lastBar, close, high, low }).
    4. onDestroy → chart.remove() + observer.disconnect().
-->
<script lang="ts">
	import { getContext, onDestroy, onMount } from "svelte";
	import { formatCurrency, formatNumber } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { MarketDataStore } from "$lib/stores/market-data.svelte";
	// Type-only imports — erased at runtime, safe under SSR.
	// The actual lightweight-charts module is loaded lazily in onMount because
	// it touches `window`/`document` at top level and would crash Node SSR.
	import type {
		IChartApi,
		ISeriesApi,
		CandlestickData,
		HistogramData,
		Time,
		UTCTimestamp,
	} from "lightweight-charts";

	// ── Props ────────────────────────────────────────────────────────────
	interface Props {
		ticker: string;
		height?: number;
	}

	let { ticker, height = 420 }: Props = $props();

	// ── Context ──────────────────────────────────────────────────────────
	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const marketStore = getContext<MarketDataStore | undefined>("netz:marketDataStore");

	// ── State ────────────────────────────────────────────────────────────
	type Bar = {
		time: UTCTimestamp;
		open: number;
		high: number;
		low: number;
		close: number;
		volume: number;
	};

	let bars = $state<Bar[]>([]);
	let loading = $state(false);
	let error = $state<string | null>(null);

	const INTERVALS = ["daily", "1hour", "30min", "15min", "5min"] as const;
	// Default interval is fixed to "daily" — runtime switching is via the
	// interval-selector buttons. Removing the prop binding here avoids
	// Svelte's `state_referenced_locally` warning.
	let activeInterval = $state<(typeof INTERVALS)[number]>("daily");

	// ── Chart refs (non-reactive — DOM/imperative) ───────────────────────
	let chartContainer: HTMLDivElement;
	let chart: IChartApi | null = null;
	let candleSeries: ISeriesApi<"Candlestick"> | null = null;
	let volumeSeries: ISeriesApi<"Histogram"> | null = null;

	// ── Time helpers ─────────────────────────────────────────────────────
	function toUtcSeconds(iso: string): UTCTimestamp {
		const t = Math.floor(new Date(iso).getTime() / 1000);
		return t as UTCTimestamp;
	}

	// ── Mount: dynamically import lightweight-charts (browser-only) ──────
	// The library touches `window`/`document` at top level and would crash
	// SvelteKit SSR if imported statically. We pull values lazily here and
	// keep the type imports above (erased at compile time).
	onMount(async () => {
		const lwc = await import("lightweight-charts");
		const { createChart, CandlestickSeries, HistogramSeries, CrosshairMode } = lwc;

		const chartInstance = createChart(chartContainer, {
			autoSize: true,
			layout: {
				background: { type: "solid" as never, color: "transparent" },
				textColor: "#888888",
				fontFamily: "Inter, system-ui, sans-serif",
				fontSize: 11,
			},
			grid: {
				vertLines: { color: "rgba(255,255,255,0.02)" },
				horzLines: { color: "rgba(255,255,255,0.02)" },
			},
			rightPriceScale: {
				borderVisible: false,
				scaleMargins: { top: 0.08, bottom: 0.28 },
			},
			timeScale: {
				borderVisible: false,
				timeVisible: activeInterval !== "daily",
				secondsVisible: false,
			},
			crosshair: {
				mode: CrosshairMode.Normal,
				vertLine: { color: "rgba(255,255,255,0.15)", width: 1, style: 0 },
				horzLine: { color: "rgba(255,255,255,0.15)", width: 1, style: 0 },
			},
		});

		candleSeries = chartInstance.addSeries(CandlestickSeries, {
			upColor: "#11ec79",
			downColor: "#fc1a1a",
			borderUpColor: "#11ec79",
			borderDownColor: "#fc1a1a",
			wickUpColor: "rgba(17,236,121,0.7)",
			wickDownColor: "rgba(252,26,26,0.7)",
			priceFormat: { type: "price", precision: 2, minMove: 0.01 },
		});

		volumeSeries = chartInstance.addSeries(HistogramSeries, {
			priceFormat: { type: "volume" },
			priceScaleId: "vol",
			color: "rgba(255,255,255,0.25)",
		});
		// Pin volume to the bottom 22% of the pane.
		chartInstance.priceScale("vol").applyOptions({
			scaleMargins: { top: 0.78, bottom: 0 },
		});

		// Publish only once everything is wired — the fetch/tick $effects
		// gate on `chart` being non-null, so this avoids a race where setData
		// fires against half-initialized series.
		chart = chartInstance;

		// Pre-warm WS if idle.
		if (marketStore && marketStore.status === "disconnected") {
			marketStore.start();
		}
	});

	onDestroy(() => {
		chart?.remove();
		chart = null;
		candleSeries = null;
		volumeSeries = null;
	});

	// ── Fetch + WS subscription on ticker / interval change ──────────────
	$effect(() => {
		const t = ticker?.trim().toUpperCase();
		const intv = activeInterval;
		if (!t || !candleSeries || !volumeSeries || !chart) {
			return;
		}

		let cancelled = false;
		loading = true;
		error = null;

		(async () => {
			try {
				const api = createClientApiClient(getToken);
				type RawBar = {
					timestamp: string;
					open: number;
					high: number;
					low: number;
					close: number;
					volume: number;
				};
				const resp = await api.get<{ bars: RawBar[] }>(
					`/market-data/historical/${encodeURIComponent(t)}?interval=${intv}`,
				);
				if (cancelled || !candleSeries || !volumeSeries) return;

				const next: Bar[] = (resp.bars ?? [])
					.map((b) => ({
						time: toUtcSeconds(b.timestamp),
						open: Number(b.open),
						high: Number(b.high),
						low: Number(b.low),
						close: Number(b.close),
						volume: Number(b.volume ?? 0),
					}))
					// Defensive: lightweight-charts requires strictly ascending time.
					.sort((a, b) => (a.time as number) - (b.time as number));

				bars = next;

				const candleData: CandlestickData[] = next.map((b) => ({
					time: b.time as Time,
					open: b.open,
					high: b.high,
					low: b.low,
					close: b.close,
				}));
				const volumeData: HistogramData[] = next.map((b) => ({
					time: b.time as Time,
					value: b.volume,
					color: b.close >= b.open ? "rgba(17,236,121,0.45)" : "rgba(252,26,26,0.45)",
				}));

				candleSeries.setData(candleData);
				volumeSeries.setData(volumeData);
				chart?.timeScale().fitContent();

				// Adapt time axis labels to selected interval.
				chart?.applyOptions({
					timeScale: { timeVisible: intv !== "daily", secondsVisible: false },
				});
			} catch (e) {
				if (!cancelled) error = e instanceof Error ? e.message : "Failed to load chart";
			} finally {
				if (!cancelled) loading = false;
			}
		})();

		marketStore?.subscribe([t]);

		return () => {
			cancelled = true;
		};
	});

	// ── Live tick fold ───────────────────────────────────────────────────
	// Reads marketStore.priceMap[ticker] — Svelte 5 wires this $effect to
	// the rune so every IEX trade triggers series.update() on the last bar.
	$effect(() => {
		if (!marketStore || !candleSeries || !volumeSeries) return;
		const t = ticker?.trim().toUpperCase();
		if (!t || bars.length === 0) return;

		const tick = marketStore.priceMap[t];
		if (!tick || !tick.price) return;

		const last = bars[bars.length - 1]!;
		const lastDay = new Date((last.time as number) * 1000).toISOString().slice(0, 10);
		const tickDay = (tick.timestamp || new Date().toISOString()).slice(0, 10);
		// Daily bars are immutable for prior sessions — only fold same-day ticks.
		if (activeInterval === "daily" && lastDay !== tickDay) return;

		const price = Number(tick.price);
		const newHigh = Math.max(last.high, price);
		const newLow = Math.min(last.low, price);
		const tickVol = Number(tick.volume ?? 0);
		const newVolume = last.volume + tickVol;

		// Skip duplicates (firehose dedupe).
		if (last.close === price && last.high === newHigh && last.low === newLow) {
			return;
		}

		// Mutate the in-memory bar (kept in sync with what's drawn).
		last.close = price;
		last.high = newHigh;
		last.low = newLow;
		last.volume = newVolume;

		// Surgical update — single bar, no re-render.
		candleSeries.update({
			time: last.time as Time,
			open: last.open,
			high: last.high,
			low: last.low,
			close: last.close,
		});
		volumeSeries.update({
			time: last.time as Time,
			value: last.volume,
			color: last.close >= last.open ? "rgba(17,236,121,0.45)" : "rgba(252,26,26,0.45)",
		});
	});

	// ── Header summary (live) ────────────────────────────────────────────
	let livePrice = $derived.by(() => {
		const t = ticker?.trim().toUpperCase();
		if (!t) return null;
		const tick = marketStore?.priceMap[t];
		if (tick?.price) return Number(tick.price);
		if (bars.length > 0) return bars[bars.length - 1]!.close;
		return null;
	});

	let livePct = $derived.by(() => {
		if (bars.length < 2 || livePrice == null) return null;
		const prev = bars[bars.length - 2]!.close;
		if (prev === 0) return null;
		return (livePrice - prev) / prev;
	});
</script>

<div class="advanced-chart">
	<header class="chart-header">
		<div class="chart-title">
			<span class="ticker">{ticker || "—"}</span>
			{#if livePrice != null}
				<span class="price">{formatCurrency(livePrice)}</span>
				{#if livePct != null}
					<span class="delta" class:up={livePct >= 0} class:down={livePct < 0}>
						{livePct >= 0 ? "▲" : "▼"} {formatNumber(livePct * 100, 2)}%
					</span>
				{/if}
			{/if}
		</div>
		<div class="interval-selector">
			{#each INTERVALS as iv (iv)}
				<button
					type="button"
					class="iv-btn"
					class:iv-btn--active={activeInterval === iv}
					onclick={() => (activeInterval = iv)}
				>{iv}</button>
			{/each}
		</div>
	</header>

	<div class="chart-stage" style:height="{height}px">
		<div bind:this={chartContainer} class="chart-canvas"></div>
		{#if loading && bars.length === 0}
			<div class="chart-overlay">Loading {ticker}…</div>
		{:else if error}
			<div class="chart-overlay chart-overlay--error">{error}</div>
		{:else if !loading && bars.length === 0}
			<div class="chart-overlay">No data for {ticker || "selected ticker"}</div>
		{/if}
	</div>
</div>

<style>
	.advanced-chart {
		display: flex;
		flex-direction: column;
		gap: 8px;
		width: 100%;
	}

	.chart-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		flex-wrap: wrap;
	}

	.chart-title {
		display: flex;
		align-items: baseline;
		gap: 10px;
		font-variant-numeric: tabular-nums;
	}

	.ticker {
		font-size: 18px;
		font-weight: 700;
		color: #ffffff;
		letter-spacing: -0.02em;
	}

	.price {
		font-size: 15px;
		font-weight: 600;
		color: #ffffff;
	}

	.delta {
		font-size: 11px;
		font-weight: 600;
		padding: 2px 8px;
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.04);
	}

	.delta.up { color: #11ec79; }
	.delta.down { color: #fc1a1a; }

	.interval-selector {
		display: flex;
		gap: 2px;
	}

	.iv-btn {
		padding: 4px 10px;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: #85a0bd;
		background: transparent;
		border: 1px solid rgba(255, 255, 255, 0.08);
		border-radius: 6px;
		cursor: pointer;
		transition: all 150ms ease;
	}

	.iv-btn:hover {
		color: #ffffff;
		background: rgba(255, 255, 255, 0.05);
	}

	.iv-btn--active {
		color: #ffffff;
		background: #0177fb;
		border-color: #0177fb;
	}

	.chart-stage {
		position: relative;
		width: 100%;
	}

	.chart-canvas {
		position: absolute;
		inset: 0;
	}

	.chart-overlay {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 12px;
		color: #85a0bd;
		pointer-events: none;
	}

	.chart-overlay--error {
		color: #fc1a1a;
	}
</style>
