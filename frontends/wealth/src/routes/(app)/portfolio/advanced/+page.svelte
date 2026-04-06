<!--
  Advanced — eVestment-style entity analytics for funds within the portfolio.
  Fund selector (from portfolio universe) + window toggle, then full-width panels.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { EmptyState } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import Loader2 from "lucide-svelte/icons/loader-2";
	import { createClientApiClient } from "$lib/api/client";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import type { EntityAnalyticsResponse } from "$lib/types/entity-analytics";
	import type { PeerGroupResult, MonteCarloResult } from "$lib/types/analytics";
	import type { UniverseAsset } from "$lib/types/universe";
	import type { PageData } from "./$types";

	import RiskStatisticsGrid from "$lib/components/analytics/entity/RiskStatisticsGrid.svelte";
	import DrawdownChart from "$lib/components/analytics/entity/DrawdownChart.svelte";
	import CaptureRatiosPanel from "$lib/components/analytics/entity/CaptureRatiosPanel.svelte";
	import RollingReturnsChart from "$lib/components/analytics/entity/RollingReturnsChart.svelte";
	import ReturnDistributionChart from "$lib/components/analytics/entity/ReturnDistributionChart.svelte";
	import ReturnStatisticsPanel from "$lib/components/analytics/entity/ReturnStatisticsPanel.svelte";
	import TailRiskPanel from "$lib/components/analytics/entity/TailRiskPanel.svelte";
	import PeerGroupPanel from "$lib/components/analytics/entity/PeerGroupPanel.svelte";
	import MonteCarloPanel from "$lib/components/analytics/entity/MonteCarloPanel.svelte";

	let { data }: { data: PageData } = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	// ── Fund list: portfolio funds (if constructed) or full universe ──
	let instruments = $derived((data.instruments ?? []) as UniverseAsset[]);
	let portfolioFundIds = $derived(
		new Set(workspace.funds.map((f) => f.instrument_id))
	);
	let fundList = $derived(
		portfolioFundIds.size > 0
			? instruments.filter((i) => portfolioFundIds.has(i.instrument_id))
			: instruments
	);

	// ── Selection state ─────────────────────────────────────────────
	let selectedFundId = $state("");
	let fundWindow = $state("1y");
	const windows = ["3m", "6m", "1y", "3y", "5y"] as const;

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
			error = e instanceof Error ? e.message : "Failed to load analytics";
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
</script>

<svelte:head>
	<title>Advanced — Portfolio — InvestIntell</title>
</svelte:head>

<div class="adv-page">

	<!-- Toolbar: fund selector + window pills -->
	<div class="adv-toolbar">
		<select class="adv-select" onchange={handleFundSelect} value={selectedFundId}>
			<option value="">Select a fund...</option>
			{#each fundList as inst (inst.instrument_id)}
				<option value={inst.instrument_id}>{inst.fund_name}</option>
			{/each}
		</select>

		{#if selectedFundId}
			<div class="adv-windows">
				{#each windows as w (w)}
					<button
						class="adv-window-pill"
						class:adv-window-pill--active={fundWindow === w}
						onclick={() => switchWindow(w)}
					>
						{w.toUpperCase()}
					</button>
				{/each}
			</div>
		{/if}

		{#if portfolioFundIds.size > 0}
			<span class="adv-scope">{fundList.length} portfolio funds</span>
		{/if}
	</div>

	<!-- Content -->
	<div class="adv-content">
		{#if fundList.length === 0}
			<EmptyState
				title="No funds available"
				message="Select a portfolio in the Builder and construct it to access fund-level advanced analytics."
			/>
		{:else if !selectedFundId}
			<EmptyState
				title="Fund-Level Advanced Analytics"
				message="Select a fund above to view risk statistics, drawdown, capture ratios, rolling returns, distribution, tail risk, peer rankings, and Monte Carlo."
			/>
		{:else if loading}
			<div class="adv-loading">
				<Loader2 class="h-6 w-6 animate-spin text-[#0177fb]" />
				<span>Loading analytics...</span>
			</div>
		{:else if error}
			<div class="adv-error">{error}</div>
		{:else if analytics}
			<RiskStatisticsGrid stats={analytics.risk_statistics} asOfDate={analytics.as_of_date} />
			<DrawdownChart drawdown={analytics.drawdown} />

			<div class="adv-row-2">
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
				<div class="adv-mc-trigger">
					<Button variant="outline" onclick={runMonteCarlo} disabled={mcLoading}>
						{mcLoading ? "Running..." : "Run Monte Carlo (10k paths)"}
					</Button>
				</div>
			{/if}
		{/if}
	</div>
</div>

<style>
	.adv-page {
		height: 100%;
		display: flex;
		flex-direction: column;
		gap: 24px;
		overflow: hidden;
	}

	/* ── Toolbar ── */
	.adv-toolbar {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-shrink: 0;
	}

	.adv-select {
		min-width: 320px;
		height: 40px;
		padding: 0 16px;
		border: 1px solid #3a3b44;
		border-radius: 36px;
		background: #000;
		color: #fff;
		font-size: 14px;
		font-family: "Urbanist", sans-serif;
		cursor: pointer;
		appearance: none;
	}

	.adv-windows {
		display: flex;
		gap: 0;
	}

	.adv-window-pill {
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

	.adv-window-pill:first-child { border-radius: 36px 0 0 36px; }
	.adv-window-pill:last-child { border-radius: 0 36px 36px 0; }
	.adv-window-pill:not(:first-child) { border-left: none; }

	.adv-window-pill:hover { background: #22232a; color: #fff; }

	.adv-window-pill--active {
		background: #0177fb;
		border-color: transparent;
		color: #fff;
	}

	.adv-window-pill--active:hover { background: #0166d9; }

	.adv-scope {
		font-size: 13px;
		color: #85a0bd;
		font-family: "Urbanist", sans-serif;
		white-space: nowrap;
	}

	/* ── Content ── */
	.adv-content {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 20px;
	}

	.adv-row-2 {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 16px;
	}

	.adv-loading {
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

	.adv-error {
		padding: 48px 24px;
		text-align: center;
		color: #ef4444;
		font-size: 14px;
	}

	.adv-mc-trigger {
		text-align: center;
		padding: 24px;
	}
</style>
