<!--
  Dashboard — InvestIntell Wealth OS.
  12-column grid layout matching Figma. No risk jargon.
  Holdings + prices from real API (SSR) + WebSocket (live updates).
-->
<script lang="ts">
	import { getContext, onMount } from "svelte";
	import { formatNumber, formatPercent, formatCurrency } from "@investintell/ui";
	import type { RiskStore, RegimeData, DriftAlert, BehaviorAlert } from "$lib/stores/risk-store.svelte";
	import type { MarketDataStore, DashboardSnapshot } from "$lib/stores/market-data.svelte";
	import type { PortfolioAnalyticsStore } from "$lib/stores/portfolio-analytics.svelte";
	import { ArrowUpRight, ChevronDown, TrendingUp, TrendingDown } from "lucide-svelte";

	let { data } = $props();

	const riskStore = getContext<RiskStore>("netz:riskStore");
	const marketStore = getContext<MarketDataStore>("netz:marketDataStore");
	const analytics = getContext<PortfolioAnalyticsStore>("netz:portfolioAnalytics");

	// Seed risk store with SSR data — layout handles start/destroy lifecycle.
	onMount(() => {
		if (data.riskSummary || data.regime) {
			riskStore.seedFromSSR({
				riskSummary: data.riskSummary as Record<string, unknown> | null,
				regime: data.regime as RegimeData | null,
				driftAlerts: data.alerts as { dtw_alerts: DriftAlert[]; behavior_change_alerts: BehaviorAlert[] } | null,
			});
		}

		// Seed market data store with SSR dashboard snapshot
		if (data.dashboardSnapshot) {
			marketStore.seedFromSSR(data.dashboardSnapshot as DashboardSnapshot);
		}
	});

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

	let selectedRange = $state("6M");
	const timeRanges = ["1D", "1W", "1M", "6M", "1Y"];

	let selectedProfile = $state("All");
	const profileFilters = ["Conservative", "Balanced", "Growth", "All"];

	let overviewFilter = $state("All");
	let watchlistFilter = $state("Most Viewed");

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

