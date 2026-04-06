<!--
  Portfolio Workspace — Unified App-in-App.
  Left sidebar: Title + Models / Universe / Policy pills.
  Right main: Chart + pill-tabbed detail panels.
  Design system: Figma One X — dark premium, glassmorphism, pill navigation.
  Navigation pills match Screener page pattern (Urbanist, 36px radius, #0177fb active).
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { Button } from "@investintell/ui/components/ui/button";
	import Settings2 from "lucide-svelte/icons/settings-2";
	import Globe from "lucide-svelte/icons/globe";
	import Folders from "lucide-svelte/icons/folders";
	import Play from "lucide-svelte/icons/play";
	import BarChart2 from "lucide-svelte/icons/bar-chart-2";
	import Loader2 from "lucide-svelte/icons/loader-2";

	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import { portfolioDisplayName } from "$lib/constants/blocks";
	import UniversePanel from "$lib/components/portfolio/UniversePanel.svelte";
	import PolicyPanel from "$lib/components/portfolio/PolicyPanel.svelte";
	import ModelListPanel from "$lib/components/portfolio/ModelListPanel.svelte";
	import PortfolioOverview from "$lib/components/portfolio/PortfolioOverview.svelte";
	import StressTestPanel from "$lib/components/portfolio/StressTestPanel.svelte";
	import AnalyticsRiskPanel from "$lib/components/portfolio/AnalyticsRiskPanel.svelte";
	import OverlapScannerPanel from "$lib/components/portfolio/OverlapScannerPanel.svelte";
	import RebalanceSimulationPanel from "$lib/components/portfolio/RebalanceSimulationPanel.svelte";
	import MainPortfolioChart from "$lib/components/portfolio/MainPortfolioChart.svelte";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import type { AttributionResult, StrategyDriftAlert, CorrelationRegimeResult } from "$lib/types/analytics";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	let portfolios = $derived((data.portfolios ?? []) as ModelPortfolio[]);

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	workspace.setGetToken(getToken);

	// Seed workspace with SSR analytics data (default "moderate" profile)
	$effect(() => {
		const ssrAttribution = data.attribution as AttributionResult | null;
		const ssrDrift = (data.driftAlerts ?? []) as StrategyDriftAlert[];
		const ssrCorrelation = data.correlationRegime as CorrelationRegimeResult | null;
		if (ssrAttribution && !workspace.attribution) workspace.attribution = ssrAttribution;
		if (ssrDrift.length > 0 && workspace.driftAlerts.length === 0) workspace.driftAlerts = ssrDrift;
		if (ssrCorrelation && !workspace.correlationRegime) workspace.correlationRegime = ssrCorrelation;
	});

	$effect(() => {
		if (workspace.universe.length === 0 && !workspace.isLoadingUniverse) {
			workspace.loadUniverse();
		}
	});

	function handleConstruct() {
		workspace.constructPortfolio();
	}

	function handleStressNav() {
		workspace.activeMainTab = "stress";
	}

	const sidebarTabs = [
		{ value: "models", label: "Models", icon: Folders },
		{ value: "universe", label: "Universe", icon: Globe },
		{ value: "policy", label: "Policy", icon: Settings2 },
	] as const;

	const mainTabs = [
		{ value: "overview", label: "Overview" },
		{ value: "analytics", label: "Analytics & Risk" },
		{ value: "stress", label: "Stress Testing" },
		{ value: "overlap", label: "Overlap" },
		{ value: "rebalance", label: "Rebalance" },
	] as const;

	let chartTitle = $derived(
		workspace.portfolio
			? portfolioDisplayName(workspace.portfolio.display_name)
			: "Select a portfolio"
	);
</script>

<svelte:head>
	<title>Portfolio — InvestIntell</title>
</svelte:head>

<div class="pw-root">

	<!-- Main grid: sidebar + workspace -->
	<div class="pw-grid">

		<!-- ── Left sidebar ── -->
		<div class="pw-sidebar">
			<div class="pw-sidebar-card">

				<!-- Sidebar header: title + action buttons -->
				<div class="pw-sidebar-header">
					<h1 class="pw-sidebar-title">Portfolio Builder</h1>
					<div class="pw-sidebar-actions">
						<Button
							size="sm"
							variant="outline"
							disabled={!workspace.portfolioId || workspace.isConstructing}
							onclick={handleConstruct}
							class="h-8 text-[12px]"
						>
							{#if workspace.isConstructing}
								<Loader2 class="mr-1 h-3.5 w-3.5 animate-spin" />
								Building...
							{:else}
								<Play class="mr-1 h-3.5 w-3.5" />
								Construct
							{/if}
						</Button>
						<Button
							size="sm"
							variant="outline"
							disabled={!workspace.portfolioId}
							onclick={handleStressNav}
							class="h-8 text-[12px]"
						>
							<BarChart2 class="mr-1 h-3.5 w-3.5" />
							Stress
						</Button>
					</div>
				</div>

				<!-- Sidebar pills (Screener-matched style) -->
				<div class="pw-pill-bar">
					{#each sidebarTabs as tab (tab.value)}
						{@const Icon = tab.icon}
						{@const active = workspace.activeSidebarTab === tab.value}
						<button
							type="button"
							class="pw-pill"
							class:pw-pill--active={active}
							onclick={() => workspace.activeSidebarTab = tab.value}
						>
							<Icon class="h-3 w-3" />
							{tab.label}
						</button>
					{/each}
				</div>

				<!-- Sidebar content -->
				<div class="pw-sidebar-content">
					{#if workspace.activeSidebarTab === "models"}
						<ModelListPanel {portfolios} />
					{:else if workspace.activeSidebarTab === "universe"}
						<UniversePanel />
					{:else}
						<PolicyPanel />
					{/if}
				</div>
			</div>
		</div>

		<!-- ── Right workspace ── -->
		<div class="pw-main">

			<!-- Top chart area (45%) -->
			<div class="pw-chart-card">
				<div class="pw-chart-header">
					<span class="pw-chart-title">{chartTitle}</span>
				</div>
				<div class="pw-chart-body">
					<MainPortfolioChart />
				</div>
			</div>

			<!-- Bottom detail area (55%) -->
			<div class="pw-detail-card">

				<!-- Main pills (Screener-matched style) -->
				<div class="pw-pill-bar pw-pill-bar--main">
					{#each mainTabs as tab (tab.value)}
						{@const active = workspace.activeMainTab === tab.value}
						<button
							type="button"
							class="pw-pill pw-pill--main"
							class:pw-pill--active={active}
							onclick={() => workspace.activeMainTab = tab.value}
						>
							{tab.label}
						</button>
					{/each}
				</div>

				<!-- Main content -->
				<div class="pw-detail-content">
					{#if workspace.activeMainTab === "overview"}
						<PortfolioOverview />
					{:else if workspace.activeMainTab === "analytics"}
						<AnalyticsRiskPanel />
					{:else if workspace.activeMainTab === "stress"}
						<StressTestPanel />
					{:else if workspace.activeMainTab === "overlap"}
						<OverlapScannerPanel />
					{:else}
						<RebalanceSimulationPanel />
					{/if}
				</div>
			</div>
		</div>
	</div>

	<!-- Error notification -->
	{#if workspace.lastError}
		<div class="pw-error-toast">
			<span class="pw-error-text">
				<strong class="pw-error-label">
					{({ construct: "Construction", rebalance: "Rebalance Preview", universe: "Universe Loading", stress: "Stress Test" })[workspace.lastError.action] ?? workspace.lastError.action} failed:
				</strong>
				{workspace.lastError.message}
			</span>
			<button
				class="pw-error-close"
				onclick={() => { workspace.lastError = null; }}
			>
				&times;
			</button>
		</div>
	{/if}
</div>

<style>
	/* ── Root layout ── */
	.pw-root {
		display: flex;
		flex-direction: column;
		height: calc(100vh - 88px);
		padding: 24px;
		min-height: 0;
	}

	.pw-grid {
		display: grid;
		flex: 1;
		grid-template-columns: 5fr 7fr;
		gap: 20px;
		overflow: hidden;
		min-height: 0;
	}

	/* ── Sidebar ── */
	.pw-sidebar {
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.pw-sidebar-card {
		display: flex;
		flex: 1;
		flex-direction: column;
		overflow: hidden;
		background: #141519;
		border-radius: 24px;
		border: 1px solid rgba(64, 66, 73, 0.3);
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
	}

	.pw-sidebar-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 20px 20px 8px;
		flex-shrink: 0;
	}

	.pw-sidebar-title {
		font-size: 18px;
		font-weight: 600;
		color: #fff;
		letter-spacing: -0.01em;
	}

	.pw-sidebar-actions {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.pw-sidebar-content {
		flex: 1;
		overflow-y: auto;
		min-height: 0;
	}

	/* ── Main workspace ── */
	.pw-main {
		display: flex;
		flex-direction: column;
		gap: 20px;
		overflow: hidden;
	}

	/* ── Chart card ── */
	.pw-chart-card {
		display: flex;
		flex-shrink: 0;
		flex-direction: column;
		background: #141519;
		border-radius: 24px;
		border: 1px solid rgba(64, 66, 73, 0.3);
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
		overflow: hidden;
		height: 45%;
	}

	.pw-chart-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 24px;
	}

	.pw-chart-title {
		font-size: 15px;
		font-weight: 500;
		color: #cbccd1;
	}

	.pw-chart-body {
		display: flex;
		flex: 1;
		flex-direction: column;
		padding: 0 12px 12px;
		min-height: 0;
	}

	/* ── Detail card ── */
	.pw-detail-card {
		display: flex;
		flex: 1;
		flex-direction: column;
		min-height: 0;
		background: #141519;
		border-radius: 24px;
		border: 1px solid rgba(64, 66, 73, 0.3);
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
		overflow: hidden;
	}

	.pw-detail-content {
		flex: 1;
		overflow-y: auto;
		min-height: 0;
	}

	/* ══════════════════════════════════════════════════════════════════
	   Pill Navigation — matches Screener pattern (Urbanist, 36px radius)
	   ══════════════════════════════════════════════════════════════════ */

	.pw-pill-bar {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 0 20px 12px;
		flex-shrink: 0;
	}

	.pw-pill-bar--main {
		padding: 16px 24px 0;
		gap: 8px;
	}

	.pw-pill {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 6px;
		padding: 8px 16px;
		border: 1px solid #3a3b44;
		border-radius: 36px;
		background: transparent;
		color: #a1a1aa;
		font-size: 12px;
		font-weight: 600;
		font-family: "Urbanist", sans-serif;
		cursor: pointer;
		white-space: nowrap;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
		letter-spacing: 0.02em;
	}

	.pw-pill:hover {
		background: #22232a;
		border-color: #52525b;
		color: #fff;
	}

	.pw-pill--active {
		background: #0177fb;
		border-color: transparent;
		color: #fff;
	}

	.pw-pill--active:hover {
		background: #0166d9;
	}

	/* Main pills are slightly larger */
	.pw-pill--main {
		padding: 10px 20px;
		font-size: 13px;
	}

	/* ── Error toast ── */
	.pw-error-toast {
		position: fixed;
		bottom: 24px;
		right: 24px;
		z-index: 50;
		display: flex;
		max-width: 384px;
		align-items: flex-start;
		gap: 12px;
		border-radius: 16px;
		border: 1px solid rgba(239, 68, 68, 0.3);
		background: rgba(69, 10, 10, 0.9);
		padding: 12px 16px;
		font-size: 14px;
		color: #fecaca;
		box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
		backdrop-filter: blur(8px);
	}

	.pw-error-text {
		flex: 1;
	}

	.pw-error-label {
		color: #fee2e2;
	}

	.pw-error-close {
		flex-shrink: 0;
		color: #f87171;
		background: none;
		border: none;
		cursor: pointer;
		font-size: 18px;
	}

	.pw-error-close:hover {
		color: #fecaca;
	}
</style>
