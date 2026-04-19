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
		{ id: "6M", label: "6M" },
		{ id: "1Y", label: "1Y" },
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

			const opts = createTerminalLightweightChartOptions({
				timeVisible: true,
				priceScaleMode: lc.PriceScaleMode.Percentage,
			});
			const c = lc.createChart(containerEl, { autoSize: true, ...opts });

			// Series 1: Instrument (baseline — cyan/red)
			const sc = terminalLWSeriesColors();
			const s = c.addSeries(lc.BaselineSeries, {
				baseValue: { type: "price", price: 0 },
				...sc.baseline,
				lineWidth: 2,
				priceLineVisible: true,
				lastValueVisible: true,
				title: "",
			});

			// Series 2: Portfolio NAV (amber line)
			const nav = c.addSeries(lc.LineSeries, {
				...sc.navOverlay,
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
