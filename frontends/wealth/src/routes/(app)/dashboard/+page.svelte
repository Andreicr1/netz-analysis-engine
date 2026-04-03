<!--
  Dashboard — InvestIntell Wealth OS.
  12-column grid layout matching Figma. No risk jargon.
-->
<script lang="ts">
	import { getContext, onMount } from "svelte";
	import { formatNumber, formatPercent } from "@investintell/ui";
	import type { RiskStore } from "$lib/stores/risk-store.svelte";
	import { ArrowUpRight, ChevronDown, TrendingUp, TrendingDown } from "lucide-svelte";

	let { data } = $props();

	const riskStore = getContext<RiskStore>("netz:riskStore");

	onMount(() => {
		const timer = setTimeout(() => {
			try { riskStore.start(); } catch (e) { console.warn("Risk store failed to start:", e); }
		}, 2000);
		return () => { clearTimeout(timer); riskStore.destroy(); };
	});

	const PROFILES = ["conservative", "moderate", "growth"] as const;
	type Profile = typeof PROFILES[number];

	function getSnapshot(profile: Profile) {
		return (data.snapshotsByProfile as Record<string, unknown>)?.[profile] as {
			nav?: number; ytd_return?: number;
		} | null;
	}

	let totalAum = $derived(PROFILES.reduce((sum, p) => sum + (getSnapshot(p)?.nav ?? 0), 0));

	let avgReturn = $derived(() => {
		const returns = PROFILES.map(p => getSnapshot(p)?.ytd_return).filter((r): r is number => r != null);
		return returns.length > 0 ? returns.reduce((a, b) => a + b, 0) / returns.length : null;
	});

	let selectedRange = $state("6M");
	const timeRanges = ["1D", "1W", "1M", "6M", "1Y"];

	let selectedProfile = $state("All");
	const profileFilters = ["Conservative", "Balanced", "Growth", "All"];

	let overviewFilter = $state("All");
	let watchlistFilter = $state("Most Viewed");

	// Holdings with per-card gradient border direction (Figma nodes 2:193–2:199)
	const holdings = [
		{ price: 1721.3, change: 12.31, changePct: 0.7, positive: true,  ticker: "TICKER", units: 104,
		  borderGrad: "linear-gradient(to top, rgba(17,236,121,0.5), rgba(17,236,121,0.15) 50%, transparent)" },
		{ price: 1521.3, change: 12.31, changePct: 0.7, positive: false, ticker: "TICKER", units: 124,
		  borderGrad: "linear-gradient(to bottom, rgba(252,26,26,0.5), rgba(252,26,26,0.15) 50%, transparent)" },
		{ price: 1721.3, change: 12.31, changePct: 0.7, positive: true,  ticker: "TICKER", units: 10,
		  borderGrad: "linear-gradient(to bottom right, rgba(17,236,121,0.5), rgba(17,236,121,0.15) 50%, transparent)" },
		{ price: 1721.3, change: 12.31, changePct: 0.7, positive: false, ticker: "TICKER", units: 110,
		  borderGrad: "linear-gradient(to bottom left, rgba(252,26,26,0.5), rgba(252,26,26,0.15) 50%, transparent)" },
		{ price: 1721.3, change: 12.31, changePct: 0.7, positive: true,  ticker: "TICKER", units: 104,
		  borderGrad: "linear-gradient(to top right, rgba(17,236,121,0.5), rgba(17,236,121,0.12) 50%, transparent)" },
	];
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
					<span class="border border-white rounded-[32px] px-[26px] py-[18px] text-[16px] text-white leading-none">6M</span>
					<span class="border border-white rounded-full p-[17px] leading-none">
						<ChevronDown size={24} class="text-white" />
					</span>
				</div>
			</div>

			<p class="text-[44px] font-bold text-white tracking-tight tabular-nums leading-none">
				$ {totalAum > 0 ? formatNumber(totalAum, 2) : "12,304.11"}
			</p>

			<div class="flex items-end gap-2">
				<span class="text-[16px] text-white tracking-[-0.8px]">Return</span>
				{#if avgReturn() != null}
					<TrendingUp size={24} class="text-[#11ec79]" />
					<span class="text-[16px] text-[#11ec79] tracking-[-0.8px]">
						+{formatPercent(avgReturn()!)} ($ {formatNumber(Math.abs(totalAum * (avgReturn()! / 100)), 0)})
					</span>
				{:else}
					<TrendingUp size={24} class="text-[#11ec79]" />
					<span class="text-[16px] text-[#11ec79] tracking-[-0.8px]">+3.5% ($ 532)</span>
				{/if}
			</div>
		</div>
	</div>

	<!-- Portfolio Holdings (8 cols) -->
	<div class="col-span-8 bg-black rounded-[24px] p-8">
		<div class="flex items-center justify-between mb-6">
			<span class="text-[20px] font-medium text-white">Portfolio Holdings</span>
			<div class="flex items-center">
				<span class="border border-white rounded-[32px] px-[26px] py-[18px] text-[16px] text-white leading-none">See all</span>
				<span class="border border-white rounded-full p-[13px] leading-none">
					<ArrowUpRight size={24} class="text-white" />
				</span>
			</div>
		</div>

		<!-- Cards: 5 cols on wide, 3 on medium, stacking vertically below -->
		<div class="grid grid-cols-5 gap-3">
			{#each holdings as h}
				<div class="rounded-[24px] p-[1px]" style:background={h.borderGrad}>
					<div class="bg-[#141519] rounded-[23px] p-4 flex flex-col justify-between min-h-[149px] h-full">
						<div class="flex flex-col gap-1">
							<span class="text-[18px] font-bold text-white tabular-nums">$ {formatNumber(h.price, 1)}</span>
							<span class="text-[12px] {h.positive ? 'text-[#11ec79]' : 'text-[#fc1a1a]'}">
								{h.positive ? "+" : "-"}{formatNumber(h.change, 2)} ({formatNumber(h.changePct, 1)}%)
							</span>
						</div>
						<div class="flex items-center justify-between mt-auto pt-4">
							<span class="text-[12px] text-white">{h.ticker}</span>
							<span class="text-[12px] text-[#f3f4f8]">
								Units <span class="font-bold text-white">{h.units}</span>
							</span>
						</div>
					</div>
				</div>
			{/each}
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
							class="h-[55px] px-[21px] rounded-[32px] text-[16px] text-white transition-colors leading-none whitespace-nowrap
								{selectedProfile === pf
									? 'bg-[#0177fb]'
									: 'bg-white/[0.13] hover:bg-white/[0.2]'}"
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

	<!-- ══ Row 3: Portfolio Overview (8 cols) + Watchlist (4 cols) ══ -->

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
					<th class="text-left text-[17px] font-semibold text-white pb-4 pr-4">Volume</th>
					<th class="text-left text-[17px] font-semibold text-white pb-4">Last 7 days</th>
				</tr>
			</thead>
			<tbody>
				<tr class="border-b border-white/10">
					<td class="py-5 text-[16px] text-white pr-4">TICKER</td>
					<td class="py-5 text-[16px] text-white tabular-nums pr-4">$26,000.21</td>
					<td class="py-5 text-[16px] text-white tabular-nums pr-4">+3.4%</td>
					<td class="py-5 text-[16px] text-white tabular-nums pr-4">$ 564.06 B</td>
					<td class="py-5 text-[16px] text-white tabular-nums pr-4">$ 379B</td>
					<td class="py-5"><TrendingUp size={20} class="text-[#11ec79]" /></td>
				</tr>
				<tr class="border-b border-white/10">
					<td class="py-5 text-[16px] text-white pr-4">TICKER</td>
					<td class="py-5 text-[16px] text-white tabular-nums pr-4">$32,000.21</td>
					<td class="py-5 text-[16px] text-white tabular-nums pr-4">-3.4%</td>
					<td class="py-5 text-[16px] text-white tabular-nums pr-4">$ 564.06 B</td>
					<td class="py-5 text-[16px] text-white tabular-nums pr-4">$ 379B</td>
					<td class="py-5"><TrendingDown size={20} class="text-[#fc1a1a]" /></td>
				</tr>
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

		{#each [0, 1] as i}
			{#if i > 0}
				<div class="border-t border-white/10"></div>
			{/if}
			<div class="flex items-center justify-between py-5">
				<div class="flex flex-col gap-1">
					<span class="text-[16px] text-white">Fund Name</span>
					<span class="text-[14px] text-[#c2c2c2]">TICKER</span>
				</div>
				<div class="flex flex-col gap-1 items-end">
					<span class="text-[16px] text-white tabular-nums">$2,310.5</span>
					<span class="text-[14px] text-[#11ec79] tabular-nums">+2.34%</span>
				</div>
			</div>
		{/each}
	</div>
</div>
