<!--
  TerminalPriceChart — lightweight-charts v5 with NAV overlay.

  Two series on one chart in Percentage mode:
    1. Baseline (blue) — selected instrument price
    2. Line (gold) — composite portfolio NAV

  PriceScaleMode.Percentage normalises both to the same Y-axis
  so instruments with different base prices are visually comparable.

  Anti-SSR: dynamic import() inside onMount.
  Dual-effect: historical setData vs live update() (no fitContent).
  Toggle: "vs Portfolio NAV" button shows/hides the gold line.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import {
		createTerminalLightweightChartOptions,
		terminalLWSeriesColors,
	} from "@investintell/ui";

	// ── Types ─────────────────────────────────────────────────
	export interface BarData {
		time: number; // UTC seconds
		value: number;
	}

	export interface LiveTick {
		time: number; // UTC seconds
		value: number;
	}

	type Timeframe = "1D" | "1W" | "1M" | "3M" | "6M" | "1Y";
	export type DataStatus = "live" | "delayed" | "offline";
	export type ChartMode = "candle" | "line";

	export interface CandleBar {
		time: number;
		open: number;
		high: number;
		low: number;
		close: number;
	}

	interface Props {
		ticker: string;
		historicalBars: BarData[];
		candleBars?: CandleBar[];
		lastTick: LiveTick | null;
		portfolioNavBars: BarData[];
		timeframe: Timeframe;
		onTimeframeChange: (tf: Timeframe) => void;
		dataStatus?: DataStatus;
		mode?: ChartMode;
	}

	let {
		ticker,
		historicalBars,
		candleBars = [],
		lastTick,
		portfolioNavBars,
		timeframe,
		onTimeframeChange,
		dataStatus = "live",
		mode = "line",
	}: Props = $props();

	const TIMEFRAMES: { id: Timeframe; label: string }[] = [
		{ id: "1D", label: "1D" },
		{ id: "1W", label: "1W" },
		{ id: "1M", label: "1M" },
		{ id: "3M", label: "3M" },
		{ id: "6M", label: "6M" },
		{ id: "1Y", label: "1Y" },
	];

	// ── Chart state ($state for reactivity tracking) ──────────
	let containerEl: HTMLDivElement | undefined = $state();
	let chart = $state<any>(null);
	let series = $state<any>(null);
	let navSeries = $state<any>(null);
	let showNav = $state(true);
	let lcModule = $state<typeof import("lightweight-charts") | null>(null);
	let currentSeriesMode = $state<ChartMode | null>(null);
	/** Last rolled candle — used to aggregate live ticks in candle mode. */
	let currentCandle: CandleBar | null = null;

	// ── Async chart initialization (SSR-safe) ─────────────────
	onMount(() => {
		let disposed = false;

		(async () => {
			const lc = await import("lightweight-charts");
			if (disposed || !containerEl) return;

			const opts = createTerminalLightweightChartOptions({
				timeVisible: true,
				priceScaleMode: lc.PriceScaleMode.Percentage,
			});
			const c = lc.createChart(containerEl, { autoSize: true, ...opts });

			// Series 2: Portfolio NAV (amber line) — stable across mode swaps.
			const sc = terminalLWSeriesColors();
			const nav = c.addSeries(lc.LineSeries, {
				...sc.navOverlay,
				lineWidth: 2,
				title: "NAV",
				crosshairMarkerVisible: true,
				crosshairMarkerRadius: 3,
				priceLineVisible: false,
				lastValueVisible: true,
			});

			lcModule = lc;
			chart = c;
			navSeries = nav;
		})();

		return () => {
			disposed = true;
			if (chart) {
				chart.remove();
				chart = null;
				series = null;
				navSeries = null;
			}
		};
	});

	/**
	 * Build the instrument series for the current `mode`. Creates the
	 * baseline/candlestick series on the owning chart, seeds it with
	 * the appropriate data source, and returns the handle. Keeps the
	 * <div> container + IChartApi instance stable (plan §A.9 contract).
	 */
	function mountInstrumentSeries(lc: typeof import("lightweight-charts"), c: any, m: ChartMode) {
		const sc = terminalLWSeriesColors();
		if (m === "candle") {
			const s = c.addSeries(lc.CandlestickSeries, {
				upColor: "#22c55e",
				downColor: "#ef4444",
				borderUpColor: "#22c55e",
				borderDownColor: "#ef4444",
				wickUpColor: "#22c55e",
				wickDownColor: "#ef4444",
				priceLineVisible: true,
				lastValueVisible: true,
			});
			return s;
		}
		const s = c.addSeries(lc.BaselineSeries, {
			baseValue: { type: "price", price: 0 },
			...sc.baseline,
			lineWidth: 2,
			priceLineVisible: true,
			lastValueVisible: true,
			title: "",
		});
		return s;
	}

	// ── Effect: mode swap (preserve visible range) ───────────
	// Replaces the instrument series in place when mode changes.
	// Captures the visible range BEFORE removing the old series and
	// restores it after the new series is seeded, so the viewport
	// does not reset on toggle (plan §A.9).
	$effect(() => {
		const lc = lcModule;
		const c = chart;
		const m = mode;
		if (!lc || !c) return;
		if (currentSeriesMode === m && series !== null) return;

		const priorRange = (() => {
			try {
				return c.timeScale().getVisibleRange();
			} catch {
				return null;
			}
		})();

		if (series !== null) {
			try {
				c.removeSeries(series);
			} catch {
				// If removal fails (e.g. disposed chart), bail — the
				// next onMount cycle will rebuild from scratch.
				return;
			}
		}

		const next = mountInstrumentSeries(lc, c, m);

		// Swap price-scale mode per series type: percentage for the
		// baseline line (% change vs first bar), normal for candles
		// (absolute OHLC values).
		c.applyOptions({
			rightPriceScale: {
				mode: m === "candle" ? lc.PriceScaleMode.Normal : lc.PriceScaleMode.Percentage,
			},
		});

		// Seed with data appropriate for the mode.
		if (m === "candle" && candleBars.length) {
			next.setData(candleBars);
			currentCandle = candleBars[candleBars.length - 1] ?? null;
		} else if (m === "line" && historicalBars.length) {
			next.applyOptions({
				baseValue: { type: "price", price: historicalBars[0]!.value },
			});
			next.setData(historicalBars);
			currentCandle = null;
		}

		// Restore the user's viewport if one existed.
		if (priorRange) {
			try {
				c.timeScale().setVisibleRange(priorRange);
			} catch {
				// Ranges can mismatch if the two datasets have
				// different domains; fall back to fit.
				c.timeScale().fitContent();
			}
		} else {
			c.timeScale().fitContent();
		}

		series = next;
		currentSeriesMode = m;
	});

	// ── Effect 1: Historical instrument bars ─────────────────
	// Reseed when the underlying bars array changes AND the current
	// series matches mode=line. The mode-swap effect above handles
	// the cross-mode reseed path.
	$effect(() => {
		const s = series;
		const c = chart;
		const bars = historicalBars;
		if (!s || !c || mode !== "line" || !bars.length) return;
		if (currentSeriesMode !== "line") return;

		s.applyOptions({
			baseValue: { type: "price", price: bars[0]!.value },
		});
		s.setData(bars);
	});

	// ── Effect 1b: Historical candle bars ────────────────────
	$effect(() => {
		const s = series;
		const c = chart;
		const bars = candleBars;
		if (!s || !c || mode !== "candle" || !bars.length) return;
		if (currentSeriesMode !== "candle") return;

		s.setData(bars);
		currentCandle = bars[bars.length - 1] ?? null;
	});

	// ── Effect 2: Portfolio NAV bars ─────────────────────────
	$effect(() => {
		const ns = navSeries;
		const bars = portfolioNavBars;
		if (!ns) return;

		if (bars.length > 0) {
			ns.setData(bars);
		}
	});

	// ── Effect 3: NAV visibility toggle ──────────────────────
	// NAV is hidden in candle mode because the price axis switches to
	// absolute values — a percent-baselined NAV line on an absolute
	// OHLC axis is visually misleading.
	$effect(() => {
		const ns = navSeries;
		const visible = showNav && mode === "line";
		if (!ns) return;
		ns.applyOptions({ visible });
	});

	// ── Effect 4: Live tick (incremental update) ─────────────
	$effect(() => {
		const s = series;
		const tick = lastTick;
		if (!s || !tick) return;

		if (mode === "line") {
			s.update({ time: tick.time, value: tick.value });
			return;
		}

		// Candle mode: aggregate tick into the current bar. If the
		// tick timestamp advances past the current bar, roll a new
		// candle seeded from the prior close. This mirrors plan §A.9
		// "local tick aggregation" until a dedicated 1m-bars stream
		// exists on the backend.
		const price = tick.value;
		const t = tick.time;
		if (!currentCandle || t > currentCandle.time) {
			const open = currentCandle?.close ?? price;
			currentCandle = { time: t, open, high: price, low: price, close: price };
		} else {
			currentCandle = {
				...currentCandle,
				high: Math.max(currentCandle.high, price),
				low: Math.min(currentCandle.low, price),
				close: price,
			};
		}
		s.update(currentCandle);
	});

	function toggleNav() {
		showNav = !showNav;
	}
