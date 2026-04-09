<!--
  Dashboard — InvestIntell Wealth OS.
  12-column grid layout matching Figma. No risk jargon.
  Holdings + prices from real API (SSR) + WebSocket (live updates).
-->
<script lang="ts">
	import { getContext, onDestroy, onMount } from "svelte";
	import { formatNumber, formatPercent, formatCurrency } from "@investintell/ui";
	import { createMountedGuard, PanelErrorState } from "@investintell/ui/runtime";
	import type { RiskStore, RegimeData, DriftAlert, BehaviorAlert } from "$lib/stores/risk-store.svelte";
	import type { MarketDataStore, DashboardSnapshot } from "$lib/stores/market-data.svelte";
	import type { PortfolioAnalyticsStore } from "$lib/stores/portfolio-analytics.svelte";
	import { ArrowUpRight, TrendingUp, TrendingDown, ChevronLeft, ChevronRight } from "lucide-svelte";
	import AdvancedMarketChart from "$lib/components/charts/AdvancedMarketChart.svelte";
	import LiveNewsFeed from "$lib/components/dashboard/LiveNewsFeed.svelte";
	import FlashNumber from "$lib/components/FlashNumber.svelte";

	let { data } = $props();

	const riskStore = getContext<RiskStore>("netz:riskStore");
	const marketStore = getContext<MarketDataStore>("netz:marketDataStore");
	const analytics = getContext<PortfolioAnalyticsStore>("netz:portfolioAnalytics");

	// Mount lifecycle guard. Used to gate any deferred callback that
	// might fire after the dashboard component has been torn down by
	// a route change — Stability Guardrails §3.3 (P4 Lifecycle).
	const mounted = createMountedGuard();

	// Seed both stores with SSR data. The marketStore.start()/stop()
	// pair lives at the (app) layout level — never start/stop the
	// shared store from a leaf route. The seed itself is synchronous
	// and lives inside `onMount`, satisfying the lint rule that bans
	// top-level store mutation.
	onMount(() => {
		mounted.start();
		if (data.riskSummary || data.regime) {
			riskStore.seedFromSSR({
				riskSummary: data.riskSummary as Record<string, unknown> | null,
				regime: data.regime as RegimeData | null,
				driftAlerts: data.alerts as { dtw_alerts: DriftAlert[]; behavior_change_alerts: BehaviorAlert[] } | null,
			});
		}
		if (data.dashboardSnapshot) {
			marketStore.seedFromSSR(data.dashboardSnapshot as DashboardSnapshot);
		}
	});

	onDestroy(() => {
		mounted.stop();
	});

	// Surface live-data unavailability through the same panel-error
	// path the boundary uses for unexpected render errors. The store
	// retries five times on its own before tipping into "error";
	// `reconnect()` is the manual escape hatch the user can pull.
	function retryMarketData() {
		mounted.guard(() => marketStore.reconnect());
	}

	const PROFILES = ["conservative", "moderate", "growth"] as const;
	type Profile = typeof PROFILES[number];

	function getSnapshot(profile: Profile) {
		return (data.snapshotsByProfile as Record<string, unknown>)?.[profile] as {
			nav?: number; ytd_return?: number;
		} | null;
	}

	// Derived from portfolio analytics (live prices fused with positions)
	let totalAum = $derived(
		analytics.totalNav > 0
			? analytics.totalNav
			: marketStore.totalAum > 0
				? marketStore.totalAum
				: PROFILES.reduce((sum, p) => sum + (getSnapshot(p)?.nav ?? 0), 0)
	);

	let totalReturnPct = $derived(
		analytics.positions.length > 0
			? analytics.totalPnlPct
			: marketStore.totalReturnPct ??
				(() => {
					const returns = PROFILES.map(p => getSnapshot(p)?.ytd_return).filter((r): r is number => r != null);
					return returns.length > 0 ? returns.reduce((a, b) => a + b, 0) / returns.length : null;
				})()
	);

	let totalPnl = $derived(analytics.totalPnl);

	// Note: a parent-level "1D / 1W / 1M / 6M / 1Y" selector used to live
	// here but it was decorative — only updated a label in the AUM card and
	// never propagated to AdvancedMarketChart. The audit flagged it as a
	// confusing dual-selector against the chart's own granularity controls.
	// Removed entirely; the chart manages its own range.

	let selectedProfile = $state("All");
	const profileFilters = ["Conservative", "Balanced", "Growth", "All"];

	let overviewFilter = $state("All");
	let watchlistFilter = $state("Most Viewed");

	// ── Active ticker — drives the central chart + news feed ──────────
	// Defaults to SPY until the user clicks a holding/watchlist row, or
	// auto-promotes to the first holding once the SSR snapshot lands.
	let activeTicker = $state<string>("SPY");

	function selectTicker(ticker: string | null | undefined) {
		const t = (ticker ?? "").trim().toUpperCase();
		if (!t) return;
		activeTicker = t;
		// Ensure the WS bridge is streaming this symbol — idempotent.
		marketStore.subscribe([t]);
	}

	// Once holdings arrive from SSR/snapshot, prefer the largest position
	// so the user doesn't open the dashboard staring at an unrelated SPY.
	$effect(() => {
		if (activeTicker !== "SPY") return;
		const first = marketStore.holdings[0];
		if (first?.ticker) {
			activeTicker = first.ticker.toUpperCase();
			marketStore.subscribe([activeTicker]);
		}
	});

	// Gradient borders — rotate across holdings for visual interest
	const GRADIENTS = [
		(pos: boolean) => `linear-gradient(to top, ${pos ? "rgba(17,236,121,0.5)" : "rgba(252,26,26,0.5)"}, ${pos ? "rgba(17,236,121,0.15)" : "rgba(252,26,26,0.15)"} 50%, transparent)`,
		(pos: boolean) => `linear-gradient(to bottom, ${pos ? "rgba(17,236,121,0.5)" : "rgba(252,26,26,0.5)"}, ${pos ? "rgba(17,236,121,0.15)" : "rgba(252,26,26,0.15)"} 50%, transparent)`,
		(pos: boolean) => `linear-gradient(to bottom right, ${pos ? "rgba(17,236,121,0.5)" : "rgba(252,26,26,0.5)"}, ${pos ? "rgba(17,236,121,0.15)" : "rgba(252,26,26,0.15)"} 50%, transparent)`,
		(pos: boolean) => `linear-gradient(to bottom left, ${pos ? "rgba(17,236,121,0.5)" : "rgba(252,26,26,0.5)"}, ${pos ? "rgba(17,236,121,0.15)" : "rgba(252,26,26,0.15)"} 50%, transparent)`,
		(pos: boolean) => `linear-gradient(to top right, ${pos ? "rgba(17,236,121,0.5)" : "rgba(252,26,26,0.5)"}, ${pos ? "rgba(17,236,121,0.12)" : "rgba(252,26,26,0.12)"} 50%, transparent)`,
	];

	// ── Holdings carousel — 3 cards visible, prev/next paginated ──────
	// Replaces the previous rudimentary 5-col flat grid. Paginates
	// through the full holdings list 3 at a time so padding is tight
	// and users can browse the whole book without horizontal scroll.
	const CAROUSEL_WINDOW = 3;
	let carouselPage = $state(0);

	let allHoldingsForCarousel = $derived(marketStore.holdings);
	let carouselPageCount = $derived(
		Math.max(1, Math.ceil(allHoldingsForCarousel.length / CAROUSEL_WINDOW))
	);

	// Clamp page if holdings shrink under us.
	$effect(() => {
		if (carouselPage >= carouselPageCount) {
			carouselPage = Math.max(0, carouselPageCount - 1);
		}
	});

	let topHoldings = $derived(
		allHoldingsForCarousel.slice(
			carouselPage * CAROUSEL_WINDOW,
			carouselPage * CAROUSEL_WINDOW + CAROUSEL_WINDOW
		)
	);

	function carouselPrev() {
		if (carouselPage > 0) carouselPage--;
	}
	function carouselNext() {
		if (carouselPage < carouselPageCount - 1) carouselPage++;
	}

	// Normalized row type for the overview table
	interface OverviewRow {
		name: string;
		ticker: string;
		price: number;
		changePct: number;
		aum: number | null;
		currency: string;
		pnl: number | null;
	}

	// Use analytics positions (live P&L) when available, fallback to raw holdings
	let overviewRows = $derived.by((): OverviewRow[] => {
		let rows: OverviewRow[];

		if (analytics.positions.length > 0) {
			rows = analytics.positions.map((p) => ({
				name: p.name,
				ticker: p.ticker,
				price: p.livePrice,
				changePct: p.intradayPnlPct,
				aum: p.positionValue,
				currency: p.currency,
				pnl: p.intradayPnl,
			}));
		} else {
			rows = marketStore.holdings.map((h) => ({
				name: h.name,
				ticker: h.ticker,
				price: h.price,
				changePct: h.change_pct,
				aum: h.aum_usd,
				currency: h.currency,
				pnl: null,
			}));
		}

		if (overviewFilter === "Gainers") return rows.filter((r) => r.changePct > 0);
		if (overviewFilter === "Losers") return rows.filter((r) => r.changePct < 0);
		return rows;
	});
	let hasData = $derived(marketStore.holdings.length > 0);
	let isLoading = $derived(marketStore.status === "connecting" && !hasData);

	// ── Portfolio Overview pagination ─────────────────────────────────
	// Replaces runaway scroll with a hard 10-row page window + prev/next.
	const OVERVIEW_PAGE_SIZE = 10;
	let overviewPage = $state(0);

	let overviewPageCount = $derived(
		Math.max(1, Math.ceil(overviewRows.length / OVERVIEW_PAGE_SIZE))
	);

	// Reset to page 0 whenever the filter changes so the user is not
	// stranded on an empty page.
	$effect(() => {
		void overviewFilter;
		overviewPage = 0;
	});

	$effect(() => {
		if (overviewPage >= overviewPageCount) {
			overviewPage = Math.max(0, overviewPageCount - 1);
		}
	});

	let overviewRowsPage = $derived(
		overviewRows.slice(
			overviewPage * OVERVIEW_PAGE_SIZE,
			overviewPage * OVERVIEW_PAGE_SIZE + OVERVIEW_PAGE_SIZE
		)
	);

	function overviewPrev() {
		if (overviewPage > 0) overviewPage--;
	}
	function overviewNext() {
		if (overviewPage < overviewPageCount - 1) overviewPage++;
	}
