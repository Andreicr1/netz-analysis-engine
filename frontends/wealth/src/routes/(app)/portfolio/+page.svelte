<!--
  Portfolio Builder — Unified workspace (App-in-App).
  Left sidebar: Models / Universe / Policy tabs.
  Right main: Chart + tabbed detail (Overview, Analytics, Stress, Holdings).
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { PageHeader } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import { Card } from "@investintell/ui/components/ui/card";
	import * as Tabs from "@investintell/ui/components/ui/tabs";
	import Settings2 from "lucide-svelte/icons/settings-2";
	import Globe from "lucide-svelte/icons/globe";
	import Folders from "lucide-svelte/icons/folders";
	import Play from "lucide-svelte/icons/play";
	import BarChart2 from "lucide-svelte/icons/bar-chart-2";
	import Loader2 from "lucide-svelte/icons/loader-2";

	import { workspace } from "$lib/state/portfolio-workspace.svelte";
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

	// Inject auth token provider into workspace singleton
	const getToken = getContext<() => Promise<string>>("netz:getToken");
	workspace.setGetToken(getToken);

	// Load approved universe on mount (once token is available)
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
</script>

<div class="flex flex-col" style="height: calc(100vh - 88px); padding: 24px;">
	<PageHeader title="Portfolio Builder">
		{#snippet actions()}
			<Button
				size="sm"
				variant="outline"
				disabled={!workspace.portfolioId || workspace.isConstructing}
				onclick={handleConstruct}
			>
				{#if workspace.isConstructing}
					<Loader2 class="mr-1.5 h-4 w-4 animate-spin" />
					Constructing…
				{:else}
					<Play class="mr-1.5 h-4 w-4" />
					Construct
				{/if}
			</Button>
			<Button
				size="sm"
				variant="outline"
				disabled={!workspace.portfolioId}
				onclick={handleStressNav}
			>
				<BarChart2 class="mr-1.5 h-4 w-4" />
				Stress Test
			</Button>
		{/snippet}
	</PageHeader>

	<!-- Main grid: sidebar + workspace -->
	<div class="mt-4 grid flex-1 grid-cols-12 gap-4 overflow-hidden">
		<!-- Left sidebar -->
		<div class="col-span-4 flex flex-col overflow-hidden xl:col-span-3">
			<Card class="flex flex-1 flex-col overflow-hidden">
				<Tabs.Root
					bind:value={workspace.activeSidebarTab}
					class="flex flex-1 flex-col overflow-hidden"
				>
					<Tabs.List class="w-full shrink-0">
						<Tabs.Trigger value="models" class="flex-1 gap-1.5">
							<Folders class="h-4 w-4" />
							Models
						</Tabs.Trigger>
						<Tabs.Trigger value="universe" class="flex-1 gap-1.5">
							<Globe class="h-4 w-4" />
							Universe
						</Tabs.Trigger>
						<Tabs.Trigger value="policy" class="flex-1 gap-1.5">
							<Settings2 class="h-4 w-4" />
							Policy
						</Tabs.Trigger>
					</Tabs.List>

					<Tabs.Content value="models" class="flex-1 overflow-y-auto">
						<ModelListPanel {portfolios} />
					</Tabs.Content>
					<Tabs.Content
						value="universe"
						class="flex-1 overflow-y-auto"
					>
						<UniversePanel />
					</Tabs.Content>
					<Tabs.Content value="policy" class="flex-1 overflow-y-auto">
						<PolicyPanel />
					</Tabs.Content>
				</Tabs.Root>
			</Card>
		</div>

		<!-- Right workspace -->
		<div
			class="col-span-8 flex flex-col gap-4 overflow-hidden xl:col-span-9"
		>
			<!-- Top chart area (45%) -->
			<Card class="flex shrink-0 flex-col" style="height: 45%;">
				<div
					class="flex items-center justify-between border-b px-4 py-2"
				>
					<span class="text-sm font-medium text-muted-foreground">
						{workspace.portfolio?.display_name ??
							"Select a portfolio"}
					</span>
				</div>
				<div class="flex flex-1 flex-col p-2" style="min-height: 0;">
					<MainPortfolioChart />
				</div>
			</Card>

			<!-- Bottom detail tabs (55%) -->
			<Card class="flex flex-1 flex-col overflow-hidden">
				<Tabs.Root
					bind:value={workspace.activeMainTab}
					class="flex flex-1 flex-col overflow-hidden"
				>
					<Tabs.List class="w-full shrink-0">
						<Tabs.Trigger value="overview" class="flex-1"
							>Fund Selection</Tabs.Trigger
						>
						<Tabs.Trigger value="analytics" class="flex-1"
							>Factor Analysis</Tabs.Trigger
						>
						<Tabs.Trigger value="stress" class="flex-1"
							>Stress Testing</Tabs.Trigger
						>
						<Tabs.Trigger value="holdings" class="flex-1"
							>Overlap Scanner</Tabs.Trigger
						>
						<Tabs.Trigger value="rebalance" class="flex-1"
							>Rebalance Sim</Tabs.Trigger
						>
					</Tabs.List>

					<Tabs.Content
						value="overview"
						class="flex-1 overflow-y-auto"
					>
						<PortfolioOverview />
					</Tabs.Content>
					<Tabs.Content
						value="analytics"
						class="flex-1 overflow-y-auto"
					>
						<FactorAnalysisPanel />
					</Tabs.Content>
					<Tabs.Content value="stress" class="flex-1 overflow-y-auto">
						<StressTestPanel />
					</Tabs.Content>
					<Tabs.Content
						value="holdings"
						class="flex-1 overflow-y-auto"
					>
						<OverlapScannerPanel />
					</Tabs.Content>
					<Tabs.Content
						value="rebalance"
						class="flex-1 overflow-y-auto"
					>
						<RebalanceSimulationPanel />
					</Tabs.Content>
				</Tabs.Root>
			</Card>
		</div>
	</div>

	<!-- Error notification -->
	{#if workspace.lastError}
		<div class="fixed bottom-6 right-6 z-50 flex max-w-sm items-start gap-3 rounded-lg border border-red-500/30 bg-red-950/90 px-4 py-3 text-sm text-red-200 shadow-lg backdrop-blur-sm">
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
