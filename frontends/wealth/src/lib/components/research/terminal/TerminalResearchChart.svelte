<!--
  TerminalResearchChart — lightweight-charts v5 risk analytics workspace.

  Three stacked panes sharing a synced time axis:
    1. Drawdown (baseline, red)    — peak-to-trough from NAV running max
    2. GARCH volatility (line)     — conditional vol from fund_risk_metrics
    3. Regime probability (area)   — p_high_vol from macro_regime_history

  All three series are pre-computed server-side in TimescaleDB. The
  frontend only renders them via lightweight-charts — zero math here.
  Fetch is skipped when `instrumentId` is null (mock / unselected).

  Data source: GET /api/v1/risk/timeseries/{instrument_id}
  Chart library: lightweight-charts ^5 (already in use by TerminalPriceChart).
-->
<script lang="ts">
	import { getContext, onMount } from "svelte";
	import type { UTCTimestamp } from "lightweight-charts";
	import {
		fetchRiskTimeseries,
		type RiskTimeseries,
	} from "$lib/services/risk-engine-client";

	interface Props {
		ticker: string;
		tickerLabel: string;
		instrumentId?: string | null;
	}

	let { ticker, tickerLabel, instrumentId = null }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let drawdownEl: HTMLDivElement | undefined = $state();
	let volEl: HTMLDivElement | undefined = $state();
	let regimeEl: HTMLDivElement | undefined = $state();

	let charts: unknown[] = [];
	let loading = $state(false);
	let errorMessage = $state<string | null>(null);
	let riskData = $state<RiskTimeseries | null>(null);

	onMount(() => {
		let disposed = false;

		return () => {
			disposed = true;
			destroyCharts();
		};

		function destroyCharts() {
			for (const c of charts) {
				if (c && typeof (c as Record<string, unknown>).remove === "function") {
					(c as { remove: () => void }).remove();
				}
			}
			charts = [];
		}
	});

	// Re-fetch and re-render whenever the selected instrument changes.
	$effect(() => {
		const iid = instrumentId;
		if (!iid) {
			riskData = null;
			errorMessage = null;
			return;
		}

		let cancelled = false;
		loading = true;
		errorMessage = null;

		(async () => {
			try {
				const data = await fetchRiskTimeseries(iid, getToken);
				if (!cancelled) {
					riskData = data;
				}
			} catch (err) {
				if (!cancelled) {
					riskData = null;
					errorMessage = err instanceof Error ? err.message : "Failed to fetch risk timeseries";
				}
			} finally {
				if (!cancelled) loading = false;
			}
		})();

		return () => {
			cancelled = true;
		};
	});

	// Render panes whenever riskData or container elements change.
	$effect(() => {
		const data = riskData;
		const dd = drawdownEl;
		const vl = volEl;
		const rg = regimeEl;
		if (!data || !dd || !vl || !rg) return;

		let disposed = false;

		(async () => {
			const lc = await import("lightweight-charts");
			if (disposed) return;

			// Tear down previous charts before rebuilding
			for (const c of charts) {
				if (c && typeof (c as Record<string, unknown>).remove === "function") {
					(c as { remove: () => void }).remove();
				}
			}
			charts = [];

			const baseLayout = {
				background: { color: "transparent" },
				textColor: "#5a6577",
				fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
				fontSize: 9,
			};
			const baseGrid = {
				vertLines: { color: "rgba(255, 255, 255, 0.03)" },
				horzLines: { color: "rgba(255, 255, 255, 0.03)" },
			};
			const baseTimeScale = {
				borderColor: "rgba(255, 255, 255, 0.06)",
				timeVisible: false,
				secondsVisible: false,
			};

			// ── Pane 1: Drawdown (baseline red) ─────────────
			const ddChart = lc.createChart(dd, {
				autoSize: true,
				layout: baseLayout,
				grid: baseGrid,
				rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.08 } },
				timeScale: baseTimeScale,
				crosshair: {
					vertLine: { color: "rgba(239, 68, 68, 0.3)" },
					horzLine: { color: "rgba(239, 68, 68, 0.3)" },
				},
			});
			const ddSeries = ddChart.addSeries(lc.BaselineSeries, {
				baseValue: { type: "price", price: 0 },
				topLineColor: "rgba(34, 197, 94, 0.0)",
				topFillColor1: "rgba(34, 197, 94, 0.00)",
				topFillColor2: "rgba(34, 197, 94, 0.00)",
				bottomLineColor: "#ef4444",
				bottomFillColor1: "rgba(239, 68, 68, 0.20)",
				bottomFillColor2: "rgba(239, 68, 68, 0.02)",
				lineWidth: 2,
				priceLineVisible: false,
				lastValueVisible: true,
				priceFormat: { type: "price", precision: 2, minMove: 0.01 },
			});
			ddSeries.setData(data.drawdown.map((p) => ({ time: p.time as unknown as UTCTimestamp, value: p.value })));
			ddChart.timeScale().fitContent();

			// ── Pane 2: GARCH Volatility (purple line) ──────
			const vlChart = lc.createChart(vl, {
				autoSize: true,
				layout: baseLayout,
				grid: baseGrid,
				rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.15, bottom: 0.1 } },
				timeScale: baseTimeScale,
				crosshair: {
					vertLine: { color: "rgba(139, 92, 246, 0.3)" },
					horzLine: { color: "rgba(139, 92, 246, 0.3)" },
				},
			});
			const vlSeries = vlChart.addSeries(lc.LineSeries, {
				color: "#8b5cf6",
				lineWidth: 2,
				priceLineVisible: false,
				lastValueVisible: true,
				priceFormat: { type: "price", precision: 2, minMove: 0.01 },
			});
			vlSeries.setData(
				data.volatilityGarch.map((p) => ({ time: p.time as unknown as UTCTimestamp, value: p.value })),
			);
			vlChart.timeScale().fitContent();

			// ── Pane 3: Regime Probability (grey area) ──────
			const rgChart = lc.createChart(rg, {
				autoSize: true,
				layout: baseLayout,
				grid: baseGrid,
				rightPriceScale: {
					borderVisible: false,
					scaleMargins: { top: 0.08, bottom: 0.08 },
				},
				timeScale: { ...baseTimeScale, timeVisible: true },
				crosshair: {
					vertLine: { color: "rgba(90, 101, 119, 0.4)" },
					horzLine: { color: "rgba(90, 101, 119, 0.4)" },
				},
			});
			const rgSeries = rgChart.addSeries(lc.AreaSeries, {
				topColor: "rgba(202, 138, 4, 0.30)",
				bottomColor: "rgba(202, 138, 4, 0.02)",
				lineColor: "#ca8a04",
				lineWidth: 1,
				priceLineVisible: false,
				lastValueVisible: true,
				priceFormat: { type: "price", precision: 2, minMove: 0.01 },
			});
			rgSeries.setData(
				data.regimeProb.map((p) => ({ time: p.time as unknown as UTCTimestamp, value: p.value })),
			);
			rgChart.timeScale().fitContent();

			// ── Time-axis sync ──────────────────────────────
			// When user scrolls/zooms one pane, mirror the visible range
			// on the other two. Guard against feedback loops with a flag.
			let syncing = false;
			const all = [ddChart, vlChart, rgChart];
			for (const source of all) {
				source.timeScale().subscribeVisibleLogicalRangeChange((range: unknown) => {
					if (!range || syncing) return;
					syncing = true;
					for (const target of all) {
						if (target === source) continue;
						target.timeScale().setVisibleLogicalRange(range as { from: number; to: number });
					}
					syncing = false;
				});
			}

			charts = [ddChart, vlChart, rgChart];
		})();

		return () => {
			disposed = true;
		};
	});

	// ── Header summary numbers ───────────────────────────
	const summary = $derived.by(() => {
		if (!riskData) return null;
		const maxDd = riskData.drawdown.length
			? Math.min(...riskData.drawdown.map((p) => p.value))
			: null;
		const lastVol = riskData.volatilityGarch.length
			? riskData.volatilityGarch[riskData.volatilityGarch.length - 1]!.value
			: null;
		const lastRegime = riskData.regimeProb.length
			? riskData.regimeProb[riskData.regimeProb.length - 1]
			: null;
		return { maxDd, lastVol, lastRegime };
	});