</script>

<!-- 12-column master grid — high-density layout, glassmorphism preserved -->
<div class="grid grid-cols-12 gap-3">

	<!-- ══ Row 1: Total AUM (4 cols) + Portfolio Holdings (8 cols) ══ -->

	<!-- Total AUM — glassmorphism (density-tuned) -->
	<svelte:boundary>
	{#if marketStore.status === "error"}
		<div class="col-span-4 min-h-[170px]">
			<PanelErrorState
				title="Live data unavailable"
				message={marketStore.error ?? "WebSocket connection lost"}
				onRetry={retryMarketData}
			/>
		</div>
	{:else}
	<div class="col-span-4 relative rounded-[24px] overflow-hidden bg-[var(--ii-glass-bg)] backdrop-blur-[12px] border border-[var(--ii-border-subtle)] min-h-[170px]">
		<div class="absolute inset-0 bg-gradient-to-br from-[#0177fb]/18 via-transparent to-transparent pointer-events-none"></div>
		<div class="relative flex flex-col justify-between h-full px-5 py-4 gap-2">
			<div class="flex items-center justify-between">
				<span class="text-[10px] font-semibold uppercase tracking-[0.09em] text-[var(--ii-text-muted)]">Total AUM</span>
				<span class="inline-flex items-center gap-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-[#11ec79]">
					<span class="h-1.5 w-1.5 rounded-full bg-[#11ec79] shadow-[0_0_6px_rgba(17,236,121,0.75)] animate-pulse"></span>
					Live
				</span>
			</div>

			{#if isLoading}
				<div class="h-8 w-44 bg-[var(--ii-surface-highlight)] rounded animate-pulse"></div>
			{:else}
				<p class="text-[32px] font-bold text-[var(--ii-text-primary)] tracking-tight tabular-nums leading-none">
					<FlashNumber value={totalAum}>{formatCurrency(totalAum)}</FlashNumber>
				</p>
			{/if}

			<div class="flex items-end gap-1.5">
				<span class="text-[10px] text-[var(--ii-text-muted)] uppercase tracking-wider">Return</span>
				{#if totalReturnPct != null}
					{#if totalReturnPct >= 0}
						<TrendingUp size={14} class="text-[#11ec79]" />
						<span class="text-sm font-semibold text-[#11ec79] tabular-nums">
							<FlashNumber value={totalReturnPct}>
								+{formatPercent(totalReturnPct)}{#if totalPnl !== 0} ({formatCurrency(Math.abs(totalPnl))}){/if}
							</FlashNumber>
						</span>
					{:else}
						<TrendingDown size={14} class="text-[#fc1a1a]" />
						<span class="text-sm font-semibold text-[#fc1a1a] tabular-nums">
							<FlashNumber value={totalReturnPct}>
								{formatPercent(totalReturnPct)}{#if totalPnl !== 0} ({formatCurrency(Math.abs(totalPnl))}){/if}
							</FlashNumber>
						</span>
					{/if}
				{:else if isLoading}
					<div class="h-3 w-20 bg-[var(--ii-surface-highlight)] rounded animate-pulse"></div>
				{:else}
					<span class="text-sm text-[var(--ii-text-muted)]">—</span>
				{/if}
			</div>
		</div>
	</div>
	{/if}
	{#snippet failed(error, reset)}
		<div class="col-span-4 min-h-[170px]">
			<PanelErrorState
				title="Total AUM panel error"
				message={error instanceof Error ? error.message : String(error)}
				onRetry={reset}
			/>
		</div>
	{/snippet}
	</svelte:boundary>

	<!-- Portfolio Holdings (8 cols) — 3-card carousel with prev/next -->
	<svelte:boundary>
	<div class="col-span-8 bg-[var(--ii-surface-panel)] rounded-[24px] px-4 py-3 border border-[var(--ii-border-subtle)]">
		<div class="flex items-center justify-between mb-2.5">
			<div class="flex items-center gap-2">
				<span class="text-[10px] font-semibold uppercase tracking-[0.09em] text-[var(--ii-text-muted)]">Portfolio Holdings</span>
				<span class="inline-flex items-center gap-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-[#11ec79]">
					<span class="h-1.5 w-1.5 rounded-full bg-[#11ec79] shadow-[0_0_6px_rgba(17,236,121,0.75)] animate-pulse"></span>
					Live
				</span>
			</div>
			<div class="flex items-center gap-1.5">
				<!-- Carousel pagination -->
				<div class="flex items-center gap-1">
					<button
						type="button"
						aria-label="Previous holdings"
						class="border border-[var(--ii-border)] rounded-full p-1 leading-none hover:bg-[var(--ii-surface-highlight)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
						disabled={carouselPage === 0}
						onclick={carouselPrev}
					>
						<ChevronLeft size={13} class="text-[var(--ii-text-primary)]" />
					</button>
					<span class="text-[10px] text-[var(--ii-text-muted)] tabular-nums min-w-[28px] text-center">
						{carouselPage + 1}/{carouselPageCount}
					</span>
					<button
						type="button"
						aria-label="Next holdings"
						class="border border-[var(--ii-border)] rounded-full p-1 leading-none hover:bg-[var(--ii-surface-highlight)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
						disabled={carouselPage >= carouselPageCount - 1}
						onclick={carouselNext}
					>
						<ChevronRight size={13} class="text-[var(--ii-text-primary)]" />
					</button>
				</div>
				<a href="/portfolio/approved" class="border border-[var(--ii-border)] rounded-full px-2.5 py-0.5 text-[10px] text-[var(--ii-text-primary)] leading-none no-underline hover:bg-[var(--ii-surface-highlight)] transition-colors">See all</a>
				<a href="/portfolio/approved" aria-label="Open portfolio" class="border border-[var(--ii-border)] rounded-full p-1 leading-none no-underline hover:bg-[var(--ii-surface-highlight)] transition-colors">
					<ArrowUpRight size={13} class="text-[var(--ii-text-primary)]" />
				</a>
			</div>
		</div>

		<!-- Cards: 3 across, tight padding -->
		<div class="grid grid-cols-3 gap-2">
			{#if isLoading}
				{#each Array(3) as _}
					<div class="rounded-[18px] bg-[var(--ii-surface-elevated)] min-h-[76px] animate-pulse"></div>
				{/each}
			{:else if topHoldings.length > 0}
				{#each topHoldings as h, i (h.ticker || h.name)}
					{@const positive = h.change_pct >= 0}
					{@const gradFn = GRADIENTS[i % GRADIENTS.length]!}
					{@const grad = gradFn(positive)}
					<button
						type="button"
						class="rounded-[18px] p-[1px] text-left w-full transition-transform hover:scale-[1.015]"
						style:background={grad}
						onclick={() => selectTicker(h.ticker)}
					>
						<div class="bg-[var(--ii-surface-elevated)] rounded-[17px] px-2.5 py-2 flex flex-col justify-between min-h-[76px] h-full">
							<div class="flex flex-col gap-0.5">
								<span class="text-sm font-bold text-[var(--ii-text-primary)] tabular-nums leading-tight">
									<FlashNumber value={h.price}>{formatCurrency(h.price, h.currency)}</FlashNumber>
								</span>
								<span class="text-[10px] tabular-nums {positive ? 'text-[#11ec79]' : 'text-[#fc1a1a]'}">
									<FlashNumber value={h.change_pct}>
										{positive ? "+" : ""}{formatNumber(h.change, 2)} ({formatNumber(h.change_pct, 1)}%)
									</FlashNumber>
								</span>
							</div>
							<div class="flex items-center justify-between mt-auto pt-1">
								<span class="text-[11px] font-semibold text-[var(--ii-text-primary)] tracking-wide">{h.ticker || h.name.slice(0, 6)}</span>
								{#if h.weight > 0}
									<span class="text-[10px] font-bold text-[var(--ii-text-primary)] tabular-nums">{formatNumber(h.weight * 100, 1)}%</span>
								{/if}
							</div>
						</div>
					</button>
				{/each}
				<!-- Pad empty slots when the last page has fewer than 3 holdings -->
				{#each Array(Math.max(0, CAROUSEL_WINDOW - topHoldings.length)) as _}
					<div class="rounded-[18px] bg-[var(--ii-surface-elevated)]/40 border border-dashed border-[var(--ii-border-subtle)] min-h-[76px]"></div>
				{/each}
			{:else}
				<div class="col-span-3 flex items-center justify-center h-[76px] text-xs text-[var(--ii-text-primary)]/30 border border-dashed border-[var(--ii-border)] rounded-[16px]">
					No holdings in portfolio
				</div>
			{/if}
		</div>
	</div>
	{#snippet failed(error, reset)}
		<div class="col-span-8">
			<PanelErrorState
				title="Portfolio holdings panel error"
				message={error instanceof Error ? error.message : String(error)}
				onRetry={reset}
			/>
		</div>
	{/snippet}
	</svelte:boundary>

	<!-- ══ Row 2: AdvancedMarketChart (8 cols) + LiveNewsFeed (4 cols) ══ -->
	<svelte:boundary>
	<div class="col-span-8 bg-[var(--ii-surface-panel)] rounded-[24px] px-5 py-4 flex flex-col gap-3 border border-[var(--ii-border-subtle)]">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<div class="flex flex-wrap items-center gap-3">
				<span class="text-[10px] font-semibold uppercase tracking-[0.09em] text-[var(--ii-text-muted)] whitespace-nowrap">Market Chart</span>
				<div class="flex flex-wrap items-center gap-1">
					{#each profileFilters as pf}
						<button
							type="button"
							class="h-7 px-3 rounded-full text-[11px] font-medium transition-colors leading-none whitespace-nowrap
								{selectedProfile === pf
									? 'bg-[#0177fb] text-white'
									: 'text-[var(--ii-text-primary)] border border-[var(--ii-border)] hover:bg-[var(--ii-surface-highlight)]'}"
							onclick={() => selectedProfile = pf}
						>{pf}</button>
					{/each}
				</div>
			</div>

		</div>

		<!-- Chart cola nas bordas internas — sem padding extra -->
		<div class="-mx-2 -mb-2">
			<AdvancedMarketChart ticker={activeTicker} height={380} />
		</div>
	</div>
	{#snippet failed(error, reset)}
		<div class="col-span-8">
			<PanelErrorState
				title="Market chart unavailable"
				message={error instanceof Error ? error.message : String(error)}
				onRetry={reset}
			/>
		</div>
	{/snippet}
	</svelte:boundary>

	<svelte:boundary>
	<div class="col-span-4">
		<LiveNewsFeed
			tickers={[activeTicker]}
			limit={20}
			refreshIntervalMs={60_000}
			maxHeight={460}
		/>
	</div>
	{#snippet failed(error, reset)}
		<div class="col-span-4">
			<PanelErrorState
				title="News feed unavailable"
				message={error instanceof Error ? error.message : String(error)}
				onRetry={reset}
			/>
		</div>
	{/snippet}
	</svelte:boundary>

	<!-- ══ Row 3: Portfolio Overview (8 cols) + Watchlist (4 cols) ══ -->

	<!-- Portfolio Overview — high-density table + pagination -->
	<svelte:boundary>
	<div class="col-span-8 bg-[var(--ii-surface-panel)] rounded-[24px] px-5 py-4 border border-[var(--ii-border-subtle)]">
		<div class="flex flex-wrap items-center justify-between gap-3 mb-3">
			<div class="flex items-center gap-2">
				<span class="text-[10px] font-semibold uppercase tracking-[0.09em] text-[var(--ii-text-muted)]">Portfolio Overview</span>
				<span class="inline-flex items-center gap-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-[#11ec79]">
					<span class="h-1.5 w-1.5 rounded-full bg-[#11ec79] shadow-[0_0_6px_rgba(17,236,121,0.75)] animate-pulse"></span>
					Live
				</span>
			</div>
			<div class="flex flex-wrap items-center gap-1">
				{#each ["All", "Gainers", "Losers"] as f}
					<button
						type="button"
						class="h-7 px-3 rounded-full text-[11px] font-medium transition-colors leading-none
							{overviewFilter === f
								? 'bg-[#0177fb] text-white'
								: 'text-[var(--ii-text-primary)] border border-[var(--ii-border)] hover:bg-[var(--ii-surface-highlight)]'}"
						onclick={() => overviewFilter = f}
					>{f}</button>
				{/each}
			</div>
		</div>

		<table class="w-full">
			<thead>
				<tr class="border-b border-[var(--ii-border)]">
					<th class="text-left text-[10px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] pb-2 pr-3">Fund</th>
					<th class="text-right text-[10px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] pb-2 pr-3">Last Price</th>
					<th class="text-right text-[10px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] pb-2 pr-3">Change</th>
					<th class="text-right text-[10px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] pb-2 pr-3">AUM</th>
					<th class="text-right text-[10px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] pb-2 w-8"></th>
				</tr>
			</thead>
			<tbody>
				{#if isLoading}
					{#each Array(5) as _}
						<tr class="border-b border-[var(--ii-border-subtle)]">
							<td class="py-2 pr-3"><div class="h-3 w-32 bg-[var(--ii-surface-highlight)] rounded animate-pulse"></div></td>
							<td class="py-2 pr-3"><div class="h-3 w-20 bg-[var(--ii-surface-highlight)] rounded animate-pulse ml-auto"></div></td>
							<td class="py-2 pr-3"><div class="h-3 w-14 bg-[var(--ii-surface-highlight)] rounded animate-pulse ml-auto"></div></td>
							<td class="py-2 pr-3"><div class="h-3 w-16 bg-[var(--ii-surface-highlight)] rounded animate-pulse ml-auto"></div></td>
							<td class="py-2"><div class="h-3 w-3 bg-[var(--ii-surface-highlight)] rounded animate-pulse ml-auto"></div></td>
						</tr>
					{/each}
				{:else if overviewRowsPage.length > 0}
					{#each overviewRowsPage as row (row.ticker || row.name)}
						{@const positive = row.changePct >= 0}
						{@const isActive = activeTicker === (row.ticker || "").toUpperCase()}
						<tr
							class="border-b border-[var(--ii-border-subtle)] cursor-pointer transition-colors hover:bg-[var(--ii-surface-highlight)] {isActive ? 'bg-[#0177fb]/10' : ''}"
							onclick={() => selectTicker(row.ticker)}
						>
							<td class="py-2 pr-3">
								<div class="flex flex-col leading-tight">
									<span class="text-sm text-[var(--ii-text-primary)]">{row.name.length > 28 ? row.name.slice(0, 28) + "…" : row.name}</span>
									<span class="text-[10px] text-[var(--ii-text-muted)] tracking-wide">{row.ticker}</span>
								</div>
							</td>
							<td class="py-2 text-sm text-[var(--ii-text-primary)] tabular-nums text-right pr-3">
								<FlashNumber value={row.price}>{formatCurrency(row.price, row.currency)}</FlashNumber>
							</td>
							<td class="py-2 text-sm tabular-nums text-right pr-3 {positive ? 'text-[#11ec79]' : 'text-[#fc1a1a]'}">
								<FlashNumber value={row.changePct}>
									{positive ? "+" : ""}{formatNumber(row.changePct, 2)}%
								</FlashNumber>
							</td>
							<td class="py-2 text-sm text-[var(--ii-text-primary)] tabular-nums text-right pr-3">
								{row.aum ? formatCurrency(row.aum) : "—"}
							</td>
							<td class="py-2 text-right">
								{#if positive}
									<TrendingUp size={14} class="text-[#11ec79] inline" />
								{:else}
									<TrendingDown size={14} class="text-[#fc1a1a] inline" />
								{/if}
							</td>
						</tr>
					{/each}
				{:else}
					<tr>
						<td colspan="5" class="py-6 text-center text-xs text-[var(--ii-text-primary)]/30">No holdings to display</td>
					</tr>
				{/if}
			</tbody>
		</table>

		<!-- Pagination footer -->
		{#if !isLoading && overviewRows.length > OVERVIEW_PAGE_SIZE}
			<div class="flex items-center justify-between mt-3 pt-2 border-t border-[var(--ii-border-subtle)]">
				<span class="text-[10px] text-[var(--ii-text-muted)] tabular-nums">
					{overviewPage * OVERVIEW_PAGE_SIZE + 1}–{Math.min((overviewPage + 1) * OVERVIEW_PAGE_SIZE, overviewRows.length)} of {overviewRows.length}
				</span>
				<div class="flex items-center gap-1.5">
					<button
						type="button"
						class="border border-[var(--ii-border)] rounded-full px-2.5 py-1 text-[10px] text-[var(--ii-text-primary)] leading-none hover:bg-[var(--ii-surface-highlight)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-1"
						disabled={overviewPage === 0}
						onclick={overviewPrev}
					>
						<ChevronLeft size={12} class="text-[var(--ii-text-primary)]" />
						Prev
					</button>
					<span class="text-[10px] text-[var(--ii-text-muted)] tabular-nums min-w-[40px] text-center">
						{overviewPage + 1}/{overviewPageCount}
					</span>
					<button
						type="button"
						class="border border-[var(--ii-border)] rounded-full px-2.5 py-1 text-[10px] text-[var(--ii-text-primary)] leading-none hover:bg-[var(--ii-surface-highlight)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-1"
						disabled={overviewPage >= overviewPageCount - 1}
						onclick={overviewNext}
					>
						Next
						<ChevronRight size={12} class="text-[var(--ii-text-primary)]" />
					</button>
				</div>
			</div>
		{/if}
	</div>
	{#snippet failed(error, reset)}
		<div class="col-span-8">
			<PanelErrorState
				title="Portfolio overview unavailable"
				message={error instanceof Error ? error.message : String(error)}
				onRetry={reset}
			/>
		</div>
	{/snippet}
	</svelte:boundary>

	<!-- Watchlist — high-density list -->
	<svelte:boundary>
	<div class="col-span-4 bg-[var(--ii-surface-panel)] rounded-[24px] px-5 py-4 border border-[var(--ii-border-subtle)]">
		<div class="flex items-center justify-between gap-2 mb-3">
			<div class="flex items-center gap-2">
				<span class="text-[10px] font-semibold uppercase tracking-[0.09em] text-[var(--ii-text-muted)]">Watchlist</span>
				<span class="inline-flex items-center gap-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-[#11ec79]">
					<span class="h-1.5 w-1.5 rounded-full bg-[#11ec79] shadow-[0_0_6px_rgba(17,236,121,0.75)] animate-pulse"></span>
					Live
				</span>
			</div>
			<div class="flex items-center gap-1">
				{#each ["Most Viewed", "Gainers", "Losers"] as f}
					<button
						type="button"
						class="h-7 px-2.5 rounded-full text-[10px] font-medium transition-colors leading-none whitespace-nowrap
							{watchlistFilter === f
								? 'bg-[#0177fb] text-white'
								: 'text-[var(--ii-text-primary)] border border-[var(--ii-border)] hover:bg-[var(--ii-surface-highlight)]'}"
						onclick={() => watchlistFilter = f}
					>{f}</button>
				{/each}
			</div>
		</div>

		{#if isLoading}
			{#each Array(5) as _}
				<div class="flex items-center justify-between py-2 border-b border-[var(--ii-border-subtle)]">
					<div class="flex flex-col gap-1">
						<div class="h-3 w-24 bg-[var(--ii-surface-highlight)] rounded animate-pulse"></div>
						<div class="h-2 w-12 bg-[var(--ii-surface-highlight)] rounded animate-pulse"></div>
					</div>
					<div class="flex flex-col gap-1 items-end">
						<div class="h-3 w-16 bg-[var(--ii-surface-highlight)] rounded animate-pulse"></div>
						<div class="h-2 w-10 bg-[var(--ii-surface-highlight)] rounded animate-pulse"></div>
					</div>
				</div>
			{/each}
		{:else}
			{@const watchlistRows = watchlistFilter === "Gainers"
				? marketStore.holdings.filter(h => h.change_pct > 0).slice(0, 8)
				: watchlistFilter === "Losers"
					? marketStore.holdings.filter(h => h.change_pct < 0).slice(0, 8)
					: marketStore.holdings.slice(0, 8)}
			{#each watchlistRows as h (h.ticker || h.name)}
				{@const isActive = activeTicker === (h.ticker || "").toUpperCase()}
				<button
					type="button"
					class="w-full text-left flex items-center justify-between py-2 px-2 -mx-2 border-b border-[var(--ii-border-subtle)] last:border-0 cursor-pointer transition-colors hover:bg-[var(--ii-surface-highlight)] {isActive ? 'bg-[#0177fb]/10' : ''}"
					onclick={() => selectTicker(h.ticker)}
				>
					<div class="flex flex-col gap-0.5 leading-tight min-w-0">
						<span class="text-sm text-[var(--ii-text-primary)] truncate">{h.name.length > 22 ? h.name.slice(0, 22) + "…" : h.name}</span>
						<span class="text-[10px] text-[var(--ii-text-muted)] tracking-wide">{h.ticker}</span>
					</div>
					<div class="flex flex-col gap-0.5 items-end leading-tight tabular-nums">
						<span class="text-sm text-[var(--ii-text-primary)]">
							<FlashNumber value={h.price}>{formatCurrency(h.price, h.currency)}</FlashNumber>
						</span>
						<span class="text-[10px] {h.change_pct >= 0 ? 'text-[#11ec79]' : 'text-[#fc1a1a]'}">
							<FlashNumber value={h.change_pct}>
								{h.change_pct >= 0 ? "+" : ""}{formatNumber(h.change_pct, 2)}%
							</FlashNumber>
						</span>
					</div>
				</button>
			{:else}
				<div class="py-6 text-center text-xs text-[var(--ii-text-primary)]/30">No items in watchlist</div>
			{/each}
		{/if}
	</div>
	{#snippet failed(error, reset)}
		<div class="col-span-4">
			<PanelErrorState
				title="Watchlist unavailable"
				message={error instanceof Error ? error.message : String(error)}
				onRetry={reset}
			/>
		</div>
	{/snippet}
	</svelte:boundary>
</div>
