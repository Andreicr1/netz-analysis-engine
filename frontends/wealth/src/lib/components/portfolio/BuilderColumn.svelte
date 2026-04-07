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
	import { goto } from "$app/navigation";
	import { Button } from "@investintell/ui/components/ui/button";
	import { PanelErrorState } from "@investintell/ui/runtime";
	import Play from "lucide-svelte/icons/play";
	import BarChart2 from "lucide-svelte/icons/bar-chart-2";
	import LineChart from "lucide-svelte/icons/line-chart";
	import Loader2 from "lucide-svelte/icons/loader-2";
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

	function handleViewChart() {
		// Opens Estado C (3rd column) with MainPortfolioChart loaded
		// in "portfolio" mode. The chart was previously pinned at the
		// top of this column — moved to the 3rd column in Phase B
		// polish so the allocation blocks get full vertical space.
		workspace.openAnalyticsForPortfolio();
	}

	const chartTitle = $derived(
		workspace.portfolio
			? portfolioDisplayName(workspace.portfolio.display_name)
			: "Select a portfolio",
	);
</script>

<svelte:boundary>
	<div class="bc-root">
		<!-- Header: portfolio name + action bar -->
		<header class="bc-header">
			<div class="bc-title-block">
				<span class="bc-kicker">Portfolio</span>
				<span class="bc-title">{chartTitle}</span>
			</div>

			<div class="bc-actions">
				<Button
					size="sm"
					variant="outline"
					disabled={!workspace.portfolioId}
					onclick={handleViewChart}
					class="h-9 text-[13px]"
				>
					<LineChart class="mr-1.5 h-4 w-4" />
					View Chart
				</Button>
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
		</header>

		<!-- Strategic allocation blocks fill the remaining vertical -->
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
		border-left: 1px solid rgba(64, 66, 73, 0.4);
		overflow: hidden;
	}

	.bc-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		padding: 14px 20px;
		border-bottom: 1px solid rgba(64, 66, 73, 0.4);
		flex-shrink: 0;
		background: #141519;
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
	}

	.bc-title {
		font-size: 0.9375rem;
		font-weight: 700;
		color: #ffffff;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.bc-actions {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-shrink: 0;
	}

	.bc-blocks {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 16px 20px 20px;
	}

	/* ── Global overrides: flatten PortfolioOverview internal cards
	 *
	 * The legacy PortfolioOverview uses rounded-[16px] and rounded-[12px]
	 * on its asset class groups and block rows. In the flat institutional
	 * aesthetic of the Flexible Columns Layout those curves clash with
	 * the Universe table's hard edges, and they do not transition well
	 * during the grid-template-columns animation of Estado C.
	 *
	 * Rather than modify the PortfolioOverview component directly
	 * (which is 348 lines and shared) we neutralise its rounded
	 * borders from here using :global(). This is a deliberate
	 * aesthetic override, not a component fork — documented in the
	 * design spec polish notes.
	 */
	.bc-blocks :global(.rounded-\[16px\]),
	.bc-blocks :global(.rounded-\[12px\]),
	.bc-blocks :global([class*="rounded-[16px]"]),
	.bc-blocks :global([class*="rounded-[12px]"]) {
		border-radius: 2px !important;
	}

	/* Keep the chip "pill" shape on smaller badges (count chips,
	 * status pills) — only the outer card-level radii get flattened. */
	.bc-blocks :global(.rounded-full) {
		border-radius: 999px !important;
	}
</style>
