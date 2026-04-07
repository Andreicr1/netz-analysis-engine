<!--
  Screener Analytics — eVestment-style fund analytics for the global catalog.
  Search + filters (fund type, strategy) + fund selector + window toggle.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { page as pageState } from "$app/state";
	import { EmptyState } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import Loader2 from "lucide-svelte/icons/loader-2";
	import { Search } from "lucide-svelte";
	import { createClientApiClient } from "$lib/api/client";
	import type { EntityAnalyticsResponse } from "$lib/types/entity-analytics";
	import type { PeerGroupResult, MonteCarloResult } from "$lib/types/analytics";
	import type { UnifiedFundItem, UnifiedCatalogPage } from "$lib/types/catalog";

	import RiskStatisticsGrid from "$lib/components/analytics/entity/RiskStatisticsGrid.svelte";
	import DrawdownChart from "$lib/components/analytics/entity/DrawdownChart.svelte";
	import CaptureRatiosPanel from "$lib/components/analytics/entity/CaptureRatiosPanel.svelte";
	import RollingReturnsChart from "$lib/components/analytics/entity/RollingReturnsChart.svelte";
	import ReturnDistributionChart from "$lib/components/analytics/entity/ReturnDistributionChart.svelte";
	import ReturnStatisticsPanel from "$lib/components/analytics/entity/ReturnStatisticsPanel.svelte";
	import TailRiskPanel from "$lib/components/analytics/entity/TailRiskPanel.svelte";
	import PeerGroupPanel from "$lib/components/analytics/entity/PeerGroupPanel.svelte";
	import MonteCarloPanel from "$lib/components/analytics/entity/MonteCarloPanel.svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	// ── Restore from URL params (e.g. from L2 link) ─────────────────
	let initialFundId = $derived(pageState.url.searchParams.get("fund") ?? "");

	// ── Filter state ────────────────────────────────────────────────
	let searchQuery = $state("");
	let filterRegion = $state("");
	let filterUniverse = $state("");
	let filterStrategy = $state("");
	let searchDebounce: ReturnType<typeof setTimeout> | null = null;

	// ── Fund catalog ────────────────────────────────────────────────
	let funds = $state<UnifiedFundItem[]>([]);
	let totalFunds = $state(0);
	let loadingList = $state(true);

	async function fetchCatalog() {
		loadingList = true;
		try {
			const params: Record<string, string> = {
				page_size: "100",
				in_universe: "true",
				sort: "name_asc",
			};
			if (searchQuery) params.q = searchQuery;
			if (filterRegion) params.region = filterRegion;
			if (filterUniverse) params.fund_universe = filterUniverse;
			if (filterStrategy) params.strategy_label = filterStrategy;

			const result = await api.get<UnifiedCatalogPage>("/screener/catalog", params);
			funds = result.items;
			totalFunds = result.total;
		} catch {
			funds = [];
			totalFunds = 0;
		} finally {
			loadingList = false;
		}
	}

	// Initial load
	$effect(() => { fetchCatalog(); });

	function onSearchInput(e: Event) {
		const val = (e.target as HTMLInputElement).value;
		searchQuery = val;
		if (searchDebounce) clearTimeout(searchDebounce);
		searchDebounce = setTimeout(() => fetchCatalog(), 350);
	}

	function setFilterRegion(val: string) {
		filterRegion = filterRegion === val ? "" : val;
		fetchCatalog();
	}

	function setFilterUniverse(val: string) {
		filterUniverse = filterUniverse === val ? "" : val;
		fetchCatalog();
	}

	function setFilterStrategy(val: string) {
		filterStrategy = filterStrategy === val ? "" : val;
		fetchCatalog();
	}

	// ── Selection state ─────────────────────────────────────────────
	let selectedFundId = $state(initialFundId);
	let fundWindow = $state("1y");
	const windows = ["3m", "6m", "1y", "3y", "5y"] as const;

	// Auto-load if fund came from URL (one-shot)
	let urlFundHandled = false;
	$effect(() => {
		const fundFromUrl = pageState.url.searchParams.get("fund");
		if (fundFromUrl && !urlFundHandled) {
			urlFundHandled = true;
			selectedFundId = fundFromUrl;
			loadFundAnalytics(fundFromUrl, fundWindow);
		}
	});

	// ── Analytics data ──────────────────────────────────────────────
	let analytics = $state<EntityAnalyticsResponse | null>(null);
	let peerGroup = $state<PeerGroupResult | null>(null);
	let mcResult = $state<MonteCarloResult | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let mcLoading = $state(false);

	async function loadFundAnalytics(fundId: string, window: string) {
		if (!fundId) { analytics = null; peerGroup = null; return; }
		loading = true;
		error = null;
		mcResult = null;
		try {
			const [a, p] = await Promise.all([
				api.get<EntityAnalyticsResponse>(`/analytics/entity/${fundId}`, { window }),
				api.get<PeerGroupResult>(`/analytics/peer-group/${fundId}`).catch(() => null),
			]);
			analytics = a;
			peerGroup = p;
		} catch (e) {
			const msg = e instanceof Error ? e.message : "Failed to load analytics";
			if (msg.includes("resolve entity") || msg.includes("not found") || msg.includes("404")) {
				error = "This fund has not been imported yet — analytics require NAV data.";
			} else if (msg.includes("Insufficient") || msg.includes("NAV data")) {
				error = "Insufficient data to compute analytics for this fund.";
			} else {
				error = msg;
			}
			analytics = null;
			peerGroup = null;
		} finally {
			loading = false;
		}
	}

	function handleFundSelect(e: Event) {
		selectedFundId = (e.target as HTMLSelectElement).value;
		loadFundAnalytics(selectedFundId, fundWindow);
	}

	function switchWindow(w: string) {
		fundWindow = w;
		if (selectedFundId) loadFundAnalytics(selectedFundId, w);
	}

	async function runMonteCarlo() {
		if (!analytics || mcLoading) return;
		mcLoading = true;
		try {
			mcResult = await api.post<MonteCarloResult>("/analytics/monte-carlo", {
				entity_id: analytics.entity_id,
				n_simulations: 10_000,
				statistic: "max_drawdown",
			});
		} catch {
			mcResult = null;
		} finally {
			mcLoading = false;
		}
	}

	// ── Filter pills ────────────────────────────────────────────────
	const REGIONS = [
		{ label: "US", value: "US" },
		{ label: "EU", value: "EU" },
	] as const;
	const UNIVERSES = [
		{ label: "Mutual Fund", value: "mutual_fund" },
		{ label: "ETF", value: "etf" },
		{ label: "CEF", value: "closed_end" },
		{ label: "BDC", value: "bdc" },
		{ label: "Hedge Fund", value: "hedge_fund" },
		{ label: "UCITS", value: "ucits" },
	] as const;
	const STRATEGIES = ["Private Credit", "Long/Short Equity", "Multi-Strategy", "Growth Equity", "Buyout", "Infrastructure"];
