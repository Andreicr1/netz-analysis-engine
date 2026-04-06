<!--
  Model — Active portfolio analysis and monitoring.
  Top: portfolio allocation chart (full-width).
  Sub-pills: Holdings | Stress Testing | Overlap | Rebalance
  Below: full-width panel content with strategic block table, stress, overlap, rebalance.
-->
<script lang="ts">
	import { EmptyState } from "@investintell/ui";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import { portfolioDisplayName } from "$lib/constants/blocks";
	import MainPortfolioChart from "$lib/components/portfolio/MainPortfolioChart.svelte";
	import PortfolioOverview from "$lib/components/portfolio/PortfolioOverview.svelte";
	import StressTestPanel from "$lib/components/portfolio/StressTestPanel.svelte";
	import OverlapScannerPanel from "$lib/components/portfolio/OverlapScannerPanel.svelte";
	import RebalanceSimulationPanel from "$lib/components/portfolio/RebalanceSimulationPanel.svelte";
	import FactorAnalysisPanel from "$lib/components/portfolio/FactorAnalysisPanel.svelte";

	const subTabs = [
		{ value: "overview", label: "Holdings" },
		{ value: "factor", label: "Factor Analysis" },
		{ value: "stress", label: "Stress Testing" },
		{ value: "overlap", label: "Overlap" },
		{ value: "rebalance", label: "Rebalance" },
	] as const;

	let chartTitle = $derived(
		workspace.portfolio
			? portfolioDisplayName(workspace.portfolio.display_name)
			: "No portfolio selected"
	);
</script>

<svelte:head>
	<title>Model — InvestIntell</title>
</svelte:head>

{#if !workspace.portfolio}
	<div class="mdl-empty">
		<EmptyState
			title="No portfolio selected"
			message="Go to Builder and select a model portfolio to view its detail."
		/>
	</div>
{:else}
	<div class="mdl-page">

		<!-- Chart card (full-width) -->
		<div class="mdl-chart-card">
			<div class="mdl-chart-header">
				<span class="mdl-chart-title">{chartTitle}</span>
			</div>
			<div class="mdl-chart-body">
				<MainPortfolioChart />
			</div>
		</div>

		<!-- Sub-pill bar -->
		<div class="mdl-sub-pills">
			{#each subTabs as tab (tab.value)}
				{@const active = workspace.activeModelTab === tab.value}
				<button
					type="button"
					class="mdl-sub-pill"
					class:mdl-sub-pill--active={active}
					onclick={() => workspace.activeModelTab = tab.value}
				>
					{tab.label}
				</button>
			{/each}
		</div>

		<!-- Panel content -->
		<div class="mdl-content">
			{#if workspace.activeModelTab === "overview"}
				<PortfolioOverview />
			{:else if workspace.activeModelTab === "factor"}
				<FactorAnalysisPanel />
			{:else if workspace.activeModelTab === "stress"}
				<StressTestPanel />
			{:else if workspace.activeModelTab === "overlap"}
				<OverlapScannerPanel />
			{:else}
				<RebalanceSimulationPanel />
			{/if}
		</div>
	</div>
{/if}

<!-- Error notification -->
{#if workspace.lastError}
	<div class="mdl-error-toast">
		<span>
			<strong>{workspace.lastError.action} failed:</strong>
			{workspace.lastError.message}
		</span>
		<button class="mdl-error-close" onclick={() => { workspace.lastError = null; }}>&times;</button>
	</div>
{/if}

<style>
	.mdl-page {
		height: 100%;
		display: flex;
		flex-direction: column;
		gap: 20px;
		overflow: hidden;
	}

	.mdl-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
	}

	/* ── Chart card ── */
	.mdl-chart-card {
		flex-shrink: 0;
		height: 260px;
		background: #141519;
		border-radius: 20px;
		border: 1px solid rgba(64, 66, 73, 0.3);
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.mdl-chart-header {
		display: flex;
		align-items: center;
		padding: 12px 20px;
		flex-shrink: 0;
	}

	.mdl-chart-title {
		font-size: 15px;
		font-weight: 600;
		color: #cbccd1;
		font-family: "Urbanist", sans-serif;
	}

	.mdl-chart-body {
		flex: 1;
		min-height: 0;
		padding: 0 12px 12px;
	}

	/* ── Sub-pills ── */
	.mdl-sub-pills {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
	}

	.mdl-sub-pill {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 8px 20px;
		border: 1px solid #3a3b44;
		border-radius: 36px;
		background: transparent;
		color: #a1a1aa;
		font-size: 14px;
		font-weight: 600;
		font-family: "Urbanist", sans-serif;
		cursor: pointer;
		white-space: nowrap;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
		letter-spacing: 0.02em;
	}

	.mdl-sub-pill:hover {
		background: #22232a;
		border-color: #52525b;
		color: #fff;
	}

	.mdl-sub-pill--active {
		background: #0177fb;
		border-color: transparent;
		color: #fff;
	}

	.mdl-sub-pill--active:hover {
		background: #0166d9;
	}

	/* ── Content ── */
	.mdl-content {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	/* ── Error toast ── */
	.mdl-error-toast {
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

	.mdl-error-close {
		flex-shrink: 0;
		color: #f87171;
		background: none;
		border: none;
		cursor: pointer;
		font-size: 18px;
	}
	.mdl-error-close:hover { color: #fecaca; }
</style>
