<!--
  BuilderColumn — Column 3 of the 3-column Builder grid (Phase 11).

  Two tabs at the top:
    [Allocations]  — BuilderTable (3-level tree, drop target)
    [Policy Rules] — CalibrationPanel (63-input calibration model)

  Footer: PortfolioStateChip + BuilderActionBar (including Run Construct).
  The footer is always visible regardless of which tab is active.

  <svelte:boundary> with PanelErrorState for crash isolation.
-->
<script lang="ts">
	import { PanelErrorState } from "@investintell/ui/runtime";
	import { formatPercent } from "@investintell/ui";
	import BuilderTable from "$lib/components/portfolio/BuilderTable.svelte";
	import BuilderActionBar from "$lib/components/portfolio/BuilderActionBar.svelte";
	import CalibrationPanel from "$lib/components/portfolio/CalibrationPanel.svelte";
	import AllocationBandChart from "$lib/components/portfolio/charts/AllocationBandChart.svelte";
	import TaaTransitionSparkline from "$lib/components/portfolio/charts/TaaTransitionSparkline.svelte";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import { portfolioDisplayName } from "$lib/constants/blocks";
	import { taaRegimeLabel } from "$lib/types/taa";

	type BuilderTab = "allocations" | "market" | "policy";
	let builderTab = $state<BuilderTab>("allocations");

	// ── TAA state (Sprint 4) ─────────────────────────────────────
	const regimeBands = $derived(workspace.regimeBands);
	const taaHistory = $derived(workspace.taaHistory);
	const effectiveWithRegime = $derived(workspace.effectiveWithRegime);
	const hasTaaData = $derived(regimeBands !== null);
	const regimeBadgeLabel = $derived(regimeBands ? taaRegimeLabel(regimeBands.raw_regime) : null);

	function handleConstruct() {
		workspace.openAnalyticsForPortfolio();
		void workspace.runConstructJob();
	}

	const chartTitle = $derived(
		workspace.portfolio
			? portfolioDisplayName(workspace.portfolio.display_name)
			: "Select a portfolio",
	);

	const totalWeight = $derived(
		workspace.funds.reduce((s, f) => s + (f.weight ?? 0), 0),
	);

	const fundCount = $derived(workspace.funds.length);
</script>

