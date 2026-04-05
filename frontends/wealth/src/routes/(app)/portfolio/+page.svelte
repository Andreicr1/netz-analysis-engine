<!--
  Portfolio Builder — Unified workspace (App-in-App).
  Left sidebar: Models / Universe / Policy tabs.
  Right main: Chart + tabbed detail (Overview, Analytics, Stress, Holdings).
-->
<script lang="ts">
	import { PageHeader } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import { Card } from "@investintell/ui/components/ui/card";
	import * as Tabs from "@investintell/ui/components/ui/tabs";
	import Settings2 from "lucide-svelte/icons/settings-2";
	import Globe from "lucide-svelte/icons/globe";
	import Folders from "lucide-svelte/icons/folders";
	import Play from "lucide-svelte/icons/play";
	import BarChart2 from "lucide-svelte/icons/bar-chart-2";

	import { workspace } from "$lib/states/portfolio-workspace.svelte";
	import UniversePanel from "$lib/components/portfolio/UniversePanel.svelte";
	import PolicyPanel from "$lib/components/portfolio/PolicyPanel.svelte";
	import ModelListPanel from "$lib/components/portfolio/ModelListPanel.svelte";
	import PortfolioOverview from "$lib/components/portfolio/PortfolioOverview.svelte";
	import StressTestPanel from "$lib/components/portfolio/StressTestPanel.svelte";
</script>

<div class="flex flex-col" style="height: calc(100vh - 88px); padding: 24px;">
	<PageHeader title="Portfolio Builder">
		{#snippet actions()}
			<Button size="sm" variant="outline" disabled={!workspace.portfolioId}>
				<Play class="mr-1.5 h-4 w-4" />
				Construct
			</Button>
			<Button size="sm" variant="outline" disabled={!workspace.portfolioId}>
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
				<Tabs.Root bind:value={workspace.activeSidebarTab} class="flex flex-1 flex-col overflow-hidden">
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
						<ModelListPanel />
					</Tabs.Content>
					<Tabs.Content value="universe" class="flex-1 overflow-y-auto">
						<UniversePanel />
					</Tabs.Content>
					<Tabs.Content value="policy" class="flex-1 overflow-y-auto">
						<PolicyPanel />
					</Tabs.Content>
				</Tabs.Root>
			</Card>
		</div>

		<!-- Right workspace -->
		<div class="col-span-8 flex flex-col gap-4 overflow-hidden xl:col-span-9">
			<!-- Top chart area (45%) -->
			<Card class="flex shrink-0 flex-col" style="height: 45%;">
				<div class="flex items-center justify-between border-b px-4 py-2">
					<span class="text-sm font-medium text-muted-foreground">
						{workspace.portfolio?.name ?? "Select a portfolio"}
					</span>
				</div>
				<div class="flex-1 p-4">
					<div class="flex h-full items-center justify-center text-muted-foreground">
						Backtest chart placeholder
					</div>
				</div>
			</Card>

			<!-- Bottom detail tabs (55%) -->
			<Card class="flex flex-1 flex-col overflow-hidden">
				<Tabs.Root bind:value={workspace.activeMainTab} class="flex flex-1 flex-col overflow-hidden">
					<Tabs.List class="w-full shrink-0">
						<Tabs.Trigger value="overview" class="flex-1">Fund Selection</Tabs.Trigger>
						<Tabs.Trigger value="analytics" class="flex-1">Factor Analysis</Tabs.Trigger>
						<Tabs.Trigger value="stress" class="flex-1">Stress Testing</Tabs.Trigger>
						<Tabs.Trigger value="holdings" class="flex-1">Overlap Scanner</Tabs.Trigger>
					</Tabs.List>

					<Tabs.Content value="overview" class="flex-1 overflow-y-auto">
						<PortfolioOverview />
					</Tabs.Content>
					<Tabs.Content value="analytics" class="flex-1 overflow-y-auto p-4">
						<div class="text-muted-foreground">Factor Analysis — Placeholder</div>
					</Tabs.Content>
					<Tabs.Content value="stress" class="flex-1 overflow-y-auto">
						<StressTestPanel />
					</Tabs.Content>
					<Tabs.Content value="holdings" class="flex-1 overflow-y-auto p-4">
						<div class="text-muted-foreground">Overlap Scanner — Placeholder</div>
					</Tabs.Content>
				</Tabs.Root>
			</Card>
		</div>
	</div>
</div>
