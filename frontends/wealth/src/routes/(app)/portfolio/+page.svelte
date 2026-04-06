<!--
  Portfolio Workspace — Unified App-in-App.
  Left sidebar: Title + Models / Universe / Policy pills.
  Right main: Chart + pill-tabbed detail panels.
  Design system: Figma One X — dark premium, glassmorphism, pill navigation.
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
	import FactorAnalysisPanel from "$lib/components/portfolio/FactorAnalysisPanel.svelte";
	import OverlapScannerPanel from "$lib/components/portfolio/OverlapScannerPanel.svelte";
	import RebalanceSimulationPanel from "$lib/components/portfolio/RebalanceSimulationPanel.svelte";
	import MainPortfolioChart from "$lib/components/portfolio/MainPortfolioChart.svelte";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	let portfolios = $derived((data.portfolios ?? []) as ModelPortfolio[]);

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	workspace.setGetToken(getToken);

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
		{ value: "overview", label: "Fund Selection" },
		{ value: "analytics", label: "Factor Analysis" },
		{ value: "stress", label: "Stress Testing" },
		{ value: "holdings", label: "Overlap Scanner" },
		{ value: "rebalance", label: "Rebalance Sim" },
	] as const;

	let chartTitle = $derived(
		workspace.portfolio
			? portfolioDisplayName(workspace.portfolio.display_name)
			: "Select a portfolio"
	);
</script>

<div class="flex flex-col" style="height: calc(100vh - 88px); padding: 24px; min-height: 0;">

	<!-- Main grid: sidebar + workspace (no top-level PageHeader) -->
	<div class="grid flex-1 grid-cols-12 gap-5 overflow-hidden min-h-0">

		<!-- ── Left sidebar (widened for Universe table) ── -->
		<div class="col-span-5 flex flex-col overflow-hidden">
			<div class="flex flex-1 flex-col overflow-hidden bg-[#141519] rounded-[24px] border border-[#404249]/30 shadow-xl">

				<!-- Sidebar header: title + action buttons -->
				<div class="flex items-center justify-between px-5 pt-5 pb-2 shrink-0">
					<h1 class="text-[18px] font-semibold text-white tracking-[-0.01em]">Portfolio Builder</h1>
					<div class="flex items-center gap-1.5">
						<Button
							size="sm"
							variant="outline"
							disabled={!workspace.portfolioId || workspace.isConstructing}
							onclick={handleConstruct}
							class="h-8 text-[12px]"
						>
							{#if workspace.isConstructing}
								<Loader2 class="mr-1 h-3.5 w-3.5 animate-spin" />
								Building…
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

				<!-- Sidebar pills -->
				<div class="flex items-center gap-2 px-5 pb-3 shrink-0">
					{#each sidebarTabs as tab (tab.value)}
						{@const Icon = tab.icon}
						{@const active = workspace.activeSidebarTab === tab.value}
						<button
							type="button"
							class="flex items-center gap-1.5 text-[12px] transition-all duration-150
								{active
									? 'bg-[#0177fb] text-white font-semibold rounded-full px-4 py-1.5'
									: 'border border-white/10 text-[#cbccd1] rounded-full px-4 py-1.5 hover:bg-white/5'}"
							onclick={() => workspace.activeSidebarTab = tab.value}
						>
							<Icon class="h-3 w-3" />
							{tab.label}
						</button>
					{/each}
				</div>

				<!-- Sidebar content -->
				<div class="flex-1 overflow-y-auto min-h-0">
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
		<div class="col-span-7 flex flex-col gap-5 overflow-hidden">

			<!-- Top chart area (45%) -->
			<div class="flex shrink-0 flex-col bg-[#141519] rounded-[24px] border border-[#404249]/30 shadow-xl overflow-hidden" style="height: 45%;">
				<div class="flex items-center justify-between px-6 py-3">
					<span class="text-[15px] font-medium text-[#cbccd1]">
						{chartTitle}
					</span>
				</div>
				<div class="flex flex-1 flex-col px-3 pb-3" style="min-height: 0;">
					<MainPortfolioChart />
				</div>
			</div>

			<!-- Bottom detail area (55%) -->
			<div class="flex flex-1 flex-col min-h-0 bg-[#141519] rounded-[24px] border border-[#404249]/30 shadow-xl overflow-hidden">

				<!-- Main pills -->
				<div class="flex items-center gap-2 px-6 py-4 shrink-0 flex-wrap">
					{#each mainTabs as tab (tab.value)}
						{@const active = workspace.activeMainTab === tab.value}
						<button
							type="button"
							class="text-[13px] transition-all duration-150
								{active
									? 'bg-[#0177fb] text-white font-semibold rounded-full px-5 py-2'
									: 'border border-white/10 text-[#cbccd1] rounded-full px-5 py-2 hover:bg-white/5'}"
							onclick={() => workspace.activeMainTab = tab.value}
						>
							{tab.label}
						</button>
					{/each}
				</div>

				<!-- Main content -->
				<div class="flex-1 overflow-y-auto min-h-0">
					{#if workspace.activeMainTab === "overview"}
						<PortfolioOverview />
					{:else if workspace.activeMainTab === "analytics"}
						<FactorAnalysisPanel />
					{:else if workspace.activeMainTab === "stress"}
						<StressTestPanel />
					{:else if workspace.activeMainTab === "holdings"}
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
		<div class="fixed bottom-6 right-6 z-50 flex max-w-sm items-start gap-3 rounded-[16px] border border-red-500/30 bg-red-950/90 px-4 py-3 text-sm text-red-200 shadow-lg backdrop-blur-sm">
			<span class="flex-1">
				<strong class="text-red-100">{({ construct: "Construction", rebalance: "Rebalance Preview", universe: "Universe Loading", stress: "Stress Test" })[workspace.lastError.action] ?? workspace.lastError.action} failed:</strong>
				{workspace.lastError.message}
			</span>
			<button
				class="shrink-0 text-red-400 hover:text-red-200"
				onclick={() => { workspace.lastError = null; }}
			>
				&times;
			</button>
		</div>
	{/if}
</div>
