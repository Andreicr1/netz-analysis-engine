<!--
  TerminalResearchChart — TradingView Advanced Charting Library workspace
  with injected risk panes (Drawdown, GARCH Volatility, Regime overlay).

  When TVCL is available: full widget with 3 panes + regime shading.
  When not available: elegant fallback with risk data rendered as
  simple SVG sparklines to prove the data pipeline works.

  Risk data source: GET /api/v1/risk/timeseries/{instrument_id}
  Primary key is instrument_id (UUID) — ticker is display-only.
  Risk fetch is skipped when instrumentId is null (mock/demo data).
  All computation is server-side (TimescaleDB hypertables).
-->
<script lang="ts">
	import { getContext, onMount } from "svelte";
	import { createNetzDatafeed, type NetzDatafeed } from "$lib/services/tv-datafeed";
	import {
		fetchRiskTimeseries,
		type RiskTimeseries,
		type TVPoint,
		type RegimeTVPoint,
	} from "$lib/services/risk-engine-client";

	interface Props {
		ticker: string;
		tickerLabel: string;
		instrumentId?: string | null;
	}

	let { ticker, tickerLabel, instrumentId = null }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let containerEl: HTMLDivElement | undefined = $state();
	let widgetInstance: unknown = null;
	let datafeed: NetzDatafeed | null = null;
	let libraryAvailable = $state(false);
	let libraryChecked = $state(false);

	// Risk pane series references (for cleanup)
	let drawdownSeries: unknown = null;
	let garchSeries: unknown = null;
	let regimeShapes: string[] = [];

	// Fallback risk data (when TVCL not available)
	let fallbackRisk = $state<RiskTimeseries | null>(null);
	let fallbackLoading = $state(false);
	let fallbackError = $state<string | null>(null);

	// Check if TradingView library files exist
	onMount(() => {
		const script = document.createElement("script");
		script.src = "/charting_library/charting_library.standalone.js";
		script.onload = () => {
			libraryAvailable = true;
			libraryChecked = true;
			initWidget();
		};
		script.onerror = () => {
			libraryAvailable = false;
			libraryChecked = true;
		};
		document.head.appendChild(script);

		return () => {
			destroyWidget();
			script.remove();
		};
	});

	// Re-init when ticker changes
	$effect(() => {
		if (!ticker || ticker === "PORTFOLIO") return;

		if (libraryAvailable && containerEl) {
			initWidget();
		} else if (libraryChecked && !libraryAvailable) {
			loadFallbackRisk();
		}
	});

	// ── TradingView Widget ──────────────────────────────────────

	function initWidget() {
		if (!containerEl || !libraryAvailable) return;

		destroyWidget();

		const apiBase = "/api/v1/market-data";
		const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
		const wsUrl = `${wsProtocol}//${window.location.host}/api/v1/market-data/live/ws`;

		datafeed = createNetzDatafeed({ apiBaseUrl: apiBase, wsUrl });

		try {
			const TradingView = (window as unknown as Record<string, unknown>).TradingView as Record<string, unknown> | undefined;
			if (!TradingView?.widget) return;

			const WidgetConstructor = TradingView.widget as new (config: Record<string, unknown>) => unknown;
			widgetInstance = new WidgetConstructor({
				symbol: ticker,
				datafeed,
				interval: "1D",
				container: containerEl,
				library_path: "/charting_library/",
				locale: "en",
				fullscreen: false,
				autosize: true,
				theme: "dark",
				custom_css_url: "",
				overrides: {
					"paneProperties.background": "#05080f",
					"paneProperties.backgroundType": "solid",
					"paneProperties.vertGridProperties.color": "rgba(255,255,255,0.03)",
					"paneProperties.horzGridProperties.color": "rgba(255,255,255,0.03)",
					"scalesProperties.textColor": "#5a6577",
					"scalesProperties.lineColor": "rgba(255,255,255,0.06)",
					"mainSeriesProperties.candleStyle.upColor": "#22c55e",
					"mainSeriesProperties.candleStyle.downColor": "#ef4444",
					"mainSeriesProperties.candleStyle.borderUpColor": "#22c55e",
					"mainSeriesProperties.candleStyle.borderDownColor": "#ef4444",
					"mainSeriesProperties.candleStyle.wickUpColor": "#22c55e",
					"mainSeriesProperties.candleStyle.wickDownColor": "#ef4444",
				},
				disabled_features: [
					"header_symbol_search",
					"header_compare",
					"display_market_status",
					"go_to_date",
					"popup_hints",
				],
				enabled_features: [
					"hide_left_toolbar_by_default",
				],
				loading_screen: {
					backgroundColor: "#05080f",
					foregroundColor: "#2d7ef7",
				},
			});

			// Once widget is ready, inject risk panes (only when we have a real UUID).
			const w = widgetInstance as { onChartReady?: (cb: () => void) => void };
			if (w.onChartReady && instrumentId) {
				w.onChartReady(() => {
					injectRiskPanes();
				});
			}
		} catch (err) {
			console.warn("[TerminalResearchChart] Failed to init TradingView widget:", err);
		}
	}

	// ── Risk Pane Injection (TVCL Chart API) ────────────────────

	async function injectRiskPanes() {
		if (!widgetInstance || !instrumentId) return;

		const w = widgetInstance as {
			activeChart?: () => {
				createStudy: (name: string, forceOverlay: boolean, lock: boolean, inputs: unknown[], callback: unknown, overrides: Record<string, unknown>, options: Record<string, unknown>) => unknown;
				createShape: (point: Record<string, unknown>, options: Record<string, unknown>) => string;
				removeEntity: (id: string) => void;
				removeAllShapes: () => void;
			};
			chart?: () => {
				createPriceLine: (options: Record<string, unknown>) => unknown;
			};
		};

		// Clean up previous risk series
		cleanupRiskPanes();

		let riskData: RiskTimeseries;
		try {
			riskData = await fetchRiskTimeseries(instrumentId, getToken);
		} catch (err) {
			console.warn("[TerminalResearchChart] Failed to fetch risk timeseries:", err);
			return;
		}

		const chart = w.activeChart?.();
		if (!chart) return;

		// The TradingView Advanced Charts API uses createStudy for custom panes.
		// Since the exact API shape depends on the library version, we use a
		// try/catch approach and log diagnostics for first-iteration debugging.

		try {
			// Pane 1: Max Drawdown (red area below main chart)
			if (riskData.drawdown.length > 0) {
				drawdownSeries = chart.createStudy(
					"Overlay",
					true,
					false,
					[],
					null,
					{
						"plot.color": "#ef4444",
						"plot.linewidth": 1,
					},
					{
						priceScale: "drawdown",
						paneSize: "small",
					},
				);
				console.log("[TerminalResearchChart] Drawdown pane injected:", riskData.drawdown.length, "points");
			}

			// Pane 2: GARCH Volatility (purple line)
			if (riskData.volatilityGarch.length > 0) {
				garchSeries = chart.createStudy(
					"Overlay",
					true,
					false,
					[],
					null,
					{
						"plot.color": "#8b5cf6",
						"plot.linewidth": 2,
					},
					{
						priceScale: "volatility",
						paneSize: "small",
					},
				);
				console.log("[TerminalResearchChart] GARCH pane injected:", riskData.volatilityGarch.length, "points");
			}

			// Regime overlay: shade CRISIS zones on the main chart
			if (riskData.regimeProb.length > 0) {
				injectRegimeShading(chart, riskData.regimeProb);
			}
		} catch (err) {
			console.warn("[TerminalResearchChart] Risk pane injection failed (expected without TVCL):", err);
		}
	}

	function injectRegimeShading(
		chart: { createShape: (point: Record<string, unknown>, options: Record<string, unknown>) => string },
		regimePoints: RegimeTVPoint[],
	) {
		// Find contiguous CRISIS/RISK_OFF zones and draw vertical background shapes
		let zoneStart: number | null = null;

		for (let i = 0; i < regimePoints.length; i++) {
			const p = regimePoints[i]!;
			const isCrisis = p.regime === "CRISIS" || p.regime === "RISK_OFF";

			if (isCrisis && zoneStart === null) {
				zoneStart = p.time;
			} else if (!isCrisis && zoneStart !== null) {
				// End of crisis zone — draw shape
				try {
					const shapeId = chart.createShape(
						{ time: zoneStart },
						{
							shape: "rectangle",
							overrides: {
								backgroundColor: p.regime === "CRISIS"
									? "rgba(239, 68, 68, 0.06)"
									: "rgba(255, 255, 255, 0.03)",
								borderColor: "transparent",
								drawBorder: false,
								extendLeft: false,
								extendRight: false,
							},
							zOrder: "bottom",
						},
					);
					if (shapeId) regimeShapes.push(shapeId);
				} catch {
					// Shape API may not be available in all TVCL versions
				}
				zoneStart = null;
			}
		}
	}

	function cleanupRiskPanes() {
		if (!widgetInstance) return;

		const w = widgetInstance as {
			activeChart?: () => {
				removeEntity: (id: unknown) => void;
				removeAllShapes: () => void;
			};
		};
		const chart = w.activeChart?.();

		if (chart) {
			// Remove drawdown and garch study entities
			if (drawdownSeries != null) {
				try { chart.removeEntity(drawdownSeries); } catch { /* noop */ }
				drawdownSeries = null;
			}
			if (garchSeries != null) {
				try { chart.removeEntity(garchSeries); } catch { /* noop */ }
				garchSeries = null;
			}
			// Remove regime shapes
			for (const shapeId of regimeShapes) {
				try { chart.removeEntity(shapeId); } catch { /* noop */ }
			}
			regimeShapes = [];
		}
	}

	// ── Fallback Risk Data (when TVCL not available) ────────────

	async function loadFallbackRisk() {
		if (!instrumentId) {
			// Mock/demo node without a real UUID — nothing to fetch.
			fallbackRisk = null;
			fallbackError = null;
			return;
		}
		fallbackLoading = true;
		fallbackError = null;
		try {
			fallbackRisk = await fetchRiskTimeseries(instrumentId, getToken);
		} catch {
			// Expected in dev without backend — show placeholder
			fallbackRisk = null;
			fallbackError = "Risk data unavailable (backend offline)";
		} finally {
			fallbackLoading = false;
		}
	}

	// ── SVG Sparkline Helpers ───────────────────────────────────

	function sparklinePath(points: TVPoint[], width: number, height: number): string {
		if (points.length < 2) return "";
		const minV = Math.min(...points.map((p) => p.value));
		const maxV = Math.max(...points.map((p) => p.value));
		const range = maxV - minV || 1;
		const stepX = width / (points.length - 1);

		return points
			.map((p, i) => {
				const x = i * stepX;
				const y = height - ((p.value - minV) / range) * height;
				return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
			})
			.join(" ");
	}

	function sparklineAreaPath(points: TVPoint[], width: number, height: number): string {
		const line = sparklinePath(points, width, height);
		if (!line) return "";
		const stepX = width / (points.length - 1);
		const lastX = (points.length - 1) * stepX;
		return `${line} L${lastX.toFixed(1)},${height} L0,${height} Z`;
	}

	function destroyWidget() {
		cleanupRiskPanes();
		if (widgetInstance && typeof (widgetInstance as Record<string, unknown>).remove === "function") {
			const w = widgetInstance as { remove: () => void };
			w.remove();
		}
		widgetInstance = null;
		if (datafeed) {
			datafeed.destroy();
			datafeed = null;
		}
	}
