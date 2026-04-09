<!--
  TerminalPriceChart — TradingView Advanced Charting Library integration.

  Replaces lightweight-charts with the full TradingView widget for:
    - Professional candlestick/line/area charting
    - 50+ built-in technical indicators (RSI, MACD, Bollinger, etc.)
    - Native "Compare" / "Add Symbol" for NAV overlay
    - Percentage mode for cross-asset comparison
    - Drawing tools, crosshair, multi-pane layout

  Datafeed: Custom adapter in tv-datafeed.ts bridges our REST+WS APIs.
  Styling: Brutalismo financeiro — #05080f bg, muted grid, no neon.

  Anti-SSR: Widget instantiation is deferred to onMount (browser-only).

  IMPORTANT: The TradingView Charting Library static files must be placed
  at /static/charting_library/ (standard distribution). The library is
  proprietary and not available via npm — obtain from TradingView B2B.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import { createNetzDatafeed, type NetzDatafeed } from "$lib/services/tv-datafeed";

	export type DataStatus = "live" | "delayed" | "offline";

	interface Props {
		/** Ticker symbol to display (e.g. "SPY", "BND"). */
		ticker: string;
		/** Portfolio ID for NAV comparison (used as compare symbol). */
		portfolioNavTicker?: string;
		/** Data status badge. */
		dataStatus?: DataStatus;
	}

	let {
		ticker,
		portfolioNavTicker,
		dataStatus = "live",
	}: Props = $props();

	let containerEl: HTMLDivElement | undefined = $state();
	let widget: any = $state(null);
	let datafeed: NetzDatafeed | null = $state(null);
	let tvReady = $state(false);
	let tvError = $state<string | null>(null);

	// ── Build the WS URL from current location ────────────────
	function buildWsUrl(): string {
		const proto = location.protocol === "https:" ? "wss:" : "ws:";
		// TODO: inject JWT token for production auth
		return `${proto}//${location.host}/api/v1/market-data/live/ws?token=dev`;
	}

	// ── Widget Initialization (SSR-safe) ──────────────────────
	onMount(() => {
		let disposed = false;

		async function initWidget() {
			if (!containerEl) return;

			// Check if TradingView library is loaded
			const TV = (window as any).TradingView;
			if (!TV?.widget) {
				console.warn(
					"[TerminalPriceChart] TradingView Charting Library not found.",
					"Place the library files at /static/charting_library/",
					"Falling back to placeholder.",
				);
				tvError = "TradingView Charting Library not loaded. Place library files at /static/charting_library/.";
				return;
			}

			if (disposed) return;

			// Create our custom datafeed
			const feed = createNetzDatafeed({
				apiBaseUrl: "/api/v1/market-data",
				wsUrl: buildWsUrl(),
			});
			datafeed = feed;

			console.log("[TerminalPriceChart] Creating widget for", ticker);

			const w = new TV.widget({
				// ── Core ─────────────────────────────────────────
				symbol: ticker || "SPY",
				interval: "D",
				container: containerEl,
				datafeed: feed,
				library_path: "/charting_library/",
				locale: "en",
				fullscreen: false,
				autosize: true,

				// ── Features ─────────────────────────────────────
				disabled_features: [
					"header_symbol_search",
					"symbol_search_hot_key",
					"header_saveload",
					"use_localstorage_for_settings",
					"popup_hints",
					"display_market_status",
					"header_quick_search",
					"go_to_date",
				],
				enabled_features: [
					"study_templates",
					"side_toolbar_in_fullscreen_mode",
					"header_indicators",
					"header_compare",
					"compare_symbol",
					"header_chart_type",
					"header_settings",
					"header_fullscreen_button",
					"header_screenshot",
					"hide_left_toolbar_by_default",
				],

				// ── Timeframes ───────────────────────────────────
				time_frames: [
					{ text: "1D", resolution: "5", description: "1 Day" },
					{ text: "1W", resolution: "15", description: "1 Week" },
					{ text: "1M", resolution: "60", description: "1 Month" },
					{ text: "3M", resolution: "D", description: "3 Months" },
					{ text: "6M", resolution: "D", description: "6 Months" },
					{ text: "1Y", resolution: "D", description: "1 Year" },
				],

				// ── Brutalismo Financeiro Theme ──────────────────
				theme: "dark",
				loading_screen: {
					backgroundColor: "#05080f",
					foregroundColor: "#2d7ef7",
				},
				custom_css_url: "",  // Can point to a custom CSS file if needed

				overrides: {
					// ── Background & Canvas ──────────────────────
					"paneProperties.background": "#05080f",
					"paneProperties.backgroundType": "solid",
					"paneProperties.vertGridProperties.color": "rgba(255, 255, 255, 0.03)",
					"paneProperties.horzGridProperties.color": "rgba(255, 255, 255, 0.03)",

					// ── Candles — muted institutional, not neon ──
					"mainSeriesProperties.candleStyle.upColor": "#2d7ef7",
					"mainSeriesProperties.candleStyle.downColor": "#5a3f7a",
					"mainSeriesProperties.candleStyle.borderUpColor": "#2d7ef7",
					"mainSeriesProperties.candleStyle.borderDownColor": "#5a3f7a",
					"mainSeriesProperties.candleStyle.wickUpColor": "#2d7ef7",
					"mainSeriesProperties.candleStyle.wickDownColor": "#5a3f7a",

					// ── Area / Line (when not candle) ────────────
					"mainSeriesProperties.areaStyle.color1": "rgba(45, 126, 247, 0.12)",
					"mainSeriesProperties.areaStyle.color2": "rgba(45, 126, 247, 0.01)",
					"mainSeriesProperties.areaStyle.linecolor": "#2d7ef7",
					"mainSeriesProperties.lineStyle.color": "#2d7ef7",

					// ── Scales ───────────────────────────────────
					"scalesProperties.textColor": "#5a6577",
					"scalesProperties.lineColor": "rgba(255, 255, 255, 0.06)",
					"scalesProperties.backgroundColor": "#05080f",

					// ── Crosshair ────────────────────────────────
					"paneProperties.crossHairProperties.color": "rgba(45, 126, 247, 0.4)",

					// ── Price line ───────────────────────────────
					"mainSeriesProperties.priceLineColor": "rgba(45, 126, 247, 0.5)",
					"mainSeriesProperties.priceLineWidth": 1,
				},

				studies_overrides: {
					// Volume — subdued fill
					"volume.volume.color.0": "rgba(90, 63, 122, 0.3)",
					"volume.volume.color.1": "rgba(45, 126, 247, 0.3)",
					"volume.volume.transparency": 70,
				},
			});

			widget = w;

			w.onChartReady(() => {
				if (disposed) return;
				console.log("[TerminalPriceChart] Chart ready");
				tvReady = true;

				// Enable percentage mode by default for fund comparison
				try {
					w.activeChart().getPanes()[0]?.setRightPriceScaleMode?.(2); // 2 = Percentage
				} catch {
					// Not critical
				}
			});
		}

		// Slight delay to let the DOM settle
		requestAnimationFrame(() => {
			if (!disposed) initWidget();
		});

		return () => {
			disposed = true;
			if (widget) {
				try {
					widget.remove();
				} catch {
					// Widget may already be destroyed
				}
				widget = null;
			}
			if (datafeed) {
				datafeed.destroy();
				datafeed = null;
			}
		};
	});

	// ── React to ticker changes ─────────────────────────────
	$effect(() => {
		const t = ticker;
		const w = widget;
		const ready = tvReady;
		if (!w || !ready || !t) return;

		try {
			w.activeChart().setSymbol(t);
			console.log("[TerminalPriceChart] Symbol changed to", t);
		} catch (err) {
			console.warn("[TerminalPriceChart] setSymbol failed:", err);
		}
	});
