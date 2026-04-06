<!--
  Builder — Integrated portfolio construction workspace.
  Left sidebar: Models | Universe | Policy pills + panel content.
  Right workspace: Chart (top) + Strategic Blocks with DnD (bottom).
  All components visible together so the manager can drag-and-drop from
  the approved universe into allocation blocks while seeing the chart update.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { Button } from "@investintell/ui/components/ui/button";
	import Settings2 from "lucide-svelte/icons/settings-2";
	import Globe from "lucide-svelte/icons/globe";
	import Folders from "lucide-svelte/icons/folders";
	import Play from "lucide-svelte/icons/play";
	import Plus from "lucide-svelte/icons/plus";
	import BarChart2 from "lucide-svelte/icons/bar-chart-2";
	import Loader2 from "lucide-svelte/icons/loader-2";
	import { goto } from "$app/navigation";

	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import { portfolioDisplayName } from "$lib/constants/blocks";
	import UniversePanel from "$lib/components/portfolio/UniversePanel.svelte";
	import PolicyPanel from "$lib/components/portfolio/PolicyPanel.svelte";
	import ModelListPanel from "$lib/components/portfolio/ModelListPanel.svelte";
	import PortfolioOverview from "$lib/components/portfolio/PortfolioOverview.svelte";
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
		workspace.activeModelTab = "stress";
		goto("/portfolio/model");
	}

	const sidebarTabs = [
		{ value: "models", label: "Models", icon: Folders },
		{ value: "universe", label: "Universe", icon: Globe },
		{ value: "policy", label: "Policy", icon: Settings2 },
	] as const;

	let chartTitle = $derived(
		workspace.portfolio
			? portfolioDisplayName(workspace.portfolio.display_name)
			: "Select a portfolio"
	);
</script>

<svelte:head>
	<title>Portfolio Builder — InvestIntell</title>
</svelte:head>

<div class="bld-root">
	<div class="bld-grid">

		<!-- ── Left sidebar ── -->
		<div class="bld-sidebar">

			<!-- Sidebar header: title + New Portfolio button -->
			<div class="bld-sidebar-header">
				<h2 class="bld-sidebar-title">Portfolio Builder</h2>
				<Button size="sm" variant="outline" class="h-8 text-[12px]">
					<Plus class="mr-1 h-3.5 w-3.5" />
					New
				</Button>
			</div>

			<!-- Sidebar sub-pills -->
			<div class="bld-sub-pills">
				{#each sidebarTabs as tab (tab.value)}
					{@const Icon = tab.icon}
					{@const active = workspace.activeBuilderTab === tab.value}
					<button
						type="button"
						class="bld-sub-pill"
						class:bld-sub-pill--active={active}
						onclick={() => workspace.activeBuilderTab = tab.value}
					>
						<Icon class="h-3 w-3" />
						{tab.label}
					</button>
				{/each}
			</div>

			<!-- Sidebar content -->
			<div class="bld-sidebar-content">
				{#if workspace.activeBuilderTab === "models"}
					<ModelListPanel {portfolios} />
				{:else if workspace.activeBuilderTab === "universe"}
					<UniversePanel />
				{:else}
					<PolicyPanel />
				{/if}
			</div>
		</div>

		<!-- ── Right workspace ── -->
		<div class="bld-main">

			<!-- Action bar -->
			<div class="bld-actions">
				<Button
					size="sm"
					variant="outline"
					disabled={!workspace.portfolioId || workspace.isConstructing}
					onclick={handleConstruct}
					class="h-9 text-[13px]"
				>
					{#if workspace.isConstructing}
						<Loader2 class="mr-1.5 h-4 w-4 animate-spin" />
						Building...
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
					class="h-9 text-[13px]"
				>
					<BarChart2 class="mr-1.5 h-4 w-4" />
					Stress Test
				</Button>
			</div>

			<!-- Top chart area -->
			<div class="bld-chart-card">
				<div class="bld-chart-header">
					<span class="bld-chart-title">{chartTitle}</span>
				</div>
				<div class="bld-chart-body">
					<MainPortfolioChart />
				</div>
			</div>

			<!-- Strategic blocks (fund selection with DnD) -->
			<div class="bld-blocks">
				<PortfolioOverview />
			</div>
		</div>
	</div>

	<!-- Error notification -->
	{#if workspace.lastError}
		<div class="bld-error-toast">
			<span>
				<strong>{workspace.lastError.action} failed:</strong>
				{workspace.lastError.message}
			</span>
			<button class="bld-error-close" onclick={() => { workspace.lastError = null; }}>&times;</button>
		</div>
	{/if}
</div>

<style>
	.bld-root {
		height: 100%;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.bld-grid {
		display: grid;
		flex: 1;
		grid-template-columns: 380px 1fr;
		gap: 20px;
		overflow: hidden;
		min-height: 0;
	}

	/* ── Sidebar ── */
	.bld-sidebar {
		display: flex;
		flex-direction: column;
		overflow: hidden;
		background: #141519;
		border-radius: 20px;
		border: 1px solid rgba(64, 66, 73, 0.3);
	}

	.bld-sidebar-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 20px 8px;
		flex-shrink: 0;
	}

	.bld-sidebar-title {
		font-size: 16px;
		font-weight: 700;
		color: #fff;
		font-family: "Urbanist", sans-serif;
		margin: 0;
	}

	.bld-sidebar-content {
		flex: 1;
		overflow-y: auto;
		min-height: 0;
	}

	/* ── Sidebar sub-pills ── */
	.bld-sub-pills {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 0 20px 12px;
		flex-shrink: 0;
	}

	.bld-sub-pill {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 6px;
		padding: 7px 16px;
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

	.bld-sub-pill:hover {
		background: #22232a;
		border-color: #52525b;
		color: #fff;
	}

	.bld-sub-pill--active {
		background: #0177fb;
		border-color: transparent;
		color: #fff;
	}

	.bld-sub-pill--active:hover {
		background: #0166d9;
	}

	/* ── Main workspace ── */
	.bld-main {
		display: flex;
		flex-direction: column;
		gap: 16px;
		overflow: hidden;
		min-height: 0;
	}

	/* ── Action bar ── */
	.bld-actions {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-shrink: 0;
	}

	/* ── Chart card ── */
	.bld-chart-card {
		flex-shrink: 0;
		height: 240px;
		background: #141519;
		border-radius: 20px;
		border: 1px solid rgba(64, 66, 73, 0.3);
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.bld-chart-header {
		display: flex;
		align-items: center;
		padding: 12px 20px;
		flex-shrink: 0;
	}

	.bld-chart-title {
		font-size: 15px;
		font-weight: 500;
		color: #cbccd1;
		font-family: "Urbanist", sans-serif;
	}

	.bld-chart-body {
		flex: 1;
		min-height: 0;
		padding: 0 12px 12px;
	}

	/* ── Strategic blocks (fund selection + DnD) ── */
	.bld-blocks {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	/* ── Error toast ── */
	.bld-error-toast {
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

	.bld-error-close {
		flex-shrink: 0;
		color: #f87171;
		background: none;
		border: none;
		cursor: pointer;
		font-size: 18px;
	}

	.bld-error-close:hover { color: #fecaca; }
</style>
