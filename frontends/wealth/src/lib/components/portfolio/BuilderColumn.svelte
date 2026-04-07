<!--
  BuilderColumn — Central column of the Portfolio Builder Flexible
  Columns Layout. Owns the action bar, the main chart, and the
  strategic allocation blocks with drop targets.

  Reference: docs/superpowers/specs/2026-04-08-portfolio-builder-flexible-columns.md §1.2

  This is the thin v1 wrapper: the existing MainPortfolioChart +
  PortfolioOverview components are reused as-is. A follow-up commit
  (§4.2 commit 07) will expand the allocation blocks into 120px+
  cards with summary bar and weighted metrics. For now we migrate
  the existing visual into the new column wrapper so Phase B can
  ship Estado B end-to-end.

  <svelte:boundary> with a PanelErrorState failed snippet is
  mandatory per §3.2 of the design spec: a crash in MainPortfolioChart
  must not drag down the Universe column.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { Button } from "@investintell/ui/components/ui/button";
	import { PanelErrorState } from "@investintell/ui/runtime";
	import Play from "lucide-svelte/icons/play";
	import BarChart2 from "lucide-svelte/icons/bar-chart-2";
	import Loader2 from "lucide-svelte/icons/loader-2";
	import MainPortfolioChart from "$lib/components/portfolio/MainPortfolioChart.svelte";
	import PortfolioOverview from "$lib/components/portfolio/PortfolioOverview.svelte";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import { portfolioDisplayName } from "$lib/constants/blocks";

	function handleConstruct() {
		workspace.constructPortfolio();
	}

	function handleStressNav() {
		workspace.activeModelTab = "stress";
		goto("/portfolio/model");
	}

	const chartTitle = $derived(
		workspace.portfolio
			? portfolioDisplayName(workspace.portfolio.display_name)
			: "Select a portfolio",
	);
</script>

<svelte:boundary>
	<div class="bc-root">
		<!-- Action bar -->
		<div class="bc-actions">
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

		<!-- Main chart -->
		<div class="bc-chart-card">
			<div class="bc-chart-header">
				<span class="bc-chart-title">{chartTitle}</span>
			</div>
			<div class="bc-chart-body">
				<MainPortfolioChart />
			</div>
		</div>

		<!-- Strategic allocation blocks with DnD drop targets -->
		<div class="bc-blocks">
			<PortfolioOverview />
		</div>
	</div>

	{#snippet failed(error: unknown, reset: () => void)}
		<PanelErrorState
			title="Portfolio builder failed to render"
			message={error instanceof Error ? error.message : "Unexpected error in the builder."}
			onRetry={reset}
		/>
	{/snippet}
</svelte:boundary>

<style>
	.bc-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		gap: 16px;
		padding: 16px;
		overflow-y: auto;
	}

	.bc-actions {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-shrink: 0;
	}

	.bc-chart-card {
		display: flex;
		flex-direction: column;
		background: var(--ii-surface, #141519);
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		border-radius: 12px;
		overflow: hidden;
		flex-shrink: 0;
		min-height: 260px;
	}

	.bc-chart-header {
		padding: 10px 16px;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.3));
	}

	.bc-chart-title {
		font-size: 0.8125rem;
		font-weight: 600;
		color: var(--ii-text-primary, white);
	}

	.bc-chart-body {
		flex: 1;
		min-height: 220px;
		padding: 8px;
	}

	.bc-blocks {
		flex: 1;
		min-height: 0;
	}
</style>