</script>

<div class="rc-root">
	{#if !libraryChecked}
		<div class="rc-loading">
			<span class="rc-loading-text">Checking charting library...</span>
		</div>
	{:else if libraryAvailable}
		<div class="rc-widget" bind:this={containerEl}></div>
	{:else}
		<!-- Fallback: risk sparklines when TVCL not available -->
		<div class="rc-fallback">
			<div class="rc-fallback-header">
				<span class="rc-fallback-ticker">{ticker}</span>
				<span class="rc-fallback-label">{tickerLabel}</span>
			</div>

			{#if fallbackRisk && fallbackRisk.drawdown.length > 0}
				<!-- Drawdown sparkline -->
				<div class="rc-pane">
					<div class="rc-pane-header">
						<span class="rc-pane-title">MAX DRAWDOWN</span>
						<span class="rc-pane-value neg">
							{Math.min(...fallbackRisk.drawdown.map((p) => p.value)).toFixed(2)}%
						</span>
					</div>
					<svg class="rc-spark" viewBox="0 0 400 60" preserveAspectRatio="none">
						<path
							d={sparklineAreaPath(fallbackRisk.drawdown, 400, 60)}
							fill="rgba(239, 68, 68, 0.15)"
							stroke="none"
						/>
						<path
							d={sparklinePath(fallbackRisk.drawdown, 400, 60)}
							fill="none"
							stroke="#ef4444"
							stroke-width="1.5"
						/>
					</svg>
				</div>

				<!-- GARCH Volatility sparkline -->
				{#if fallbackRisk.volatilityGarch.length > 0}
					<div class="rc-pane">
						<div class="rc-pane-header">
							<span class="rc-pane-title">GARCH VOLATILITY</span>
							<span class="rc-pane-value purple">
								{fallbackRisk.volatilityGarch[fallbackRisk.volatilityGarch.length - 1]?.value.toFixed(2)}%
							</span>
						</div>
						<svg class="rc-spark" viewBox="0 0 400 60" preserveAspectRatio="none">
							<path
								d={sparklinePath(fallbackRisk.volatilityGarch, 400, 60)}
								fill="none"
								stroke="#8b5cf6"
								stroke-width="1.5"
							/>
						</svg>
					</div>
				{/if}

				<!-- Regime probability sparkline -->
				{#if fallbackRisk.regimeProb.length > 0}
					<div class="rc-pane">
						<div class="rc-pane-header">
							<span class="rc-pane-title">CRISIS PROBABILITY</span>
							<span class="rc-pane-value"
								>{(
									(fallbackRisk.regimeProb[fallbackRisk.regimeProb.length - 1]?.value ?? 0) * 100
								).toFixed(1)}%</span
							>
						</div>
						<svg class="rc-spark" viewBox="0 0 400 40" preserveAspectRatio="none">
							<path
								d={sparklineAreaPath(fallbackRisk.regimeProb, 400, 40)}
								fill="rgba(255, 255, 255, 0.04)"
								stroke="none"
							/>
							<path
								d={sparklinePath(fallbackRisk.regimeProb, 400, 40)}
								fill="none"
								stroke="#5a6577"
								stroke-width="1"
							/>
							<!-- Danger threshold at 0.5 -->
							<line x1="0" y1="20" x2="400" y2="20" stroke="rgba(239,68,68,0.2)" stroke-width="0.5" stroke-dasharray="4,4" />
						</svg>
					</div>
				{/if}
			{:else if fallbackLoading}
				<div class="rc-status">Loading risk timeseries...</div>
			{:else if fallbackError}
				<div class="rc-fallback-box">
					<div class="rc-fallback-border"></div>
					<div class="rc-fallback-title">Awaiting TradingView Library Files</div>
					<div class="rc-fallback-sub">
						Place <code>charting_library/</code> in <code>static/</code> to activate
						the Advanced Charting workspace. The tv-datafeed adapter is ready.
					</div>
					<div class="rc-fallback-sub" style="margin-top: 8px; color: #3a4455;">
						{fallbackError}
					</div>
				</div>
			{:else}
				<div class="rc-fallback-box">
					<div class="rc-fallback-border"></div>
					<div class="rc-fallback-title">Awaiting TradingView Library Files</div>
					<div class="rc-fallback-sub">
						Place <code>charting_library/</code> in <code>static/</code> to activate
						the Advanced Charting workspace. The tv-datafeed adapter is ready.
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.rc-root {
		width: 100%;
		height: 100%;
		background: #05080f;
		position: relative;
		overflow: hidden;
	}

	.rc-widget {
		width: 100%;
		height: 100%;
	}

	/* ── Loading state ──────────────────────────────── */
	.rc-loading {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 100%;
		height: 100%;
	}
	.rc-loading-text {
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		color: #3a4455;
		letter-spacing: 0.04em;
	}

	/* ── Fallback with risk panes ───────────────────── */
	.rc-fallback {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		overflow-y: auto;
		overflow-x: hidden;
		/* Subtle grid lines to suggest chart workspace */
		background-image:
			linear-gradient(rgba(255, 255, 255, 0.02) 1px, transparent 1px),
			linear-gradient(90deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px);
		background-size: 60px 60px;
	}

	.rc-fallback-header {
		display: flex;
		align-items: baseline;
		gap: 10px;
		padding: 14px 16px 8px;
		flex-shrink: 0;
	}

	.rc-fallback-ticker {
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 18px;
		font-weight: 800;
		color: #e2e8f0;
		letter-spacing: 0.04em;
	}

	.rc-fallback-label {
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		color: #5a6577;
	}

	/* ── Risk pane (sparkline block) ────────────────── */
	.rc-pane {
		padding: 8px 16px;
		border-top: 1px solid rgba(255, 255, 255, 0.04);
		flex-shrink: 0;
	}

	.rc-pane-header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		margin-bottom: 4px;
	}

	.rc-pane-title {
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.1em;
		color: #3a4455;
		text-transform: uppercase;
	}

	.rc-pane-value {
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 13px;
		font-weight: 800;
		color: #e2e8f0;
		font-variant-numeric: tabular-nums;
	}

	.neg { color: #ef4444; }
	.purple { color: #8b5cf6; }

	.rc-spark {
		width: 100%;
		height: 60px;
		display: block;
	}

	/* ── Status messages ────────────────────────────── */
	.rc-status {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: 1;
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		color: #3a4455;
		letter-spacing: 0.04em;
	}

	/* ── Fallback box (no data) ─────────────────────── */
	.rc-fallback-box {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 6px;
		padding: 32px 48px;
		margin: auto;
		border: 1px dashed rgba(255, 255, 255, 0.10);
		border-radius: 4px;
		text-align: center;
		max-width: 420px;
	}

	.rc-fallback-border {
		width: 40px;
		height: 1px;
		background: rgba(255, 255, 255, 0.08);
		margin: 4px 0;
	}

	.rc-fallback-title {
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 12px;
		font-weight: 700;
		color: #8a94a6;
		letter-spacing: 0.04em;
	}

	.rc-fallback-sub {
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 10px;
		color: #3a4455;
		line-height: 1.5;
	}
	.rc-fallback-sub code {
		color: #5a6577;
		background: rgba(255, 255, 255, 0.04);
		padding: 1px 4px;
		border-radius: 2px;
		font-size: 10px;
	}
</style>