<svelte:boundary>
	<div class="bc-root">
		<!-- Header: title + count + tabs -->
		<header class="bc-header">
			<div class="bc-title-row">
				<div class="bc-title-block">
					<span class="bc-kicker">PORTFOLIO</span>
					<span class="bc-title">{chartTitle}</span>
				</div>
				<span class="bc-count">
					{fundCount} fund{fundCount === 1 ? "" : "s"} · {formatPercent(totalWeight, 2)}
				</span>
			</div>

			<!-- Tab pills -->
			<div class="bc-tabs">
				<button
					type="button"
					class="bc-tab"
					class:bc-tab--active={builderTab === "allocations"}
					onclick={() => (builderTab = "allocations")}
				>
					Allocations
				</button>
				<button
					type="button"
					class="bc-tab"
					class:bc-tab--active={builderTab === "market"}
					onclick={() => (builderTab = "market")}
				>
					Market
					{#if regimeBadgeLabel}
						<span class="bc-tab-badge">{regimeBadgeLabel}</span>
					{/if}
				</button>
				<button
					type="button"
					class="bc-tab"
					class:bc-tab--active={builderTab === "policy"}
					onclick={() => (builderTab = "policy")}
				>
					Policy Rules
				</button>
			</div>
		</header>

		<!-- Tab content -->
		<div class="bc-body">
			{#if builderTab === "allocations"}
				<BuilderTable />
			{:else if builderTab === "market"}
				<div class="bc-market-wrap">
					<section class="bc-market-section">
						<h3 class="bc-market-heading">Allocation Bands</h3>
						<p class="bc-market-desc">
							Optimizer operates within the colored bands. Grey bars show the policy limits.
						</p>
						<AllocationBandChart
							allocations={effectiveWithRegime}
							rawRegime={regimeBands?.raw_regime}
							loading={workspace.isLoadingEffectiveWithRegime}
							height={260}
						/>
					</section>

					<section class="bc-market-section">
						<h3 class="bc-market-heading">Band Transitions</h3>
						<p class="bc-market-desc">
							How allocation centers have evolved over the last 60 days as conditions changed.
						</p>
						<TaaTransitionSparkline
							history={taaHistory}
							loading={workspace.isLoadingTaaHistory}
							height={180}
						/>
					</section>
				</div>
			{:else}
				<div class="bc-policy-wrap">
					<CalibrationPanel />
				</div>
			{/if}
		</div>

		<!-- Footer: action bar (always visible) -->
		<footer class="bc-footer">
			<BuilderActionBar onConstruct={handleConstruct} />
		</footer>
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
		background: #141519;
		overflow: hidden;
	}

	/* ── Header ──────────────────────────────────────────────── */
	.bc-header {
		flex-shrink: 0;
		padding: 16px 16px 0;
		background: #141519;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.bc-title-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
	}

	.bc-title-block {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.bc-kicker {
		font-size: 0.6875rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: #85a0bd;
		font-family: "Urbanist", sans-serif;
	}

	.bc-title {
		font-size: 0.9375rem;
		font-weight: 700;
		color: #ffffff;
		font-family: "Urbanist", sans-serif;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.bc-count {
		font-size: 0.6875rem;
		font-weight: 700;
		color: #ffffff;
		background: rgba(255, 255, 255, 0.05);
		padding: 2px 10px;
		border-radius: 999px;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}

	/* ── Tab pills ───────────────────────────────────────────── */
	.bc-tabs {
		display: flex;
		align-items: center;
		gap: 4px;
		padding-bottom: 12px;
		border-bottom: 1px solid rgba(64, 66, 73, 0.4);
	}

	.bc-tab {
		display: inline-flex;
		align-items: center;
		padding: 6px 16px;
		border: 1px solid transparent;
		border-radius: 999px;
		background: transparent;
		color: #85a0bd;
		font-family: "Urbanist", sans-serif;
		font-size: 0.8125rem;
		font-weight: 500;
		cursor: pointer;
		transition: all 120ms ease;
	}
	.bc-tab:hover {
		color: #ffffff;
		background: rgba(255, 255, 255, 0.03);
	}
	.bc-tab--active {
		background: #0177fb;
		color: #ffffff;
		font-weight: 600;
	}
	.bc-tab--active:hover {
		background: #0177fb;
	}

	.bc-tab-badge {
		display: inline-flex;
		align-items: center;
		margin-left: 6px;
		padding: 1px 7px;
		border-radius: 999px;
		font-size: 0.625rem;
		font-weight: 700;
		background: rgba(255, 255, 255, 0.08);
		color: inherit;
		letter-spacing: 0.02em;
	}
	.bc-tab--active .bc-tab-badge {
		background: rgba(255, 255, 255, 0.2);
	}

	/* ── Body — tab content fills remaining vertical space ──── */
	.bc-body {
		flex: 1;
		min-height: 0;
		overflow: hidden;
	}

	.bc-policy-wrap {
		height: 100%;
		overflow-y: auto;
	}

	/* ── Market tab content (TAA Sprint 4) ─────────────────────── */
	.bc-market-wrap {
		height: 100%;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 16px;
	}
	.bc-market-section {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.bc-market-heading {
		margin: 0;
		font-size: 0.75rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ii-text-muted, #85a0bd);
		font-family: "Urbanist", sans-serif;
	}
	.bc-market-desc {
		margin: 0;
		font-size: 0.6875rem;
		line-height: 1.4;
		color: var(--ii-text-muted, #85a0bd);
		opacity: 0.7;
	}

	/* ── Footer — action bar, always visible ─────────────────── */
	.bc-footer {
		flex-shrink: 0;
		padding: 12px 16px;
		border-top: 1px solid rgba(64, 66, 73, 0.4);
		background: #141519;
		display: flex;
		align-items: center;
		gap: 8px;
	}
</style>
