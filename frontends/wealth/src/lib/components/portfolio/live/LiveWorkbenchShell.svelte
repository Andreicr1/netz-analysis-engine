<!--
  LiveWorkbenchShell — 3-column terminal grid.

  Grid topology (professional trading dashboard):

    ┌──────────────────────────────────────────────────────┐
    │               HEADER (44px, 3 cols)                  │
    ├──────────┬───────────────────────┬───────────────────┤
    │          │                       │                   │
    │   NEWS   │       CHART           │       OMS         │
    │  (280px) │       (1fr)           │      (340px)      │
    │          │                       │                   │
    ├──────────┼───────────────────────┼───────────────────┤
    │   NEWS   │      BLOTTER          │    TRADE LOG      │
    │  (cont.) │   (positions)         │   (executions)    │
    └──────────┴───────────────────────┴───────────────────┘

  Panel aesthetic: bg-black grid container with 2px gap,
  each zone is a dark panel (#0b0f1a) — "cards colados".
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { Button, EmptyState } from "@investintell/ui";
	import { PanelErrorState } from "@investintell/ui/runtime";
	import { goto } from "$app/navigation";
	import TerminalTickerStrip from "./TerminalTickerStrip.svelte";
	import TerminalNewsFeed from "./TerminalNewsFeed.svelte";
	import TerminalOmsPanel from "./TerminalOmsPanel.svelte";
	import TerminalBlotter from "./TerminalBlotter.svelte";
	import TerminalTradeLog from "./TerminalTradeLog.svelte";
	import TerminalApprovedUniverse from "./TerminalApprovedUniverse.svelte";
	import TerminalAllocator from "./TerminalAllocator.svelte";
	import InitialFundingModal from "./InitialFundingModal.svelte";
	import TerminalPriceChart from "./charts/TerminalPriceChart.svelte";
	import OperationalRiskCard from "../../layout/OperationalRiskCard.svelte";
	import TradeBlotter from "../../execution/TradeBlotter.svelte";
	import type {
		BarData,
		LiveTick,
	} from "./charts/TerminalPriceChart.svelte";
	import type { ModelPortfolio, InstrumentWeight } from "$lib/types/model-portfolio";
	import { createClientApiClient } from "$lib/api/client";

	export interface CusipExposure {
		cusip: string;
		issuer_name: string | null;
		total_exposure_pct: number;
		funds_holding: string[];
		is_breach: boolean;
	}

	export interface OverlapResultRead {
		portfolio_id: string;
		computed_at: string;
		limit_pct: number;
		total_holdings: number;
		funds_analyzed: number;
		top_cusip_exposures: CusipExposure[];
		sector_exposures: any[];
		breaches: CusipExposure[];
	}

	/** Draft holding for EDIT mode — instrument + target allocation. */
	export interface DraftHolding {
		instrument_id: string;
		fund_name: string;
		block_id: string;
		targetWeight: number;
	}

	interface Props {
		portfolios: readonly ModelPortfolio[];
		selectedId: string | null;
		initialMode?: "LIVE" | "EDIT";
		onSelect: (portfolio: ModelPortfolio) => void;
	}

	let { portfolios, selectedId, initialMode = "LIVE", onSelect }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);
	let overlapResult = $state<OverlapResultRead | null>(null);

	$effect(() => {
		if (!selected?.id) {
			overlapResult = null;
			return;
		}
		let cancelled = false;
		api.get<OverlapResultRead>(`/model-portfolios/${selected.id}/overlap?limit_pct=0.05`)
			.then((res) => {
				if (!cancelled) overlapResult = res;
			})
			.catch((err) => console.error("Overlap fetch error:", err));
		return () => {
			cancelled = true;
		};
	});

	// ── Mode State Machine ────────────────────────────────────
	let mode = $state<"LIVE" | "EDIT">(initialMode);
	let draftHoldings = $state<DraftHolding[]>([]);
	let showFundingModal = $state(false);

	function enterEditMode() {
		draftHoldings = [];
		mode = "EDIT";
	}

	function cancelEditMode() {
		draftHoldings = [];
		mode = "LIVE";
	}

	function addToDraft(instrument: { instrument_id: string; fund_name: string; block_id: string }) {
		if (draftHoldings.some((h) => h.instrument_id === instrument.instrument_id)) return;
		draftHoldings = [...draftHoldings, { ...instrument, targetWeight: 0 }];
	}

	function removeFromDraft(instrumentId: string) {
		draftHoldings = draftHoldings.filter((h) => h.instrument_id !== instrumentId);
	}

	function updateDraftWeight(instrumentId: string, weight: number) {
		draftHoldings = draftHoldings.map((h) =>
			h.instrument_id === instrumentId ? { ...h, targetWeight: weight } : h,
		);
	}

	function requestPublish() {
		showFundingModal = true;
	}

	function handleFundingComplete() {
		showFundingModal = false;
		draftHoldings = [];
		mode = "LIVE";
	}

	function handleFundingCancel() {
		showFundingModal = false;
	}

	const hasPortfolios = $derived(portfolios.length > 0);
	const selected = $derived.by(() => {
		if (!selectedId) return portfolios[0] ?? null;
		return (
			portfolios.find((p) => p.id === selectedId) ?? portfolios[0] ?? null
		);
	});

	// Reset instrument selection when portfolio changes
	$effect(() => {
		const _id = selected?.id;
		void _id;
		selectedInstrumentId = null;
	});

	// ── Chart state ───────────────────────────────────────────
	type Timeframe = "1D" | "1W" | "1M" | "3M" | "6M" | "1Y";
	let chartTimeframe = $state<Timeframe>("1M");
	let mockLastTick = $state<LiveTick | null>(null);

	function generateMockBars(seed: string, tf: Timeframe): BarData[] {
		let hash = 0;
		for (let i = 0; i < seed.length; i++) {
			hash = (hash * 31 + seed.charCodeAt(i)) | 0;
		}
		const basePrice = 80 + Math.abs(hash % 60);
		const barCount =
			tf === "1D" ? 78 : tf === "1W" ? 5 * 78 : tf === "1M" ? 22 * 78 : 66 * 78;
		const count = Math.min(barCount, 500);
		const intervalSec =
			tf === "1D" ? 300 : tf === "1W" ? 300 : tf === "1M" ? 3600 : 3600 * 4;
		const now = Math.floor(Date.now() / 1000);
		const startTime = now - count * intervalSec;
		const bars: BarData[] = [];
		let price = basePrice;
		for (let i = 0; i < count; i++) {
			price += (Math.random() - 0.48) * 0.5;
			price = Math.max(price * 0.95, Math.min(price * 1.05, price));
			bars.push({
				time: startTime + i * intervalSec,
				value: Math.round(price * 100) / 100,
			});
		}
		return bars;
	}

	// ── Target funds + mock actual holdings ──────────────────
	const targetFunds = $derived<InstrumentWeight[]>(
		selected?.fund_selection_schema?.funds ?? [],
	);

	const actualHoldings = $derived.by(() => {
		return targetFunds.map((f) => ({
			instrument_id: f.instrument_id,
			fund_name: f.fund_name,
			block_id: f.block_id,
			weight: f.weight + (Math.random() - 0.5) * 0.04,
		}));
	});

	let holdingsVersion = $state(1);

	// ── Blotter → Chart instrument selection ─────────────────
	let selectedInstrumentId = $state<string | null>(null);

	function handleInstrumentSelect(instrumentId: string) {
		selectedInstrumentId = instrumentId;
	}

	const defaultTicker = $derived(
		selected?.fund_selection_schema?.funds?.[0]?.fund_name ?? selected?.profile ?? "PORT",
	);

	const effectiveChartTicker = $derived.by(() => {
		if (selectedInstrumentId) {
			const fund = targetFunds.find((f) => f.instrument_id === selectedInstrumentId);
			if (fund) return fund.fund_name;
		}
		return defaultTicker;
	});

	const chartSeedKey = $derived(
		(selectedInstrumentId ?? selected?.id ?? "") + chartTimeframe,
	);

	const historicalBars = $derived.by(() => {
		if (!selected) return [];
		return generateMockBars(chartSeedKey, chartTimeframe);
	});

	// Mock portfolio composite NAV — different seed so the curve
	// diverges from the instrument line, showing the overlay effect.
	const portfolioNavBars = $derived.by(() => {
		if (!selected) return [];
		return generateMockBars("nav:" + selected.id + chartTimeframe, chartTimeframe);
	});

	// Simulate live ticks — restarts on instrument/timeframe change
	$effect(() => {
		if (!selected || historicalBars.length === 0) {
			mockLastTick = null;
			return;
		}
		const _ticker = effectiveChartTicker;
		void _ticker;
		const lastBar = historicalBars[historicalBars.length - 1]!;
		let price = lastBar.value;
		mockLastTick = null;
		const interval = setInterval(() => {
			price += (Math.random() - 0.48) * 0.3;
			mockLastTick = {
				time: Math.floor(Date.now() / 1000),
				value: Math.round(price * 100) / 100,
			};
		}, 2000);
		return () => clearInterval(interval);
	});

	function handleTimeframeChange(tf: Timeframe) {
		chartTimeframe = tf;
	}

	// Mock trade log
	const tradeLog = $derived<Array<{
		id: string;
		instrumentId: string;
		fundName: string;
		action: "BUY" | "SELL";
		deltaWeight: number;
		executedAt: string;
		fillStatus: string;
	}>>([]);

	// ── Header price data — follows effective ticker ─────────
	const headerPriceData = $derived.by(() => {
		const lastPrice = mockLastTick?.value ?? historicalBars[historicalBars.length - 1]?.value ?? 0;
		const firstPrice = historicalBars[0]?.value ?? lastPrice;
		const changePct = firstPrice > 0 ? ((lastPrice - firstPrice) / firstPrice) * 100 : 0;
		return {
			ticker: effectiveChartTicker,
			price: lastPrice,
			changePct: Math.round(changePct * 100) / 100,
			bid: lastPrice > 0 ? Math.round((lastPrice - 0.02) * 100) / 100 : null,
			ask: lastPrice > 0 ? Math.round((lastPrice + 0.02) * 100) / 100 : null,
		};
	});

	const headerKpis = $derived.by(() => {
		const opt = selected?.fund_selection_schema?.optimization;
		return {
			expectedReturn: opt?.expected_return != null
				? Math.round(opt.expected_return * 10000) / 100
				: null,
			volatility: opt?.portfolio_volatility != null
				? Math.round(opt.portfolio_volatility * 10000) / 100
				: null,
			driftAlerts: 0,
		};
	});

	function startNewPortfolio() {
		mode = "EDIT";
		draftHoldings = [];
	}

	function exitTerminal() {
		void goto("/portfolio");
	}