</script>

<div class="tpc-root">
	{#if tvError}
		<!-- Fallback when library not loaded -->
		<div class="tpc-fallback">
			<div class="tpc-fallback-ticker">{ticker || "---"}</div>
			<div class="tpc-fallback-msg">{tvError}</div>
			<div class="tpc-fallback-hint">
				The TradingView Advanced Charting Library is a B2B product.
				Contact TradingView to obtain the library files, then place
				them at <code>/static/charting_library/</code>.
			</div>
		</div>
	{:else}
		<!-- Status badge overlay -->
		{#if dataStatus !== "live"}
			<div class="tpc-status-overlay">
				<span
					class="tpc-status-badge"
					class:tpc-status-delayed={dataStatus === "delayed"}
					class:tpc-status-offline={dataStatus === "offline"}
				>{dataStatus.toUpperCase()}</span>
			</div>
		{/if}

		<!-- TradingView widget container -->
		<div class="tpc-chart" bind:this={containerEl}></div>

		<!-- Loading overlay (shown until chart is ready) -->
		{#if !tvReady && !tvError}
			<div class="tpc-loading">
				<div class="tpc-loading-text">Loading chart...</div>
			</div>
		{/if}
	{/if}
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
		position: relative;
		background: #05080f;
	}

	/* ── TradingView chart container ─────────────────────────── */
	.tpc-chart {
		position: relative;
		z-index: 0;
		flex: 1;
		min-height: 0;
		min-width: 0;
		width: 100%;
		overflow: hidden;
	}

	/* Force the TV iframe to match our background */
	.tpc-chart :global(iframe) {
		border: none !important;
	}

	/* ── Loading overlay ─────────────────────────────────────── */
	.tpc-loading {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		background: #05080f;
		z-index: 5;
	}
	.tpc-loading-text {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 11px;
		color: #3d4654;
		letter-spacing: 0.06em;
	}

	/* ── Status badge ────────────────────────────────────────── */
	.tpc-status-overlay {
		position: absolute;
		top: 8px;
		left: 10px;
		z-index: 10;
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

	/* ── Fallback (no library) ───────────────────────────────── */
	.tpc-fallback {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 12px;
		height: 100%;
		padding: 24px;
		text-align: center;
	}
	.tpc-fallback-ticker {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 18px;
		font-weight: 700;
		color: #2d7ef7;
		letter-spacing: 0.08em;
	}
	.tpc-fallback-msg {
		font-size: 12px;
		color: #5a6577;
		max-width: 400px;
		line-height: 1.5;
	}
	.tpc-fallback-hint {
		font-size: 10px;
		color: #3d4654;
		max-width: 380px;
		line-height: 1.4;
	}
	.tpc-fallback-hint code {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		color: #5a6577;
		padding: 1px 4px;
		background: rgba(255, 255, 255, 0.04);
	}
</style>
