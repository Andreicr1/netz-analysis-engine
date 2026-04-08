<!--
  BuilderColumn — Center column of the Portfolio Builder Flexible
  Columns Layout. Owns the action bar and the strategic allocation
  blocks with drop targets.

  Reference: docs/superpowers/specs/2026-04-08-portfolio-builder-flexible-columns.md §1.2

  Phase B polish (2026-04-08 visual validation feedback):
    - MainPortfolioChart moved to AnalyticsColumn (3rd column), opened
      by the `View Chart` button which flips `workspace.analyticsMode`
      to "portfolio". The Builder column is now chart-free and uses
      all vertical space for allocation blocks.
    - Rounded corners removed to match the flat density aesthetic
      of the Universe column (user feedback: "bordas arredondadas
      quebram a harmonização visual, além de não serem o componente
      ideal para o tipo de transição que queremos"). Global CSS
      overrides flatten the inner PortfolioOverview card borders too.
    - Dark-mode hex values hardcoded — no var() fallbacks.

  <svelte:boundary> with PanelErrorState failed snippet is mandatory
  per §3.2 of the design spec.
-->
<script lang="ts">
	import { PanelErrorState } from "@investintell/ui/runtime";
	import { formatPercent } from "@investintell/ui";
	import LineChart from "lucide-svelte/icons/line-chart";
	import BuilderTable from "$lib/components/portfolio/BuilderTable.svelte";
	import BuilderActionBar from "$lib/components/portfolio/BuilderActionBar.svelte";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import { portfolioDisplayName } from "$lib/constants/blocks";

	function handleConstruct() {
		// Phase 4 Task 4.5 — Run Construct is now a Job-or-Stream flow
		// (DL18 P2). Opening the 3rd column in "portfolio" mode makes
		// the BuilderRightStack visible so the PM sees the Narrative
		// tab advance through the runPhase SSE events and auto-switch
		// to the Narrative tab on "done".
		workspace.openAnalyticsForPortfolio();
		void workspace.runConstructJob();
	}

	function handleViewChart() {
		// Opens Estado C (3rd column) which hosts the BuilderRightStack
		// (Calibration | Narrative | Stress | Chart). The page handles
		// the tab selection — pressing "View Chart" is the spiritual
		// successor of the legacy behaviour so the Chart tab is the
		// reasonable landing spot.
		workspace.openAnalyticsForPortfolio();
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
		<!--
		  Header — mirrors UniverseColumn.uc-header geometry exactly:
		    Row 1: title block + count badge (status pill on the right)
		    Row 2: action pill group (parity with Universe search row)
		  Total height matches UniverseColumn so the table headers
		  below both start at the same Y pixel. This is the "Y-axis
		  lock" requested in the visual validation feedback.
		-->
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

			<div class="bc-actions">
				<!--
				  View Chart is a layout shortcut, not a state-machine
				  action — it just opens Estado C with the chart tab. It
				  stays as a static pill so the muscle memory survives.
				-->
				<button
					type="button"
					class="bc-pill"
					disabled={!workspace.portfolioId}
					onclick={handleViewChart}
				>
					<LineChart size={16} />
					<span>View Chart</span>
				</button>

				<!--
				  Phase 5 Task 5.2 — every state-machine button comes
				  from ``portfolio.allowed_actions`` (DL3). Construct is
				  the only action that does not POST to the transition
				  dispatcher; it has its own Job-or-Stream route which
				  the action bar fires via the ``onConstruct`` callback.
				-->
				<BuilderActionBar onConstruct={handleConstruct} />
			</div>
		</header>

		<!-- Continuous tree table — mirror of UniverseTable structure -->
		<div class="bc-body">
			<BuilderTable />
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
	/* ── Hardcoded dark palette ──────────────────────────────────
	 * Matches the legacy UniversePanel colours the user approved:
	 *   #141519  — column surface
	 *   #0e0f13  — workspace canvas
	 *   #404249  — border subtle
	 *   #85a0bd  — text muted (institutional blue-grey)
	 *   #cbccd1  — text secondary
	 *   #0177fb  — brand primary
	 * Zero var() fallbacks — forces dark rendering regardless of
	 * theme context.
	 */

	.bc-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		background: #141519;
		overflow: hidden;
	}

	/* ── Header — mirrors UniverseColumn.uc-header geometry ───────
	 * Two stacked rows (title row + action row) with 16px gap.
	 * Total header height matches the Universe column so the tables
	 * below both start at the same Y pixel. */
	.bc-header {
		flex-shrink: 0;
		padding: 16px;
		border-bottom: 1px solid rgba(64, 66, 73, 0.4);
		background: #141519;
		display: flex;
		flex-direction: column;
		gap: 16px;
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

	.bc-actions {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}

	/* ── Pills — Screener .scr-pill pattern (dark, white border, 36px) ── */
	.bc-pill {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 10px 18px;
		border: 1px solid #ffffff;
		border-radius: 36px;
		background: #000000;
		color: #ffffff;
		font-size: 13px;
		font-weight: 400;
		font-family: "Urbanist", sans-serif;
		cursor: pointer;
		white-space: nowrap;
		transition: background 120ms ease;
	}

	.bc-pill:hover:not(:disabled) {
		background: #1a1b20;
	}

	.bc-pill:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.bc-pill :global(.bc-pill-spinner) {
		animation: bc-spin 1s linear infinite;
	}

	@keyframes bc-spin {
		to { transform: rotate(360deg); }
	}

	/* ── Body — BuilderTable fills the remaining vertical ───── */
	.bc-body {
		flex: 1;
		min-height: 0;
		overflow: hidden;
	}
</style>
