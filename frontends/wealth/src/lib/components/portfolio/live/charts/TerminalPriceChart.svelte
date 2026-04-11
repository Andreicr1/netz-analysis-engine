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

	// ── Types ─────────────────────────────────────────────────
	export interface BarData {
		time: number; // UTC seconds
		value: number;
	}

	export interface LiveTick {
		time: number; // UTC seconds
		value: number;
	}

	type Timeframe = "1D" | "1W" | "1M" | "3M";
	export type DataStatus = "live" | "delayed" | "offline";

	interface Props {
		ticker: string;
		historicalBars: BarData[];
		lastTick: LiveTick | null;
		portfolioNavBars: BarData[];
		timeframe: Timeframe;
		onTimeframeChange: (tf: Timeframe) => void;
		dataStatus?: DataStatus;
	}

	let {
		ticker,
		historicalBars,
		lastTick,
		portfolioNavBars,
		timeframe,
		onTimeframeChange,
		dataStatus = "live",
	}: Props = $props();

	const TIMEFRAMES: { id: Timeframe; label: string }[] = [
		{ id: "1D", label: "1D" },
		{ id: "1W", label: "1W" },
		{ id: "1M", label: "1M" },
		{ id: "3M", label: "3M" },
	];

	// ── Chart state ($state for reactivity tracking) ──────────
	let containerEl: HTMLDivElement | undefined = $state();
	let chart = $state<any>(null);
	let series = $state<any>(null);
	let navSeries = $state<any>(null);
	let showNav = $state(true);

	// ── Async chart initialization (SSR-safe) ─────────────────
	onMount(() => {
		let disposed = false;

		(async () => {
			const lc = await import("lightweight-charts");
			if (disposed || !containerEl) return;

			const c = lc.createChart(containerEl, {
				autoSize: true,
				layout: {
					background: { color: "transparent" },
					textColor: "#5a6577",
					fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
					fontSize: 10,
				},
				grid: {
					vertLines: { color: "rgba(255, 255, 255, 0.04)" },
					horzLines: { color: "rgba(255, 255, 255, 0.04)" },
				},
				crosshair: {
					vertLine: {
						color: "rgba(45, 126, 247, 0.3)",
						labelBackgroundColor: "#2d7ef7",
					},
					horzLine: {
						color: "rgba(45, 126, 247, 0.3)",
						labelBackgroundColor: "#2d7ef7",
					},
				},
				rightPriceScale: {
					mode: lc.PriceScaleMode.Percentage,
					borderVisible: false,
					scaleMargins: { top: 0.08, bottom: 0.08 },
				},
				timeScale: {
					borderColor: "rgba(255, 255, 255, 0.08)",
					timeVisible: true,
					secondsVisible: false,
					rightOffset: 5,
				},
				handleScroll: true,
				handleScale: true,
			});

			// Series 1: Instrument (baseline — blue/red)
			const s = c.addSeries(lc.BaselineSeries, {
				baseValue: { type: "price", price: 0 },
				topLineColor: "#2d7ef7",
				topFillColor1: "rgba(45, 126, 247, 0.10)",
				topFillColor2: "rgba(45, 126, 247, 0.01)",
				bottomLineColor: "#e74c3c",
				bottomFillColor1: "rgba(231, 76, 60, 0.01)",
				bottomFillColor2: "rgba(231, 76, 60, 0.06)",
				lineWidth: 2,
				priceLineVisible: true,
				priceLineColor: "rgba(45, 126, 247, 0.4)",
				lastValueVisible: true,
				title: "",
			});

			// Series 2: Portfolio NAV (gold line)
			const nav = c.addSeries(lc.LineSeries, {
				color: "#fbbf24",
				lineWidth: 2,
				title: "NAV",
				crosshairMarkerVisible: true,
				crosshairMarkerRadius: 3,
				priceLineVisible: false,
				lastValueVisible: true,
			});

			chart = c;
			series = s;
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

	// ── Effect 1: Historical instrument bars ─────────────────
	$effect(() => {
		const s = series;
		const c = chart;
		const bars = historicalBars;
		if (!s || !c || !bars.length) return;

		s.applyOptions({
			baseValue: { type: "price", price: bars[0]!.value },
		});
		s.setData(bars);
		c.timeScale().fitContent();
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
	$effect(() => {
		const ns = navSeries;
		const visible = showNav;
		if (!ns) return;
		ns.applyOptions({ visible });
	});

	// ── Effect 4: Live tick (incremental update) ─────────────
	$effect(() => {
		const s = series;
		const tick = lastTick;
		if (!s || !tick) return;
		s.update({ time: tick.time, value: tick.value });
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
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
		position: relative;
		z-index: 10;
	}

	.tpc-ticker-row {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.tpc-ticker {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.06em;
		color: #c8d0dc;
	}

	.tpc-status-badge {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 8px;
		font-weight: 800;
		letter-spacing: 0.08em;
		padding: 1px 5px;
	}
	.tpc-status-delayed {
		color: #f59e0b;
		background: rgba(245, 158, 11, 0.12);
		border: 1px solid rgba(245, 158, 11, 0.25);
	}
	.tpc-status-offline {
		color: #ef4444;
		background: rgba(239, 68, 68, 0.12);
		border: 1px solid rgba(239, 68, 68, 0.25);
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
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.04em;
		color: #5a6577;
		background: transparent;
		border: 1px solid rgba(255, 255, 255, 0.06);
		cursor: pointer;
		transition: color 80ms, background 80ms, border-color 80ms;
	}
	.tpc-nav-toggle:hover {
		color: #fbbf24;
		border-color: rgba(251, 191, 36, 0.2);
	}
	.tpc-nav-toggle--active {
		color: #fbbf24;
		background: rgba(251, 191, 36, 0.08);
		border-color: rgba(251, 191, 36, 0.25);
	}
	.tpc-nav-toggle:focus-visible {
		outline: 2px solid #fbbf24;
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
		border-left: 1px solid rgba(255, 255, 255, 0.06);
	}

	.tpc-timeframes {
		display: flex;
		gap: 2px;
	}

	.tpc-tf-btn {
		appearance: none;
		padding: 3px 8px;
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.04em;
		color: #5a6577;
		background: transparent;
		border: 1px solid transparent;
		cursor: pointer;
		transition: color 80ms, background 80ms, border-color 80ms;
	}
	.tpc-tf-btn:hover {
		color: #c8d0dc;
		background: rgba(255, 255, 255, 0.04);
	}
	.tpc-tf-active {
		color: #2d7ef7;
		border-color: rgba(45, 126, 247, 0.3);
		background: rgba(45, 126, 247, 0.08);
	}
	.tpc-tf-btn:focus-visible {
		outline: 2px solid #2d7ef7;
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
