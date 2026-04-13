<!--
  /portfolio/live -- Phase 5 Live Workbench (Session A).

  2-zone grid layout: watchlist (240px left) + chart/holdings right.
  Wired to MarketDataStore via TERMINAL_MARKET_DATA_KEY context.
  Real-time Tiingo WebSocket prices via existing infrastructure.

  URL state (DL15 -- Zero localStorage):
    ?portfolio=<id>   -- the currently-selected live portfolio
-->
<script lang="ts">
	import { page } from "$app/state";
	import { goto } from "$app/navigation";
	import { resolve } from "$app/paths";
	import { getContext } from "svelte";
	import { PanelErrorState } from "@investintell/ui/runtime";
	import { createClientApiClient } from "$lib/api/client";
	import type { MarketDataStore } from "$lib/stores/market-data.svelte";
	import { TERMINAL_MARKET_DATA_KEY } from "$lib/components/portfolio/live/workbench-state";
	import type { PageData } from "./$types";
	import type {
		ModelPortfolio,
		InstrumentWeight,
	} from "$lib/types/model-portfolio";

	// Components
	import Watchlist, {
		type WatchlistItem,
	} from "$lib/components/terminal/live/Watchlist.svelte";
	import ChartToolbar from "$lib/components/terminal/live/ChartToolbar.svelte";
	import PortfolioSummary from "$lib/components/terminal/live/PortfolioSummary.svelte";
	import HoldingsTable, {
		type HoldingRow,
	} from "$lib/components/terminal/live/HoldingsTable.svelte";
	import NewsFeed from "$lib/components/terminal/live/NewsFeed.svelte";
	import MacroRegimePanel from "$lib/components/terminal/live/MacroRegimePanel.svelte";
	import TradeLog from "$lib/components/terminal/live/TradeLog.svelte";
	import AlertStreamPanel from "$lib/components/terminal/live/AlertStreamPanel.svelte";
	import RebalanceFocusMode from "$lib/components/terminal/live/RebalanceFocusMode.svelte";
	import TerminalPriceChart from "$lib/components/portfolio/live/charts/TerminalPriceChart.svelte";
	import type { BarData, LiveTick } from "$lib/components/portfolio/live/charts/TerminalPriceChart.svelte";

	let { data }: { data: PageData } = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const marketStore = getContext<MarketDataStore>(TERMINAL_MARKET_DATA_KEY);
	const api = createClientApiClient(getToken);

	// ---- Portfolio selection (URL-driven) ----

	const portfolios = $derived((data.portfolios ?? []) as ModelPortfolio[]);
	const selectedId = $derived<string | null>(
		page.url.searchParams.get("portfolio"),
	);

	const selected = $derived.by(() => {
		if (!selectedId) return portfolios[0] ?? null;
		return portfolios.find((p) => p.id === selectedId) ?? portfolios[0] ?? null;
	});

	async function handlePortfolioSelect(portfolio: ModelPortfolio) {
		const params = new URLSearchParams(page.url.searchParams);
		params.set("portfolio", portfolio.id);
		const target = resolve(`/portfolio/live?${params.toString()}`);
		await goto(target, { replaceState: true, noScroll: true, keepFocus: true });
	}

	// ---- Instrument ticker resolution ----

	interface InstrumentInfo {
		instrument_id: string;
		ticker: string;
		name: string;
	}

	let instrumentMap = $state<Map<string, InstrumentInfo>>(new Map());

	// Fetch instruments to resolve instrument_id -> ticker
	$effect(() => {
		const _id = selected?.id;
		if (!_id) {
			instrumentMap = new Map();
			return;
		}
		let cancelled = false;
		api.get<Array<{ instrument_id: string; ticker: string | null; name: string }>>(
			"/instruments",
		)
			.then((instruments) => {
				if (cancelled) return;
				const m = new Map<string, InstrumentInfo>();
				for (const inst of instruments) {
					if (inst.ticker) {
						m.set(inst.instrument_id, {
							instrument_id: inst.instrument_id,
							ticker: inst.ticker,
							name: inst.name,
						});
					}
				}
				instrumentMap = m;
			})
			.catch(() => {
				// Instruments not available -- degrade gracefully
			});
		return () => {
			cancelled = true;
		};
	});

	// ---- Target funds + resolved tickers ----

	const targetFunds = $derived<InstrumentWeight[]>(
		selected?.fund_selection_schema?.funds ?? [],
	);

	function resolveTicker(instrumentId: string, fallbackName: string): string {
		return instrumentMap.get(instrumentId)?.ticker ?? fallbackName;
	}

	function resolveName(instrumentId: string, fallbackName: string): string {
		return instrumentMap.get(instrumentId)?.name ?? fallbackName;
	}

	// ---- Actual holdings ----

	interface ActualHoldingsData {
		source: string;
		holdings: Array<{
			instrument_id: string;
			fund_name: string;
			block_id: string;
			weight: number;
		}>;
		holdings_version: number;
		last_rebalanced_at: string | null;
	}

	let actualHoldingsData = $state<ActualHoldingsData | null>(null);

	$effect(() => {
		const pid = selected?.id;
		const _refresh = refreshToken; // re-fetch when trades are executed
		if (!pid) {
			actualHoldingsData = null;
			return;
		}
		let cancelled = false;
		api.get<ActualHoldingsData>(`/model-portfolios/${pid}/actual-holdings`)
			.then((res) => {
				if (!cancelled) actualHoldingsData = res;
			})
			.catch(() => {
				if (!cancelled) actualHoldingsData = null;
			});
		return () => {
			cancelled = true;
		};
	});

	// ---- Subscribe portfolio tickers to MarketDataStore ----

	$effect(() => {
		if (targetFunds.length === 0 || instrumentMap.size === 0) return;
		const tickers = targetFunds
			.map((f) => instrumentMap.get(f.instrument_id)?.ticker)
			.filter((t): t is string => !!t);
		if (tickers.length > 0) {
			marketStore.subscribe(tickers);
			marketStore.start();
		}
		return () => {
			if (tickers.length > 0) {
				marketStore.unsubscribe(tickers);
			}
		};
	});

	// ---- Watchlist items ----

	const watchlistItems = $derived<WatchlistItem[]>(
		targetFunds
			.map((f) => {
				const ticker = resolveTicker(f.instrument_id, "");
				if (!ticker) return null;
				return {
					ticker,
					name: resolveName(f.instrument_id, f.fund_name),
					instrument_id: f.instrument_id,
					weight: f.weight,
				};
			})
			.filter((item): item is WatchlistItem => item !== null),
	);

	// ---- Resolved tickers for news feed ----

	const resolvedTickers = $derived<string[]>(
		targetFunds
			.map((f) => instrumentMap.get(f.instrument_id)?.ticker)
			.filter((t): t is string => !!t),
	);

	// ---- Holdings table rows ----

	const holdingsRows = $derived.by<HoldingRow[]>(() => {
		const actual = actualHoldingsData?.holdings ?? [];
		const actualMap = new Map(actual.map((h) => [h.instrument_id, h.weight]));

		return targetFunds
			.map((f) => {
				const ticker = resolveTicker(f.instrument_id, "");
				if (!ticker) return null;
				return {
					instrument_id: f.instrument_id,
					fund_name: resolveName(f.instrument_id, f.fund_name),
					ticker,
					weight: actualMap.get(f.instrument_id) ?? f.weight,
					target_weight: f.weight,
				};
			})
			.filter((r): r is HoldingRow => r !== null);
	});

	// ---- Chart state ----

	type Timeframe = "1D" | "1W" | "1M" | "3M" | "1Y";
	let selectedTicker = $state<string | null>(null);
	let chartTimeframe = $state<Timeframe>("1M");
	let compareTicker = $state<string | null>(null);

	// Reset selection when portfolio changes
	$effect(() => {
		const _id = selected?.id;
		void _id;
		selectedTicker = null;
		compareTicker = null;
	});

	// Effective ticker for the chart (first instrument if none selected)
	const effectiveTicker = $derived(
		selectedTicker ?? watchlistItems[0]?.ticker ?? "",
	);

	const effectiveInstrumentName = $derived.by(() => {
		if (!effectiveTicker) return "";
		const item = watchlistItems.find(
			(w) => w.ticker.toUpperCase() === effectiveTicker.toUpperCase(),
		);
		return item?.name ?? effectiveTicker;
	});

	// Historical bars from REST quote endpoint
	let historicalBars = $state<BarData[]>([]);
	let portfolioNavBars = $state<BarData[]>([]);

	$effect(() => {
		const t = effectiveTicker;
		const _tf = chartTimeframe;
		if (!t) {
			historicalBars = [];
			return;
		}
		let cancelled = false;
		api.get<{
			ticker: string;
			interval: string;
			bars: Array<{ timestamp: string; open: number | null; high: number | null; low: number | null; close: number | null; volume: number }>;
			source: string;
		}>(`/market-data/historical/${encodeURIComponent(t)}`)
			.then((res) => {
				if (cancelled) return;
				historicalBars = (res.bars ?? [])
					.filter((b) => b.close != null)
					.map((b) => ({
						time: Math.floor(new Date(b.timestamp).getTime() / 1000),
						value: Number(b.close),
					}));
			})
			.catch(() => {
				if (!cancelled) historicalBars = [];
			});
		return () => {
			cancelled = true;
		};
	});

	// Load portfolio NAV series for overlay
	$effect(() => {
		const pid = selected?.id;
		if (!pid) {
			portfolioNavBars = [];
			return;
		}
		let cancelled = false;
		api.get<{
			portfolio_id: string;
			dates: string[];
			nav_series: number[];
			drawdown_series: number[];
			metrics: { sharpe: number | null; max_dd: number | null; ann_return: number | null; calmar: number | null };
		}>(`/model-portfolios/${pid}/nav-history`)
			.then((res) => {
				if (cancelled) return;
				if (res.dates && res.nav_series && res.dates.length > 0) {
					portfolioNavBars = res.dates.map((d: string, i: number) => ({
						time: Math.floor(new Date(d).getTime() / 1000),
						value: res.nav_series[i] ?? 0,
					}));
				} else {
					portfolioNavBars = [];
				}
			})
			.catch(() => {
				if (!cancelled) portfolioNavBars = [];
			});
		return () => {
			cancelled = true;
		};
	});

	// Live tick from MarketDataStore -> chart
	const lastTick = $derived.by((): LiveTick | null => {
		if (!effectiveTicker) return null;
		const tick = marketStore.priceMap.get(effectiveTicker.toUpperCase());
		if (!tick) return null;
		return {
			time: Math.floor(new Date(tick.timestamp).getTime() / 1000),
			value: tick.price,
		};
	});

	// Comparison NAV bars (placeholder: uses same quote endpoint)
	let compareNavBars = $state<BarData[]>([]);

	$effect(() => {
		const ct = compareTicker;
		if (!ct) {
			compareNavBars = [];
			return;
		}
		let cancelled = false;
		api.get<{
			ticker: string;
			interval: string;
			bars: Array<{ timestamp: string; open: number | null; high: number | null; low: number | null; close: number | null; volume: number }>;
			source: string;
		}>(`/market-data/historical/${encodeURIComponent(ct)}`)
			.then((res) => {
				if (cancelled) return;
				compareNavBars = (res.bars ?? [])
					.filter((b) => b.close != null)
					.map((b) => ({
						time: Math.floor(new Date(b.timestamp).getTime() / 1000),
						value: Number(b.close),
					}));
			})
			.catch(() => {
				if (!cancelled) compareNavBars = [];
			});
		return () => {
			cancelled = true;
		};
	});

	// Use compare bars as portfolioNavBars when comparing, else real NAV
	const effectiveNavBars = $derived(
		compareTicker ? compareNavBars : portfolioNavBars,
	);

	function handleTimeframeChange(tf: Timeframe) {
		chartTimeframe = tf;
	}

	function handleWatchlistSelect(ticker: string) {
		selectedTicker = ticker;
	}

	function handleHoldingsSelect(ticker: string) {
		selectedTicker = ticker;
	}

	function handleCompare(ticker: string) {
		compareTicker = ticker;
	}

	function handleClearCompare() {
		compareTicker = null;
	}

	// Data status for chart
	const dataStatus = $derived.by(() => {
		const s = marketStore.status;
		if (s === "connected") return "live" as const;
		if (s === "reconnecting" || s === "connecting") return "delayed" as const;
		return "offline" as const;
	});

	// ---- Refresh trigger (incremented after trade execution) ----

	let refreshToken = $state(0);

	// ---- Rebalance FocusMode (URL-driven) ----

	const showRebalance = $derived(page.url.searchParams.get("rebalance") === "open");

	function handleRebalanceOpen() {
		const params = new URLSearchParams(page.url.searchParams);
		params.set("rebalance", "open");
		goto(resolve(`/portfolio/live?${params.toString()}`), { replaceState: true, noScroll: true, keepFocus: true });
	}

	function handleRebalanceClose() {
		const params = new URLSearchParams(page.url.searchParams);
		params.delete("rebalance");
		goto(resolve(`/portfolio/live?${params.toString()}`), { replaceState: true, noScroll: true, keepFocus: true });
	}

	function handleRebalanceSuccess() {
		handleRebalanceClose();
		refreshToken++;
	}

	// ---- Portfolio summary data ----

	const portfolioAum = $derived(marketStore.totalAum);
	const instrumentCount = $derived(targetFunds.length);
	const lastRebalance = $derived(actualHoldingsData?.last_rebalanced_at ?? null);

	// Aggregate drift status
	const aggregateDrift = $derived.by((): "aligned" | "watch" | "breach" => {
		if (!actualHoldingsData?.holdings) return "aligned";
		const actualMap = new Map(
			actualHoldingsData.holdings.map((h) => [h.instrument_id, h.weight]),
		);
		let maxDrift = 0;
		for (const f of targetFunds) {
			const actual = actualMap.get(f.instrument_id) ?? f.weight;
			maxDrift = Math.max(maxDrift, Math.abs(actual - f.weight));
		}
		if (maxDrift >= 0.03) return "breach";
		if (maxDrift >= 0.02) return "watch";
		return "aligned";
	});

	// ---- Drift monitor data ----

	const isFallbackHoldings = $derived(
		actualHoldingsData?.source === "target_fallback",
	);

	const driftFunds = $derived.by(() => {
		const actual = actualHoldingsData?.holdings ?? [];
		const actualMap = new Map(actual.map((h) => [h.instrument_id, h.weight]));
		return targetFunds
			.map((f) => {
				const ticker = resolveTicker(f.instrument_id, "");
				if (!ticker) return null;
				return {
					instrument_id: f.instrument_id,
					fund_name: resolveName(f.instrument_id, f.fund_name),
					ticker,
					target_weight: f.weight,
					actual_weight: actualMap.get(f.instrument_id) ?? f.weight,
				};
			})
			.filter((r): r is NonNullable<typeof r> => r !== null);
	});

	// Convert drift breaches/watches to alert items for AlertStreamPanel
	interface DriftAlert {
		id: string;
		source: string;
		alert_type: string;
		severity: "info" | "warning" | "critical";
		title: string;
		subtitle: string | null;
		subject_kind: string;
		subject_id: string;
		subject_name: string | null;
		created_at: string;
		acknowledged_at: string | null;
		acknowledged_by: string | null;
		href: string | null;
	}

	const driftAlerts = $derived.by((): DriftAlert[] => {
		if (isFallbackHoldings) return [];
		return driftFunds
			.filter((f) => Math.abs(f.actual_weight - f.target_weight) >= 0.02)
			.map((f) => {
				const drift = f.actual_weight - f.target_weight;
				const absDrift = Math.abs(drift);
				const severity: "warning" | "critical" = absDrift >= 0.03 ? "critical" : "warning";
				const pct = (absDrift * 100).toFixed(1);
				const direction = drift > 0 ? "over" : "under";
				return {
					id: `drift-${f.instrument_id}`,
					source: "drift_monitor",
					alert_type: "drift_breach",
					severity,
					title: `${f.ticker} ${direction}weight by ${pct}pp`,
					subtitle: null,
					subject_kind: "instrument",
					subject_id: f.instrument_id,
					subject_name: f.fund_name,
					created_at: new Date().toISOString(),
					acknowledged_at: null,
					acknowledged_by: null,
					href: null,
				};
			});
	});

	// Portfolio dropdown
	let showDropdown = $state(false);

	function toggleDropdown() {
		showDropdown = !showDropdown;
	}

	function selectFromDropdown(p: ModelPortfolio) {
		showDropdown = false;
		handlePortfolioSelect(p);
	}