</script>

<svelte:boundary>
	{#if !hasPortfolios && mode === "LIVE"}
		<div class="tg-empty">
			<EmptyState
				title="No live portfolios yet"
				message="Start by creating a portfolio in Edit mode. Add instruments from the Approved Universe, set target weights, and fund the portfolio."
			/>
			<div class="tg-empty-actions">
				<Button variant="default" onclick={startNewPortfolio}>
					Create Portfolio
				</Button>
			</div>
		</div>
	{:else}
		<!-- Mobile lock screen -->
		<div class="tg-mobile-lock">
			<div class="tg-mobile-lock-icon" aria-hidden="true">&#9634;</div>
			<h2 class="tg-mobile-lock-title">Terminal requires desktop resolution</h2>
			<p class="tg-mobile-lock-msg">
				This execution surface is designed for screens wider than 1200px.
				Please use a desktop to access the Terminal.
			</p>
			<Button variant="default" onclick={exitTerminal}>
				Back to Portfolio
			</Button>
		</div>

		<div class="tg-root">
			<!-- HEADER (spans all 3 columns) -->
			<div class="tg-header-slot">
				<TerminalTickerStrip
					{portfolios}
					{selected}
					{onSelect}
					priceData={headerPriceData}
					kpis={headerKpis}
					{mode}
					onEdit={enterEditMode}
					onCancelEdit={cancelEditMode}
					onPublish={requestPublish}
					{draftHoldings}
					onExit={exitTerminal}
					{overlapResult}
				/>
			</div>

			<!-- NEWS / APPROVED UNIVERSE (left sidebar, spans 2 rows) -->
			<div class="tg-zone tg-news" aria-label={mode === "LIVE" ? "News feed" : "Approved universe"}>
				{#if mode === "LIVE"}
					<TerminalNewsFeed />
				{:else}
					<TerminalApprovedUniverse
						{draftHoldings}
						onAdd={addToDraft}
					/>
				{/if}
			</div>

			<!-- CHART (center top) -->
			<section class="tg-zone tg-chart" aria-label="Chart zone">
				<TerminalPriceChart
					ticker={effectiveChartTicker}
					{historicalBars}
					{portfolioNavBars}
					lastTick={mockLastTick}
					timeframe={chartTimeframe}
					onTimeframeChange={handleTimeframeChange}
				/>
			</section>

			<!-- OMS / ALLOCATOR (right top) -->
			<aside class="tg-zone tg-oms" aria-label={mode === "LIVE" ? "Order management" : "Weight allocator"}>
				{#if mode === "LIVE"}
					<div class="flex flex-col w-full h-full gap-[2px] bg-black">
						<OperationalRiskCard />
						<div class="flex-1 min-h-0 relative">
							<TradeBlotter
								currentWeights={actualHoldings}
								optimalWeights={targetFunds}
							/>
						</div>
					</div>
				{:else}
					<TerminalAllocator
						{draftHoldings}
						onUpdateWeight={updateDraftWeight}
						onRemove={removeFromDraft}
					/>
				{/if}
			</aside>

			<!-- BLOTTER (center bottom — positions only) -->
			<div class="tg-zone tg-blotter" aria-label="Positions">
				<TerminalBlotter
					{mode}
					{targetFunds}
					{actualHoldings}
					{draftHoldings}
					{selectedInstrumentId}
					onInstrumentSelect={handleInstrumentSelect}
					{overlapResult}
				/>
			</div>

			<!-- TRADE LOG (right bottom) -->
			<div class="tg-zone tg-tradelog" aria-label="Trade log">
				<TerminalTradeLog {tradeLog} />
			</div>

			<!-- INITIAL FUNDING MODAL (STP flow) -->
			{#if showFundingModal}
				<InitialFundingModal
					{draftHoldings}
					portfolioName={selected?.display_name ?? "New Portfolio"}
					onComplete={handleFundingComplete}
					onCancel={handleFundingCancel}
					{overlapResult}
				/>
			{/if}
		</div>
	{/if}

	{#snippet failed(err: unknown, reset: () => void)}
		<PanelErrorState
			title="Terminal failed to render"
			message={err instanceof Error
				? err.message
				: "Unexpected error in the Terminal."}
			onRetry={reset}
		/>
	{/snippet}
</svelte:boundary>

<style>
	/* ── Terminal Design Tokens ──────────────────────────────── */
	.tg-root {
		--tg-bg: #000000;
		--tg-surface: #0b0f1a;
		--tg-border: rgba(255, 255, 255, 0.06);
		--tg-text: #c8d0dc;
		--tg-text-muted: #5a6577;
		--tg-accent: #2d7ef7;
	}

	/* ── 3-Column Grid ──────────────────────────────────────── */
	.tg-root {
		display: grid;
		grid-template-areas:
			"header  header  header"
			"news    chart   oms"
			"news    blotter tradelog";
		grid-template-columns: 280px 1fr 340px;
		grid-template-rows: 44px 1fr 35vh;
		gap: 2px;
		width: 100%;
		height: 100%;
		overflow: hidden;
		background: var(--tg-bg);
		font-family: "Urbanist", system-ui, sans-serif;
	}

	/* ── Zone base — iron rule ───────────────────────────────── */
	.tg-zone {
		display: flex;
		min-width: 0;
		min-height: 0;
		max-height: 100%;
		overflow: hidden;
		background: var(--tg-surface);
	}

	/* ── Header slot ─────────────────────────────────────────── */
	.tg-header-slot {
		grid-area: header;
		min-width: 0;
		min-height: 0;
		overflow: visible;
		position: relative;
		z-index: 50;
		background: var(--tg-surface);
	}

	/* ── News feed — left sidebar, spans 2 rows ──────────────── */
	.tg-news {
		grid-area: news;
		align-items: stretch;
		justify-content: stretch;
	}

	/* ── Chart — center top ──────────────────────────────────── */
	.tg-chart {
		grid-area: chart;
		align-items: stretch;
		justify-content: stretch;
		position: relative;
		z-index: 0;
		contain: layout paint;
	}

	/* ── OMS — right top ─────────────────────────────────────── */
	.tg-oms {
		grid-area: oms;
		align-items: stretch;
		justify-content: stretch;
	}

	/* ── Blotter — center bottom (positions) ──────────────────── */
	.tg-blotter {
		grid-area: blotter;
		align-items: stretch;
		justify-content: stretch;
	}

	/* ── Trade Log — right bottom ────────────────────────────── */
	.tg-tradelog {
		grid-area: tradelog;
		align-items: stretch;
		justify-content: stretch;
	}

	/* ── Empty state ─────────────────────────────────────────── */
	.tg-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 20px;
		height: 100%;
		padding: 48px 24px;
		background: #05080f;
	}
	.tg-empty-actions {
		display: flex;
		gap: 12px;
	}

	/* ── Mobile lock screen (hidden on desktop) ──────────────── */
	.tg-mobile-lock {
		display: none;
	}

	/* ═══════════════════════════════════════════════════════════
	   RESPONSIVE: lock at ≤1200px (3-col needs width)
	   ═══════════════════════════════════════════════════════════ */
	@media (max-width: 1200px) {
		.tg-root {
			display: none !important;
		}
		.tg-mobile-lock {
			display: flex;
			flex-direction: column;
			align-items: center;
			justify-content: center;
			gap: 16px;
			height: 100%;
			padding: 32px 24px;
			text-align: center;
			background: #05080f;
			color: #c8d0dc;
		}
		.tg-mobile-lock-icon {
			font-size: 48px;
			color: #5a6577;
			line-height: 1;
		}
		.tg-mobile-lock-title {
			font-size: 16px;
			font-weight: 700;
			margin: 0;
		}
		.tg-mobile-lock-msg {
			font-size: 13px;
			color: #5a6577;
			max-width: 360px;
			line-height: 1.5;
			margin: 0;
		}
	}

	/* ═══════════════════════════════════════════════════════════
	   PRINT: Trade Sheet — OMS only, white bg
	   ═══════════════════════════════════════════════════════════ */
	@media print {
		:global(.terminal-root) {
			position: static !important;
			width: auto !important;
			height: auto !important;
			overflow: visible !important;
			background: #ffffff !important;
			color: #000000 !important;
		}
		:global(body) {
			overflow: visible !important;
			background: #ffffff !important;
		}

		.tg-header-slot,
		.tg-news,
		.tg-chart,
		.tg-blotter,
		.tg-tradelog,
		.tg-mobile-lock,
		.tg-empty {
			display: none !important;
		}

		.tg-root {
			display: block !important;
			background: #ffffff !important;
			height: auto !important;
			overflow: visible !important;
		}
		.tg-oms {
			display: block !important;
			width: 100% !important;
			max-height: none !important;
			height: auto !important;
			overflow: visible !important;
			background: #ffffff !important;
			color: #000000 !important;
		}

		@page {
			size: A4 portrait;
			margin: 20mm 15mm;
		}
	}
</style>
