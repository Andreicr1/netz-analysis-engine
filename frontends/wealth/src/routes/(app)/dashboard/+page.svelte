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
	import { ArrowUpRight, TrendingUp, TrendingDown } from "lucide-svelte";
	import AdvancedMarketChart from "$lib/components/charts/AdvancedMarketChart.svelte";
	import LiveNewsFeed from "$lib/components/dashboard/LiveNewsFeed.svelte";

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

	// Top 5 holdings for the card row
	let topHoldings = $derived(marketStore.holdings.slice(0, 5));

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
	<div class="col-span-4 relative rounded-[24px] overflow-hidden bg-[#0d0d0d]/60 backdrop-blur-[11px] border border-white/5 min-h-[170px]">
		<div class="absolute inset-0 bg-gradient-to-br from-[#0177fb]/15 via-transparent to-transparent pointer-events-none"></div>
		<div class="relative flex flex-col justify-between h-full px-5 py-4 gap-2">
			<div class="flex items-center justify-between">
				<span class="text-xs font-semibold uppercase tracking-[0.08em] text-[#85a0bd]">Total AUM</span>
			</div>

			{#if isLoading}
				<div class="h-8 w-44 bg-white/5 rounded animate-pulse"></div>
			{:else}
				<p class="text-[32px] font-bold text-white tracking-tight tabular-nums leading-none">
					{formatCurrency(totalAum)}
				</p>
			{/if}

			<div class="flex items-end gap-1.5">
				<span class="text-xs text-[#85a0bd] uppercase tracking-wider">Return</span>
				{#if totalReturnPct != null}
					{#if totalReturnPct >= 0}
						<TrendingUp size={14} class="text-[#11ec79]" />
						<span class="text-sm font-semibold text-[#11ec79] tabular-nums">
							+{formatPercent(totalReturnPct)}{#if totalPnl !== 0} ({formatCurrency(Math.abs(totalPnl))}){/if}
						</span>
					{:else}
						<TrendingDown size={14} class="text-[#fc1a1a]" />
						<span class="text-sm font-semibold text-[#fc1a1a] tabular-nums">
							{formatPercent(totalReturnPct)}{#if totalPnl !== 0} ({formatCurrency(Math.abs(totalPnl))}){/if}
						</span>
					{/if}
				{:else if isLoading}
					<div class="h-3 w-20 bg-white/5 rounded animate-pulse"></div>
				{:else}
					<span class="text-sm text-[#85a0bd]">—</span>
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

	<!-- Portfolio Holdings (8 cols) — density-tuned -->
	<svelte:boundary>
	<div class="col-span-8 bg-black rounded-[24px] px-5 py-4">
		<div class="flex items-center justify-between mb-3">
			<span class="text-xs font-semibold uppercase tracking-[0.08em] text-[#85a0bd]">Portfolio Holdings</span>
			<div class="flex items-center gap-1">
				<a href="/portfolio/approved" class="border border-white/20 rounded-full px-3 py-1 text-[11px] text-white leading-none no-underline hover:bg-white/10 transition-colors">See all</a>
				<a href="/portfolio/approved" class="border border-white/20 rounded-full p-1.5 leading-none no-underline hover:bg-white/10 transition-colors">
					<ArrowUpRight size={14} class="text-white" />
				</a>
			</div>
		</div>

		<!-- Cards: 5 across, compact -->
		<div class="grid grid-cols-5 gap-2">
			{#if isLoading}
				{#each Array(5) as _}
					<div class="rounded-[20px] bg-[#141519] min-h-[88px] animate-pulse"></div>
				{/each}
			{:else if topHoldings.length > 0}
				{#each topHoldings as h, i}
					{@const positive = h.change_pct >= 0}
					{@const gradFn = GRADIENTS[i % GRADIENTS.length]!}
					{@const grad = gradFn(positive)}
					<button
						type="button"
						class="rounded-[20px] p-[1px] text-left w-full transition-transform hover:scale-[1.02]"
						style:background={grad}
						onclick={() => selectTicker(h.ticker)}
					>
						<div class="bg-[#141519] rounded-[19px] px-3 py-2.5 flex flex-col justify-between min-h-[88px] h-full">
							<div class="flex flex-col gap-0.5">
								<span class="text-sm font-bold text-white tabular-nums leading-tight">{formatCurrency(h.price, h.currency)}</span>
								<span class="text-[10px] tabular-nums {positive ? 'text-[#11ec79]' : 'text-[#fc1a1a]'}">
									{positive ? "+" : ""}{formatNumber(h.change, 2)} ({formatNumber(h.change_pct, 1)}%)
								</span>
							</div>
							<div class="flex items-center justify-between mt-auto pt-1.5">
								<span class="text-xs font-semibold text-white tracking-wide">{h.ticker || h.name.slice(0, 6)}</span>
								{#if h.weight > 0}
									<span class="text-[10px] font-bold text-white tabular-nums">{formatNumber(h.weight * 100, 1)}%</span>
								{/if}
							</div>
						</div>
					</button>
				{/each}
			{:else}
				<div class="col-span-5 flex items-center justify-center h-[88px] text-xs text-white/30 border border-dashed border-white/10 rounded-[16px]">
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
	<div class="col-span-8 bg-black rounded-[24px] px-5 py-4 flex flex-col gap-3">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<div class="flex flex-wrap items-center gap-3">
				<span class="text-xs font-semibold uppercase tracking-[0.08em] text-[#85a0bd] whitespace-nowrap">Market Chart</span>
				<div class="flex flex-wrap items-center gap-1">
					{#each profileFilters as pf}
						<button
							type="button"
							class="h-7 px-3 rounded-full text-[11px] font-medium text-white transition-colors leading-none whitespace-nowrap
								{selectedProfile === pf
									? 'bg-[#0177fb]'
									: 'border border-white/20 hover:bg-white/10'}"
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

	<!-- Portfolio Overview — high-density table -->
	<svelte:boundary>
	<div class="col-span-8 bg-black rounded-[24px] px-5 py-4">
		<div class="flex flex-wrap items-center justify-between gap-3 mb-3">
			<span class="text-xs font-semibold uppercase tracking-[0.08em] text-[#85a0bd]">Portfolio Overview</span>
			<div class="flex flex-wrap items-center gap-1">
				{#each ["All", "Gainers", "Losers"] as f}
					<button
						type="button"
						class="h-7 px-3 rounded-full text-[11px] font-medium text-white transition-colors leading-none
							{overviewFilter === f
								? 'bg-[#0177fb]'
								: 'border border-white/20 hover:bg-white/10'}"
						onclick={() => overviewFilter = f}
					>{f}</button>
				{/each}
			</div>
		</div>

		<table class="w-full">
			<thead>
				<tr class="border-b border-white/10">
					<th class="text-left text-[10px] font-semibold uppercase tracking-wider text-[#85a0bd] pb-2 pr-3">Fund</th>
					<th class="text-right text-[10px] font-semibold uppercase tracking-wider text-[#85a0bd] pb-2 pr-3">Last Price</th>
					<th class="text-right text-[10px] font-semibold uppercase tracking-wider text-[#85a0bd] pb-2 pr-3">Change</th>
					<th class="text-right text-[10px] font-semibold uppercase tracking-wider text-[#85a0bd] pb-2 pr-3">AUM</th>
					<th class="text-right text-[10px] font-semibold uppercase tracking-wider text-[#85a0bd] pb-2 w-8"></th>
				</tr>
			</thead>
			<tbody>
				{#if isLoading}
					{#each Array(5) as _}
						<tr class="border-b border-white/5">
							<td class="py-2 pr-3"><div class="h-3 w-32 bg-white/5 rounded animate-pulse"></div></td>
							<td class="py-2 pr-3"><div class="h-3 w-20 bg-white/5 rounded animate-pulse ml-auto"></div></td>
							<td class="py-2 pr-3"><div class="h-3 w-14 bg-white/5 rounded animate-pulse ml-auto"></div></td>
							<td class="py-2 pr-3"><div class="h-3 w-16 bg-white/5 rounded animate-pulse ml-auto"></div></td>
							<td class="py-2"><div class="h-3 w-3 bg-white/5 rounded animate-pulse ml-auto"></div></td>
						</tr>
					{/each}
				{:else if overviewRows.length > 0}
					{#each overviewRows as row}
						{@const positive = row.changePct >= 0}
						{@const isActive = activeTicker === (row.ticker || "").toUpperCase()}
						<tr
							class="border-b border-white/5 cursor-pointer transition-colors hover:bg-white/5 {isActive ? 'bg-[#0177fb]/10' : ''}"
							onclick={() => selectTicker(row.ticker)}
						>
							<td class="py-2 pr-3">
								<div class="flex flex-col leading-tight">
									<span class="text-sm text-white">{row.name.length > 28 ? row.name.slice(0, 28) + "…" : row.name}</span>
									<span class="text-[10px] text-[#85a0bd] tracking-wide">{row.ticker}</span>
								</div>
							</td>
							<td class="py-2 text-sm text-white tabular-nums text-right pr-3">{formatCurrency(row.price, row.currency)}</td>
							<td class="py-2 text-sm tabular-nums text-right pr-3 {positive ? 'text-[#11ec79]' : 'text-[#fc1a1a]'}">
								{positive ? "+" : ""}{formatNumber(row.changePct, 2)}%
							</td>
							<td class="py-2 text-sm text-white tabular-nums text-right pr-3">
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
						<td colspan="5" class="py-6 text-center text-xs text-white/30">No holdings to display</td>
					</tr>
				{/if}
			</tbody>
		</table>
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
	<div class="col-span-4 bg-black rounded-[24px] px-5 py-4">
		<div class="flex items-center justify-between gap-2 mb-3">
			<span class="text-xs font-semibold uppercase tracking-[0.08em] text-[#85a0bd]">Watchlist</span>
			<div class="flex items-center gap-1">
				{#each ["Most Viewed", "Gainers", "Losers"] as f}
					<button
						type="button"
						class="h-7 px-2.5 rounded-full text-[10px] font-medium text-white transition-colors leading-none whitespace-nowrap
							{watchlistFilter === f
								? 'bg-[#0177fb]'
								: 'border border-white/20 hover:bg-white/10'}"
						onclick={() => watchlistFilter = f}
					>{f}</button>
				{/each}
			</div>
		</div>

		{#if isLoading}
			{#each Array(5) as _}
				<div class="flex items-center justify-between py-2 border-b border-white/5">
					<div class="flex flex-col gap-1">
						<div class="h-3 w-24 bg-white/5 rounded animate-pulse"></div>
						<div class="h-2 w-12 bg-white/5 rounded animate-pulse"></div>
					</div>
					<div class="flex flex-col gap-1 items-end">
						<div class="h-3 w-16 bg-white/5 rounded animate-pulse"></div>
						<div class="h-2 w-10 bg-white/5 rounded animate-pulse"></div>
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
					class="w-full text-left flex items-center justify-between py-2 px-2 -mx-2 border-b border-white/5 last:border-0 cursor-pointer transition-colors hover:bg-white/5 {isActive ? 'bg-[#0177fb]/10' : ''}"
					onclick={() => selectTicker(h.ticker)}
				>
					<div class="flex flex-col gap-0.5 leading-tight min-w-0">
						<span class="text-sm text-white truncate">{h.name.length > 22 ? h.name.slice(0, 22) + "…" : h.name}</span>
						<span class="text-[10px] text-[#85a0bd] tracking-wide">{h.ticker}</span>
					</div>
					<div class="flex flex-col gap-0.5 items-end leading-tight tabular-nums">
						<span class="text-sm text-white">{formatCurrency(h.price, h.currency)}</span>
						<span class="text-[10px] {h.change_pct >= 0 ? 'text-[#11ec79]' : 'text-[#fc1a1a]'}">
							{h.change_pct >= 0 ? "+" : ""}{formatNumber(h.change_pct, 2)}%
						</span>
					</div>
				</button>
			{:else}
				<div class="py-6 text-center text-xs text-white/30">No items in watchlist</div>
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