</script>

<svelte:head>
	<title>Analytics — Screener — InvestIntell</title>
</svelte:head>

<div class="ea-page">

	<!-- ── Toolbar row 1: Search + Region + Universe pills ── -->
	<div class="ea-toolbar">
		<div class="ea-toolbar-left">
			<div class="ea-search">
				<Search size={18} />
				<input
					type="text"
					class="ea-search-input"
					placeholder="Search by name, ticker, manager..."
					value={searchQuery}
					oninput={onSearchInput}
				/>
			</div>

			<div class="ea-toggles">
				{#each REGIONS as r (r.value)}
					<button
						class="ea-toggle"
						class:ea-toggle--active={filterRegion === r.value}
						onclick={() => setFilterRegion(r.value)}
					>
						{r.label}
					</button>
				{/each}
			</div>

			<div class="ea-separator"></div>

			<div class="ea-toggles">
				{#each UNIVERSES as u (u.value)}
					<button
						class="ea-toggle"
						class:ea-toggle--active={filterUniverse === u.value}
						onclick={() => setFilterUniverse(u.value)}
					>
						{u.label}
					</button>
				{/each}
			</div>
		</div>

		<span class="ea-count">{totalFunds.toLocaleString()} funds</span>
	</div>

	<!-- ── Toolbar row 2: Strategy pills ── -->
	<div class="ea-toolbar">
		<div class="ea-toolbar-left">
			<div class="ea-toggles">
				{#each STRATEGIES as st (st)}
					<button
						class="ea-toggle ea-toggle--strategy"
						class:ea-toggle--active={filterStrategy === st}
						onclick={() => setFilterStrategy(st)}
					>
						{st}
					</button>
				{/each}
			</div>
		</div>
	</div>

	<div class="ea-toolbar">
		<div class="ea-toolbar-left">
			<select class="ea-select" onchange={handleFundSelect} value={selectedFundId}>
				<option value="">Select a fund...</option>
				{#each funds as fund (fund.external_id)}
					<option value={fund.external_id}>
						{fund.name}{fund.ticker ? ` (${fund.ticker})` : ""}{fund.manager_name ? ` — ${fund.manager_name}` : ""}
					</option>
				{/each}
			</select>

			{#if selectedFundId}
				<div class="ea-windows">
					{#each windows as w (w)}
						<button
							class="ea-window-pill"
							class:ea-window-pill--active={fundWindow === w}
							onclick={() => switchWindow(w)}
						>
							{w.toUpperCase()}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	</div>

	<!-- Content -->
	<div class="ea-content">
		{#if loadingList && funds.length === 0}
			<div class="ea-loading">
				<Loader2 class="h-6 w-6 animate-spin text-[#0177fb]" />
				<span>Loading fund catalog...</span>
			</div>
		{:else if !selectedFundId}
			<EmptyState
				title="Fund Universe Analytics"
				message="Search and filter funds above, then select one to view risk statistics, drawdown, capture ratios, rolling returns, distribution, tail risk, peer rankings, and Monte Carlo."
			/>
		{:else if loading}
			<div class="ea-loading">
				<Loader2 class="h-6 w-6 animate-spin text-[#0177fb]" />
				<span>Loading analytics...</span>
			</div>
		{:else if error}
			<div class="ea-error">{error}</div>
		{:else if analytics}
			<RiskStatisticsGrid stats={analytics.risk_statistics} asOfDate={analytics.as_of_date} />
			<DrawdownChart drawdown={analytics.drawdown} />

			<div class="ea-row-2">
				<CaptureRatiosPanel capture={analytics.capture} />
				<RollingReturnsChart rollingReturns={analytics.rolling_returns} />
			</div>

			<ReturnDistributionChart distribution={analytics.distribution} />

			{#if analytics.return_statistics}
				<ReturnStatisticsPanel stats={analytics.return_statistics} />
			{/if}

			{#if analytics.tail_risk}
				<TailRiskPanel tailRisk={analytics.tail_risk} />
			{/if}

			{#if peerGroup}
				<PeerGroupPanel {peerGroup} />
			{/if}

			{#if mcResult}
				<MonteCarloPanel mc={mcResult} />
			{:else}
				<div class="ea-mc-trigger">
					<Button variant="outline" onclick={runMonteCarlo} disabled={mcLoading}>
						{mcLoading ? "Running..." : "Run Monte Carlo (10k paths)"}
					</Button>
				</div>
			{/if}
		{/if}
	</div>
</div>

<style>
	.ea-page {
		height: 100%;
		display: flex;
		flex-direction: column;
		gap: 16px;
		overflow: hidden;
	}

	/* ── Toolbar ── */
	.ea-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		flex-shrink: 0;
	}

	.ea-toolbar-left {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	/* ── Search ── */
	.ea-search {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 10px 20px;
		border: 1px solid #fff;
		border-radius: 36px;
		background: #000;
		color: #cbccd1;
		max-width: 360px;
		flex: 1;
	}

	.ea-search-input {
		flex: 1;
		min-width: 0;
		border: none !important;
		background: transparent !important;
		color: #fff;
		font-size: 14px;
		font-weight: 400;
		font-family: "Urbanist", sans-serif;
		outline: none !important;
		box-shadow: none !important;
		padding: 0;
	}

	.ea-search-input::placeholder { color: #cbccd1; }

	.ea-separator {
		width: 1px;
		height: 24px;
		background: #3a3b44;
		margin: 0 4px;
	}

	/* ── Toggles (fund type + strategy) ── */
	.ea-toggles {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.ea-toggle {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 6px 14px;
		border: 1px solid #3a3b44;
		border-radius: 36px;
		background: transparent;
		color: #a1a1aa;
		font-size: 13px;
		font-weight: 600;
		font-family: "Urbanist", sans-serif;
		cursor: pointer;
		white-space: nowrap;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
	}

	.ea-toggle:hover { background: #22232a; border-color: #52525b; color: #fff; }

	.ea-toggle--active {
		background: #0177fb;
		border-color: transparent;
		color: #fff;
	}

	.ea-toggle--active:hover { background: #0166d9; }

	.ea-toggle--strategy {
		font-size: 12px;
		padding: 5px 12px;
	}

	/* ── Count ── */
	.ea-count {
		font-size: 14px;
		color: #fff;
		font-weight: 400;
		font-family: "Urbanist", sans-serif;
		white-space: nowrap;
	}

	/* ── Fund selector ── */
	.ea-select {
		min-width: 400px;
		height: 40px;
		padding: 0 16px;
		border: 1px solid #3a3b44;
		border-radius: 36px;
		background: #000;
		color: #fff;
		font-size: 14px;
		font-family: "Urbanist", sans-serif;
		cursor: pointer;
	}

	/* ── Window pills ── */
	.ea-windows {
		display: flex;
		gap: 0;
	}

	.ea-window-pill {
		padding: 8px 16px;
		border: 1px solid #3a3b44;
		background: transparent;
		color: #a1a1aa;
		font-size: 13px;
		font-weight: 600;
		font-family: "Urbanist", sans-serif;
		cursor: pointer;
		transition: background 120ms ease, color 120ms ease;
	}

	.ea-window-pill:first-child { border-radius: 36px 0 0 36px; }
	.ea-window-pill:last-child { border-radius: 0 36px 36px 0; }
	.ea-window-pill:not(:first-child) { border-left: none; }

	.ea-window-pill:hover { background: #22232a; color: #fff; }

	.ea-window-pill--active {
		background: #0177fb;
		border-color: transparent;
		color: #fff;
	}

	.ea-window-pill--active:hover { background: #0166d9; }

	/* ── Content ── */
	.ea-content {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 20px;
	}

	.ea-row-2 {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 16px;
	}

	.ea-loading {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 10px;
		padding: 64px 24px;
		color: #85a0bd;
		font-size: 14px;
		font-weight: 500;
		font-family: "Urbanist", sans-serif;
	}

	.ea-error {
		padding: 48px 24px;
		text-align: center;
		color: #ef4444;
		font-size: 14px;
	}

	.ea-mc-trigger {
		text-align: center;
		padding: 24px;
	}
</style>