</script>

<div class="tpc-root">
	<!-- Controls bar -->
	<div class="tpc-controls">
		<div class="tpc-ticker-row">
			<span class="tpc-ticker">{ticker || "---"}</span>
			{#if dataStatus !== "live"}
				<span
					class="tpc-status-badge"
					class:tpc-status-delayed={dataStatus === "delayed"}
					class:tpc-status-offline={dataStatus === "offline"}
					aria-label="Data status: {dataStatus}"
				>{dataStatus.toUpperCase()}</span>
			{/if}
		</div>

		<div class="tpc-right-controls">
			<!-- NAV overlay toggle -->
			<button
				type="button"
				class="tpc-nav-toggle"
				class:tpc-nav-toggle--active={showNav}
				onclick={toggleNav}
				aria-pressed={showNav}
				title="Toggle portfolio NAV overlay"
			>
				<span class="tpc-nav-check" aria-hidden="true">{showNav ? "\u2713" : ""}</span>
				vs NAV
			</button>

			<!-- Timeframe pills -->
			<div class="tpc-timeframes" role="group" aria-label="Timeframe">
				{#each TIMEFRAMES as tf}
					<button
						type="button"
						class="tpc-tf-btn"
						class:tpc-tf-active={timeframe === tf.id}
						onclick={() => onTimeframeChange(tf.id)}
						aria-pressed={timeframe === tf.id}
					>
						{tf.label}
					</button>
				{/each}
			</div>
		</div>
	</div>

	<!-- Chart canvas -->
	<div class="tpc-chart" bind:this={containerEl}></div>
</div>

<style>
	.tpc-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
	}

	/* ── Controls bar ────────────────────────────────────────── */
	.tpc-controls {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
		height: 32px;
		padding: 0 10px;
		border-bottom: var(--terminal-border-hairline);
		position: relative;
		z-index: 10;
	}

	.tpc-ticker-row {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.tpc-ticker {
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-secondary);
	}

	.tpc-status-badge {
		font-family: var(--terminal-font-mono);
		font-size: 8px;
		font-weight: 800;
		letter-spacing: 0.08em;
		padding: 1px 5px;
	}
	.tpc-status-delayed {
		color: var(--terminal-status-warn);
		background: color-mix(in srgb, var(--terminal-status-warn) 12%, transparent);
		border: 1px solid color-mix(in srgb, var(--terminal-status-warn) 25%, transparent);
	}
	.tpc-status-offline {
		color: var(--terminal-status-error);
		background: color-mix(in srgb, var(--terminal-status-error) 12%, transparent);
		border: 1px solid color-mix(in srgb, var(--terminal-status-error) 25%, transparent);
	}

	/* ── Right controls (toggle + timeframes) ────────────────── */
	.tpc-right-controls {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	/* ── NAV toggle button ───────────────────────────────────── */
	.tpc-nav-toggle {
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
		border: var(--terminal-border-hairline);
		cursor: pointer;
		transition: color 80ms, background 80ms, border-color 80ms;
	}
	.tpc-nav-toggle:hover {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber-dim);
	}
	.tpc-nav-toggle--active {
		color: var(--terminal-accent-amber);
		background: color-mix(in srgb, var(--terminal-accent-amber) 8%, transparent);
		border-color: var(--terminal-accent-amber-dim);
	}
	.tpc-nav-toggle:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}
	.tpc-nav-check {
		font-size: 9px;
		width: 9px;
		text-align: center;
	}

	/* ── Separator between toggle and timeframes ─────────────── */
	.tpc-right-controls .tpc-timeframes {
		padding-left: 8px;
		border-left: var(--terminal-border-hairline);
	}

	.tpc-timeframes {
		display: flex;
		gap: 2px;
	}

	.tpc-tf-btn {
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
		transition: color 80ms, background 80ms, border-color 80ms;
	}
	.tpc-tf-btn:hover {
		color: var(--terminal-fg-secondary);
		background: var(--terminal-bg-panel-raised);
	}
	.tpc-tf-active {
		color: var(--terminal-accent-cyan);
		border-color: var(--terminal-accent-cyan-dim);
		background: color-mix(in srgb, var(--terminal-accent-cyan) 8%, transparent);
	}
	.tpc-tf-btn:focus-visible {
		outline: 2px solid var(--terminal-accent-cyan);
		outline-offset: 1px;
	}

	/* ── Chart container ─────────────────────────────────────── */
	.tpc-chart {
		position: relative;
		z-index: 0;
		flex: 1;
		min-height: 0;
		min-width: 0;
		width: 100%;
		overflow: hidden;
	}
</style>