<!-- 12-column master grid -->
<div class="grid grid-cols-12 gap-6">

	<!-- ══ Row 1: Total AUM (4 cols) + Portfolio Holdings (8 cols) ══ -->

	<!-- Total AUM — glassmorphism -->
	<div class="col-span-4 relative rounded-[24px] overflow-hidden bg-[#0d0d0d]/60 backdrop-blur-[11px] border border-white/5 min-h-[261px]">
		<div class="absolute inset-0 bg-gradient-to-br from-[#0177fb]/15 via-transparent to-transparent pointer-events-none"></div>
		<div class="relative flex flex-col justify-between h-full p-8">
			<div class="flex items-center justify-between">
				<span class="text-[20px] font-medium text-white">Total AUM</span>
				<div class="flex items-center">
					<span class="border border-white rounded-[32px] px-[26px] py-[18px] text-[16px] text-white leading-none">{selectedRange}</span>
					<span class="border border-white rounded-full p-[17px] leading-none">
						<ChevronDown size={24} class="text-white" />
					</span>
				</div>
			</div>

			{#if isLoading}
				<div class="h-[44px] w-48 bg-white/5 rounded-lg animate-pulse"></div>
			{:else}
				<p class="text-[44px] font-bold text-white tracking-tight tabular-nums leading-none">
					{formatCurrency(totalAum)}
				</p>
			{/if}

			<div class="flex items-end gap-2">
				<span class="text-[16px] text-white tracking-[-0.8px]">Return</span>
				{#if totalReturnPct != null}
					{#if totalReturnPct >= 0}
						<TrendingUp size={24} class="text-[#11ec79]" />
						<span class="text-[16px] text-[#11ec79] tracking-[-0.8px]">
							+{formatPercent(totalReturnPct)}{#if totalPnl !== 0} ({formatCurrency(Math.abs(totalPnl))}){/if}
						</span>
					{:else}
						<TrendingDown size={24} class="text-[#fc1a1a]" />
						<span class="text-[16px] text-[#fc1a1a] tracking-[-0.8px]">
							{formatPercent(totalReturnPct)}{#if totalPnl !== 0} ({formatCurrency(Math.abs(totalPnl))}){/if}
						</span>
					{/if}
				{:else if isLoading}
					<div class="h-4 w-24 bg-white/5 rounded animate-pulse"></div>
				{:else}
					<span class="text-[16px] text-[#85a0bd] tracking-[-0.8px]">—</span>
				{/if}
			</div>
		</div>
	</div>

	<!-- Portfolio Holdings (8 cols) -->
	<div class="col-span-8 bg-black rounded-[24px] p-8">
		<div class="flex items-center justify-between mb-6">
			<span class="text-[20px] font-medium text-white">Portfolio Holdings</span>
			<div class="flex items-center">
				<a href="/portfolio/approved" class="border border-white rounded-[32px] px-[26px] py-[18px] text-[16px] text-white leading-none no-underline hover:bg-white/10 transition-colors">See all</a>
				<a href="/portfolio/approved" class="border border-white rounded-full p-[13px] leading-none no-underline hover:bg-white/10 transition-colors">
					<ArrowUpRight size={24} class="text-white" />
				</a>
			</div>
		</div>

		<!-- Cards: 5 cols on wide, stacking below -->
		<div class="grid grid-cols-5 gap-3">
			{#if isLoading}
				{#each Array(5) as _}
					<div class="rounded-[24px] bg-[#141519] min-h-[149px] animate-pulse"></div>
				{/each}
			{:else if topHoldings.length > 0}
				{#each topHoldings as h, i}
					{@const positive = h.change_pct >= 0}
					{@const gradFn = GRADIENTS[i % GRADIENTS.length]!}
					{@const grad = gradFn(positive)}
					<div class="rounded-[24px] p-[1px]" style:background={grad}>
						<div class="bg-[#141519] rounded-[23px] p-4 flex flex-col justify-between min-h-[149px] h-full">
							<div class="flex flex-col gap-1">
								<span class="text-[18px] font-bold text-white tabular-nums">{formatCurrency(h.price, h.currency)}</span>
								<span class="text-[12px] {positive ? 'text-[#11ec79]' : 'text-[#fc1a1a]'}">
									{positive ? "+" : ""}{formatNumber(h.change, 2)} ({formatNumber(h.change_pct, 1)}%)
								</span>
							</div>
							<div class="flex items-center justify-between mt-auto pt-4">
								<span class="text-[12px] text-white">{h.ticker || h.name.slice(0, 8)}</span>
								{#if h.weight > 0}
									<span class="text-[12px] text-[#f3f4f8]">
										<span class="font-bold text-white">{formatNumber(h.weight * 100, 1)}%</span>
									</span>
								{/if}
							</div>
						</div>
					</div>
				{/each}
			{:else}
				<div class="col-span-5 flex items-center justify-center h-[149px] text-white/30 border border-dashed border-white/10 rounded-[16px]">
					No holdings in portfolio
				</div>
			{/if}
		</div>
	</div>

	<!-- ══ Row 2: Portfolio Performance (12 cols) ══ -->
	<div class="col-span-12 bg-black rounded-[24px] p-8">
		<div class="flex flex-wrap items-center justify-between gap-4 mb-8">
			<div class="flex flex-wrap items-center gap-4">
				<span class="text-[20px] font-medium text-white whitespace-nowrap">Portfolio Performance</span>
				<div class="flex flex-wrap items-center gap-0">
					{#each profileFilters as pf}
						<button
							type="button"
							class="h-[55px] px-[26px] rounded-[32px] text-[16px] text-white transition-colors leading-none whitespace-nowrap
								{selectedProfile === pf
									? 'bg-[#0177fb]'
									: 'border border-white hover:bg-white/10'}"
							onclick={() => selectedProfile = pf}
						>{pf}</button>
					{/each}
				</div>
			</div>

			<div class="flex flex-wrap items-center gap-0">
				{#each timeRanges as tr}
					<button
						type="button"
						class="h-[55px] px-[26px] rounded-[32px] text-[16px] text-white transition-colors leading-none
							{selectedRange === tr
								? 'bg-[#0177fb]'
								: 'border border-white hover:bg-white/10'}"
						onclick={() => selectedRange = tr}
					>{tr}</button>
				{/each}
			</div>
		</div>

		<div class="h-[260px] flex items-center justify-center text-white/30 border border-dashed border-white/10 rounded-[16px]">
			Performance chart ({selectedProfile} · {selectedRange})
		</div>
	</div>

	<!-- ���═ Row 3: Portfolio Overview (8 cols) + Watchlist (4 cols) ══ -->

	<!-- Portfolio Overview -->
	<div class="col-span-8 bg-black rounded-t-[24px] p-8">
		<div class="flex flex-wrap items-center justify-between gap-4 mb-6">
			<span class="text-[20px] font-medium text-white">Portfolio Overview</span>
			<div class="flex flex-wrap items-center gap-0">
				{#each ["All", "Gainers", "Losers"] as f}
					<button
						type="button"
						class="h-[55px] px-[26px] rounded-[32px] text-[16px] text-white transition-colors leading-none
							{overviewFilter === f
								? 'bg-[#0177fb]'
								: 'border border-white hover:bg-white/10'}"
						onclick={() => overviewFilter = f}
					>{f}</button>
				{/each}
			</div>
		</div>

		<table class="w-full">
			<thead>
				<tr class="border-b border-white/10">
					<th class="text-left text-[17px] font-semibold text-white pb-4 pr-4">Fund</th>
					<th class="text-left text-[17px] font-semibold text-white pb-4 pr-4">Last Price</th>
					<th class="text-left text-[17px] font-semibold text-white pb-4 pr-4">Change</th>
					<th class="text-left text-[17px] font-semibold text-white pb-4 pr-4">AUM</th>
					<th class="text-left text-[17px] font-semibold text-white pb-4">Trend</th>
				</tr>
			</thead>
			<tbody>
				{#if isLoading}
					{#each Array(3) as _}
						<tr class="border-b border-white/10">
							<td class="py-5 pr-4"><div class="h-4 w-32 bg-white/5 rounded animate-pulse"></div></td>
							<td class="py-5 pr-4"><div class="h-4 w-24 bg-white/5 rounded animate-pulse"></div></td>
							<td class="py-5 pr-4"><div class="h-4 w-16 bg-white/5 rounded animate-pulse"></div></td>
							<td class="py-5 pr-4"><div class="h-4 w-20 bg-white/5 rounded animate-pulse"></div></td>
							<td class="py-5"><div class="h-4 w-8 bg-white/5 rounded animate-pulse"></div></td>
						</tr>
					{/each}
				{:else if overviewRows.length > 0}
					{#each overviewRows as row}
						{@const positive = row.changePct >= 0}
						<tr class="border-b border-white/10">
							<td class="py-5 text-[16px] text-white pr-4">
								<div class="flex flex-col">
									<span>{row.name.length > 30 ? row.name.slice(0, 30) + "…" : row.name}</span>
									<span class="text-[13px] text-[#85a0bd]">{row.ticker}</span>
								</div>
							</td>
							<td class="py-5 text-[16px] text-white tabular-nums pr-4">{formatCurrency(row.price, row.currency)}</td>
							<td class="py-5 text-[16px] tabular-nums pr-4 {positive ? 'text-[#11ec79]' : 'text-[#fc1a1a]'}">
								{positive ? "+" : ""}{formatNumber(row.changePct, 2)}%
							</td>
							<td class="py-5 text-[16px] text-white tabular-nums pr-4">
								{row.aum ? formatCurrency(row.aum) : "—"}
							</td>
							<td class="py-5">
								{#if positive}
									<TrendingUp size={20} class="text-[#11ec79]" />
								{:else}
									<TrendingDown size={20} class="text-[#fc1a1a]" />
								{/if}
							</td>
						</tr>
					{/each}
				{:else}
					<tr>
						<td colspan="5" class="py-8 text-center text-white/30">No holdings to display</td>
					</tr>
				{/if}
			</tbody>
		</table>
	</div>

	<!-- Watchlist -->
	<div class="col-span-4 bg-black rounded-t-[24px] p-8">
		<span class="text-[20px] font-medium text-white mb-6 block">Watchlist</span>
		<div class="flex flex-wrap items-center gap-0 mb-8">
			{#each ["Most Viewed", "Gainers", "Losers"] as f}
				<button
					type="button"
					class="h-[55px] px-[21px] rounded-[32px] text-[16px] text-white transition-colors leading-none whitespace-nowrap
						{watchlistFilter === f
							? 'bg-[#0177fb]'
							: 'border border-white hover:bg-white/10'}"
					onclick={() => watchlistFilter = f}
				>{f}</button>
			{/each}
		</div>

		{#if isLoading}
			{#each Array(3) as _}
				<div class="flex items-center justify-between py-5 border-b border-white/10">
					<div class="flex flex-col gap-2">
						<div class="h-4 w-28 bg-white/5 rounded animate-pulse"></div>
						<div class="h-3 w-16 bg-white/5 rounded animate-pulse"></div>
					</div>
					<div class="flex flex-col gap-2 items-end">
						<div class="h-4 w-20 bg-white/5 rounded animate-pulse"></div>
						<div class="h-3 w-14 bg-white/5 rounded animate-pulse"></div>
					</div>
				</div>
			{/each}
		{:else}
			{@const watchlistRows = watchlistFilter === "Gainers"
				? marketStore.holdings.filter(h => h.change_pct > 0).slice(0, 5)
				: watchlistFilter === "Losers"
					? marketStore.holdings.filter(h => h.change_pct < 0).slice(0, 5)
					: marketStore.holdings.slice(0, 5)}
			{#each watchlistRows as h, i}
				{#if i > 0}
					<div class="border-t border-white/10"></div>
				{/if}
				<div class="flex items-center justify-between py-5">
					<div class="flex flex-col gap-1">
						<span class="text-[16px] text-white">{h.name.length > 20 ? h.name.slice(0, 20) + "…" : h.name}</span>
						<span class="text-[14px] text-[#c2c2c2]">{h.ticker}</span>
					</div>
					<div class="flex flex-col gap-1 items-end">
						<span class="text-[16px] text-white tabular-nums">{formatCurrency(h.price, h.currency)}</span>
						<span class="text-[14px] tabular-nums {h.change_pct >= 0 ? 'text-[#11ec79]' : 'text-[#fc1a1a]'}">
							{h.change_pct >= 0 ? "+" : ""}{formatNumber(h.change_pct, 2)}%
						</span>
					</div>
				</div>
			{:else}
				<div class="py-8 text-center text-white/30">No items in watchlist</div>
			{/each}
		{/if}
	</div>
</div>