</script>

<svelte:head>
	<title>Live Workbench -- InvestIntell</title>
</svelte:head>

<svelte:boundary>
	{#if portfolios.length === 0}
		<div class="lw-empty">
			<span class="lw-empty-label">No live portfolios</span>
			<span class="lw-empty-sub">Activate a portfolio in the Builder to see it here.</span>
		</div>
	{:else}
		<div class="lw-shell">
			<!-- LEFT COLUMN: Watchlist + Alerts + Trade Log -->
			<aside class="lw-left" aria-label="Watchlist and alerts">
				<!-- Portfolio selector -->
				<div class="lw-portfolio-selector">
					<button
						type="button"
						class="lw-portfolio-trigger"
						onclick={toggleDropdown}
						aria-haspopup="listbox"
						aria-expanded={showDropdown}
					>
						<span class="lw-portfolio-name">
							{selected?.display_name ?? "Select"}
						</span>
						<span class="lw-portfolio-chevron" aria-hidden="true">
							{showDropdown ? "\u25B4" : "\u25BE"}
						</span>
					</button>

					{#if showDropdown}
						<ul
							class="lw-portfolio-list"
							role="listbox"
							aria-label="Portfolios"
						>
							{#each portfolios as p (p.id)}
								<!-- svelte-ignore a11y_click_events_have_key_events -->
								<li
									role="option"
									class="lw-portfolio-item"
									class:lw-portfolio-item--active={p.id === selected?.id}
									aria-selected={p.id === selected?.id}
									onclick={() => selectFromDropdown(p)}
								>
									<span class="lw-portfolio-item-name">{p.display_name}</span>
									<span class="lw-portfolio-item-profile">{p.profile}</span>
								</li>
							{/each}
						</ul>
					{/if}
				</div>

				<div class="lw-left-watchlist">
					<Watchlist
						items={watchlistItems}
						selectedTicker={effectiveTicker}
						onSelect={handleWatchlistSelect}
						portfolioName={selected?.display_name ?? ""}
					/>
				</div>

				<div class="lw-left-alerts">
					<AlertStreamPanel
						portfolioId={selected?.id ?? null}
						injectedAlerts={driftAlerts}
					/>
				</div>

				<div class="lw-left-tradelog">
					{#key refreshToken}
						<TradeLog portfolioId={selected?.id ?? null} />
					{/key}
				</div>
			</aside>

			<!-- CENTER: Toolbar + Chart + Summary + Holdings -->
			<div class="lw-center">
				<div class="lw-toolbar">
					<ChartToolbar
						ticker={effectiveTicker}
						instrumentName={effectiveInstrumentName}
						timeframe={chartTimeframe}
						onTimeframeChange={handleTimeframeChange}
						onCompare={handleCompare}
						{compareTicker}
						onClearCompare={handleClearCompare}
					/>
				</div>

				<section class="lw-chart" aria-label="Price chart">
					<TerminalPriceChart
						ticker={effectiveTicker}
						{historicalBars}
						portfolioNavBars={effectiveNavBars}
						{lastTick}
						timeframe={chartTimeframe === "1Y" ? "3M" : chartTimeframe}
						onTimeframeChange={handleTimeframeChange}
						{dataStatus}
					/>
				</section>

				<div class="lw-summary">
					<PortfolioSummary
						status={selected?.status ?? ""}
						state={selected?.state ?? "draft"}
						aum={portfolioAum}
						returnPct={marketStore.totalReturnPct}
						driftStatus={aggregateDrift}
						{instrumentCount}
						{lastRebalance}
						onRebalance={handleRebalanceOpen}
					/>
				</div>

				<div class="lw-holdings">
					<HoldingsTable
						holdings={holdingsRows}
						selectedTicker={effectiveTicker}
						onSelect={handleHoldingsSelect}
					/>
				</div>
			</div>

			<!-- RIGHT COLUMN: News Feed + Market Conditions -->
			<aside class="lw-right" aria-label="Market context">
				<div class="lw-news">
					<NewsFeed tickers={resolvedTickers} />
				</div>
				<div class="lw-macro">
					<MacroRegimePanel />
				</div>
			</aside>
		</div>

		{#if showRebalance && selected}
			<RebalanceFocusMode
				portfolioId={selected.id}
				portfolioName={selected.display_name ?? "Portfolio"}
				holdings={actualHoldingsData?.holdings ?? []}
				holdingsVersion={actualHoldingsData?.holdings_version ?? 1}
				totalAum={portfolioAum}
				onClose={handleRebalanceClose}
				onSuccess={handleRebalanceSuccess}
			/>
		{/if}
	{/if}

	{#snippet failed(err: unknown, reset: () => void)}
		<PanelErrorState
			title="Live Workbench error"
			message={err instanceof Error ? err.message : "Unexpected error"}
			onRetry={reset}
		/>
	{/snippet}
</svelte:boundary>

<style>
	/* -- Empty state -- */
	.lw-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--terminal-space-2);
		height: 100%;
		background: var(--terminal-bg-void);
	}

	.lw-empty-label {
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-14);
		font-weight: 700;
		color: var(--terminal-fg-tertiary);
	}

	.lw-empty-sub {
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
	}

	/* -- Main grid: 3-column, full height -- */
	.lw-shell {
		display: grid;
		grid-template-columns: 220px 1fr 280px;
		height: calc(100vh - 88px);
		gap: 1px;
		background: var(--terminal-bg-void);
		font-family: var(--terminal-font-mono);
	}

	/* LEFT COLUMN: stacked vertically */
	.lw-left {
		display: flex;
		flex-direction: column;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
	}

	.lw-left-watchlist {
		flex: 60;
		min-height: 0;
		overflow: hidden;
		border-bottom: var(--terminal-border-hairline);
	}

	.lw-left-alerts {
		flex: 25;
		min-height: 0;
		overflow: hidden;
		border-bottom: var(--terminal-border-hairline);
	}

	.lw-left-tradelog {
		flex: 15;
		min-height: 0;
		overflow: hidden;
	}

	/* CENTER COLUMN: toolbar + chart + summary + holdings */
	.lw-center {
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
	}

	.lw-toolbar {
		flex-shrink: 0;
		height: 32px;
		min-width: 0;
		overflow: hidden;
	}

	.lw-chart {
		flex: 55;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
		position: relative;
	}

	.lw-summary {
		flex-shrink: 0;
		overflow: hidden;
		border-top: var(--terminal-border-hairline);
	}

	.lw-holdings {
		flex: 45;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
		border-top: var(--terminal-border-hairline);
	}

	/* RIGHT COLUMN: News + Macro stacked */
	.lw-right {
		display: flex;
		flex-direction: column;
		min-height: 0;
		overflow: hidden;
	}

	.lw-news {
		flex: 55;
		min-height: 0;
		overflow: hidden;
		border-bottom: var(--terminal-border-hairline);
	}

	.lw-macro {
		flex: 45;
		min-height: 0;
		overflow: hidden;
	}

	/* -- Portfolio selector dropdown -- */
	.lw-portfolio-selector {
		position: relative;
		flex-shrink: 0;
		border-bottom: var(--terminal-border-hairline);
	}

	.lw-portfolio-trigger {
		appearance: none;
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		height: 32px;
		padding: 0 var(--terminal-space-2);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		font-weight: 700;
		color: var(--terminal-accent-amber);
		background: var(--terminal-bg-panel);
		border: none;
		cursor: pointer;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.lw-portfolio-trigger:hover {
		background: var(--terminal-bg-panel-raised);
	}

	.lw-portfolio-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.lw-portfolio-chevron {
		flex-shrink: 0;
		font-size: 9px;
		color: var(--terminal-fg-tertiary);
	}

	.lw-portfolio-list {
		position: absolute;
		top: 100%;
		left: 0;
		right: 0;
		z-index: var(--terminal-z-dropdown);
		margin: 0;
		padding: var(--terminal-space-1) 0;
		list-style: none;
		background: var(--terminal-bg-overlay);
		border: 1px solid var(--terminal-fg-muted);
		max-height: 280px;
		overflow-y: auto;
	}

	.lw-portfolio-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px var(--terminal-space-2);
		cursor: pointer;
		transition: background var(--terminal-motion-tick);
	}

	.lw-portfolio-item:hover {
		background: var(--terminal-bg-panel-raised);
	}

	.lw-portfolio-item--active {
		border-left: 2px solid var(--terminal-accent-amber);
	}

	.lw-portfolio-item-name {
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.lw-portfolio-item--active .lw-portfolio-item-name {
		color: var(--terminal-accent-amber);
	}

	.lw-portfolio-item-profile {
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
		flex-shrink: 0;
	}

	/* -- Mobile lock -- */
	@media (max-width: 1200px) {
		.lw-shell {
			display: none !important;
		}

		.lw-empty::after {
			content: "Terminal requires desktop resolution (>1200px)";
			font-family: var(--terminal-font-mono);
			font-size: var(--terminal-text-11);
			color: var(--terminal-fg-muted);
			margin-top: var(--terminal-space-4);
		}
	}
</style>