</script>

<div class="rc-root">
	<div class="rc-header">
		<div class="rc-header-left">
			<span class="rc-ticker">{ticker || "---"}</span>
			<span class="rc-label">{tickerLabel}</span>
		</div>
		<div class="rc-header-right">
			{#if loading}
				<span class="rc-tag">Loading risk series&hellip;</span>
			{:else if summary}
				<span class="rc-summary">
					MAX DD
					<strong class="neg">{summary.maxDd != null ? summary.maxDd.toFixed(2) + "%" : "—"}</strong>
				</span>
				<span class="rc-summary">
					GARCH VOL
					<strong class="purple">{summary.lastVol != null ? summary.lastVol.toFixed(2) + "%" : "—"}</strong>
				</span>
				<span class="rc-summary">
					REGIME
					<strong class="amber">{summary.lastRegime?.regime ?? "—"}</strong>
				</span>
			{/if}
		</div>
	</div>

	{#if !instrumentId}
		<div class="rc-placeholder">
			<div class="rc-placeholder-title">SELECT AN INSTRUMENT</div>
			<div class="rc-placeholder-sub">
				Pick a fund from the asset browser to render<br />
				drawdown, GARCH volatility and macro regime overlays.
			</div>
		</div>
	{:else if errorMessage}
		<div class="rc-placeholder">
			<div class="rc-placeholder-title neg">RISK DATA UNAVAILABLE</div>
			<div class="rc-placeholder-sub">{errorMessage}</div>
		</div>
	{:else}
		<div class="rc-pane">
			<div class="rc-pane-label">DRAWDOWN</div>
			<div class="rc-pane-chart" bind:this={drawdownEl}></div>
		</div>
		<div class="rc-pane">
			<div class="rc-pane-label">GARCH VOLATILITY</div>
			<div class="rc-pane-chart" bind:this={volEl}></div>
		</div>
		<div class="rc-pane">
			<div class="rc-pane-label">MACRO REGIME P(HIGH VOL)</div>
			<div class="rc-pane-chart" bind:this={regimeEl}></div>
		</div>
	{/if}
</div>

<style>
	.rc-root {
		width: 100%;
		height: 100%;
		background: #05080f;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.rc-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 12px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
		flex-shrink: 0;
		height: 36px;
	}

	.rc-header-left {
		display: flex;
		align-items: baseline;
		gap: 10px;
		min-width: 0;
	}

	.rc-ticker {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 13px;
		font-weight: 800;
		color: #e2e8f0;
		letter-spacing: 0.04em;
	}

	.rc-label {
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		color: #5a6577;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.rc-header-right {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-shrink: 0;
	}

	.rc-summary {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 9px;
		color: #5a6577;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		display: inline-flex;
		gap: 4px;
		align-items: baseline;
	}

	.rc-summary strong {
		font-size: 11px;
		font-weight: 700;
		color: #e2e8f0;
		font-variant-numeric: tabular-nums;
	}

	.rc-tag {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 9px;
		color: #3a4455;
		letter-spacing: 0.06em;
	}

	/* ── Panes ───────────────────────────────────────────── */
	.rc-pane {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
		border-bottom: 1px solid rgba(255, 255, 255, 0.04);
	}
	.rc-pane:last-child {
		border-bottom: none;
	}

	.rc-pane-label {
		flex-shrink: 0;
		padding: 4px 10px 2px;
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		color: #3a4455;
		text-transform: uppercase;
	}

	.rc-pane-chart {
		flex: 1;
		min-height: 0;
		min-width: 0;
		width: 100%;
		position: relative;
	}

	/* ── Placeholder ─────────────────────────────────────── */
	.rc-placeholder {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 8px;
		padding: 32px;
		text-align: center;
	}

	.rc-placeholder-title {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.12em;
		color: #5a6577;
	}

	.rc-placeholder-sub {
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		color: #3a4455;
		line-height: 1.5;
	}

	.neg { color: #ef4444; }
	.purple { color: #8b5cf6; }
	.amber { color: #ca8a04; }
</style>
