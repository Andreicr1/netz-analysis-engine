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
	import { formatNumber } from "@investintell/ui";
	import {
		createTerminalLightweightChartOptions,
		terminalLWSeriesColors,
	} from "@investintell/ui";
	import { getContext, onMount } from "svelte";
	import type { UTCTimestamp } from "lightweight-charts";
	import {
		fetchRiskTimeseries,
		type RiskTimeseries,
	} from "$wealth/services/risk-engine-client";

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

			const sc = terminalLWSeriesColors();

			// ── Pane 1: Drawdown (baseline red) ─────────────
			const ddOpts = createTerminalLightweightChartOptions({
				fontSize: 9,
				crosshairColor: sc.drawdown.bottomLineColor,
			});
			const ddChart = lc.createChart(dd, { autoSize: true, ...ddOpts });
			const ddSeries = ddChart.addSeries(lc.BaselineSeries, {
				baseValue: { type: "price", price: 0 },
				...sc.drawdown,
				lineWidth: 2,
				priceLineVisible: false,
				lastValueVisible: true,
				priceFormat: { type: "price", precision: 2, minMove: 0.01 },
			});
			ddSeries.setData(data.drawdown.map((p) => ({ time: p.time as unknown as UTCTimestamp, value: p.value })));
			ddChart.timeScale().fitContent();

			// ── Pane 2: GARCH Volatility (violet line) ──────
			const vlOpts = createTerminalLightweightChartOptions({
				fontSize: 9,
				scaleMargins: { top: 0.15, bottom: 0.1 },
				crosshairColor: sc.volatility.color,
			});
			const vlChart = lc.createChart(vl, { autoSize: true, ...vlOpts });
			const vlSeries = vlChart.addSeries(lc.LineSeries, {
				...sc.volatility,
				lineWidth: 2,
				priceLineVisible: false,
				lastValueVisible: true,
				priceFormat: { type: "price", precision: 2, minMove: 0.01 },
			});
			vlSeries.setData(
				data.volatilityGarch.map((p) => ({ time: p.time as unknown as UTCTimestamp, value: p.value })),
			);
			vlChart.timeScale().fitContent();

			// ── Pane 3: Regime Probability (amber area) ──────
			const rgOpts = createTerminalLightweightChartOptions({
				fontSize: 9,
				timeVisible: true,
			});
			const rgChart = lc.createChart(rg, { autoSize: true, ...rgOpts });
			const rgSeries = rgChart.addSeries(lc.AreaSeries, {
				...sc.regime,
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
					<strong class="neg">{summary.maxDd != null ? formatNumber(summary.maxDd, 2) + "%" : "—"}</strong>
				</span>
				<span class="rc-summary">
					FORWARD VOL
					<strong class="purple">{summary.lastVol != null ? formatNumber(summary.lastVol, 2) + "%" : "—"}</strong>
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
				drawdown, conditional volatility and regime overlays.
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
			<div class="rc-pane-label">CONDITIONAL VOLATILITY</div>
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
		background: var(--terminal-bg-panel);
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.rc-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 12px;
		border-bottom: var(--terminal-border-hairline);
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
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-14);
		font-weight: 800;
		color: var(--terminal-fg-primary);
		letter-spacing: 0.04em;
	}

	.rc-label {
		font-family: var(--terminal-font-sans);
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-tertiary);
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
		font-family: var(--terminal-font-mono);
		font-size: 9px;
		color: var(--terminal-fg-tertiary);
		letter-spacing: 0.08em;
		text-transform: uppercase;
		display: inline-flex;
		gap: 4px;
		align-items: baseline;
	}

	.rc-summary strong {
		font-size: 11px;
		font-weight: 700;
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
	}

	.rc-tag {
		font-family: var(--terminal-font-mono);
		font-size: 9px;
		color: var(--terminal-fg-muted);
		letter-spacing: 0.06em;
	}

	/* ── Panes ───────────────────────────────────────────── */
	.rc-pane {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
		border-bottom: var(--terminal-border-hairline);
	}
	.rc-pane:last-child {
		border-bottom: none;
	}

	.rc-pane-label {
		flex-shrink: 0;
		padding: 4px 10px 2px;
		font-family: var(--terminal-font-mono);
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		color: var(--terminal-fg-muted);
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
		font-family: var(--terminal-font-mono);
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.12em;
		color: var(--terminal-fg-tertiary);
	}

	.rc-placeholder-sub {
		font-family: var(--terminal-font-sans);
		font-size: 11px;
		color: var(--terminal-fg-muted);
		line-height: 1.5;
	}

	.neg { color: var(--terminal-status-error); }
	.purple { color: var(--terminal-accent-violet); }
	.amber { color: var(--terminal-accent-amber); }
</style>
