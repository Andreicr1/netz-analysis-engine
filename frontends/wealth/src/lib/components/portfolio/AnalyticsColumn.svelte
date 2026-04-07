<!--
  AnalyticsColumn — 3rd column of the Portfolio Builder Flexible
  Columns Layout. Drives Estado C of the adaptive grid.

  Reference: docs/superpowers/specs/2026-04-08-portfolio-builder-flexible-columns.md §1.3

  Two modes routed by `workspace.analyticsMode`:
    - "fund"      → selectedAnalyticsFund drill-down placeholder
                    (Phase C adds the full Fund tab with LayerChart)
    - "portfolio" → MainPortfolioChart NAV synthesis for the current
                    portfolio (moved here from the BuilderColumn top)

  Phase C will add proper tabs (Fund / Portfolio / Stress / Compare)
  and replace the inline MainPortfolioChart with LayerChart primitives.
  For now the existing MainPortfolioChart is re-hosted here so the
  BuilderColumn gets full vertical space for allocation blocks.

  Esc closes the column (via window keydown + cleanup effect). The
  close button clears both `analyticsMode` and `selectedAnalyticsFund`.

  Dark-mode hex values hardcoded — no var() fallbacks.
-->
<script lang="ts">
	import X from "lucide-svelte/icons/x";
	import { PanelEmptyState, PanelErrorState } from "@investintell/ui/runtime";
	import MainPortfolioChart from "$lib/components/portfolio/MainPortfolioChart.svelte";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";

	function handleClose() {
		workspace.clearAnalytics();
	}

	// Close on Escape — window-level keydown with cleanup effect.
	// Phase C will promote this to createMountedGuard + scoped
	// keydown on the page wrapper for proper focus trap behaviour.
	$effect(() => {
		function onKey(e: KeyboardEvent) {
			if (e.key === "Escape" && workspace.analyticsMode !== null) {
				handleClose();
			}
		}
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	});

	const mode = $derived(workspace.analyticsMode);
	const fund = $derived(workspace.selectedAnalyticsFund);

	const headerKicker = $derived(
		mode === "fund" ? "Fund Details" :
		mode === "portfolio" ? "Portfolio Chart" :
		"Analytics",
	);

	const headerTitle = $derived(
		mode === "fund"
			? (fund?.fund_name ?? "—")
			: mode === "portfolio"
				? (workspace.portfolio?.display_name ?? "Current portfolio")
				: "No selection",
	);
</script>

<svelte:boundary>
	<div class="ac-root">
		<header class="ac-header">
			<div class="ac-title-block">
				<span class="ac-kicker">{headerKicker}</span>
				<span class="ac-title">{headerTitle}</span>
				{#if mode === "fund" && fund?.ticker}
					<span class="ac-ticker">{fund.ticker}</span>
				{/if}
			</div>
			<button
				type="button"
				class="ac-close"
				onclick={handleClose}
				aria-label="Close analytics panel"
			>
				<X size={16} />
			</button>
		</header>

		<div class="ac-body">
			{#if mode === null}
				<PanelEmptyState
					title="Analytics closed"
					message="Click a fund in the Universe or use View Chart in the Builder action bar to open this panel."
				/>
			{:else if mode === "portfolio"}
				<!-- Portfolio NAV synthesis chart, relocated from the
				     old Builder column top card. Phase C will swap
				     MainPortfolioChart for a LayerChart primitive. -->
				<div class="ac-chart-frame">
					<MainPortfolioChart />
				</div>
			{:else if mode === "fund" && fund}
				<div class="ac-placeholder">
					<p class="ac-placeholder-text">
						Full fund drill-down arrives in Phase C — tabs for Fund, Portfolio, Stress and Compare with LayerChart visuals.
					</p>
					<dl class="ac-meta">
						<div class="ac-meta-row">
							<dt>Asset Class</dt>
							<dd>{fund.asset_class ?? "—"}</dd>
						</div>
						<div class="ac-meta-row">
							<dt>Block</dt>
							<dd>{fund.block_label}</dd>
						</div>
						<div class="ac-meta-row">
							<dt>Geography</dt>
							<dd>{fund.geography ?? "—"}</dd>
						</div>
					</dl>
				</div>
			{/if}
		</div>
	</div>

	{#snippet failed(error: unknown, reset: () => void)}
		<PanelErrorState
			title="Analytics panel failed"
			message={error instanceof Error ? error.message : "Unexpected error in the analytics column."}
			onRetry={reset}
		/>
	{/snippet}
</svelte:boundary>

<style>
	/* Hardcoded dark palette (matches legacy UniversePanel). */
	.ac-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		background: #141519;
		border-left: 1px solid rgba(64, 66, 73, 0.4);
	}

	.ac-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		padding: 14px 16px;
		border-bottom: 1px solid rgba(64, 66, 73, 0.4);
		flex-shrink: 0;
		background: #141519;
	}

	.ac-title-block {
		display: flex;
		flex-direction: column;
		gap: 3px;
		min-width: 0;
	}

	.ac-kicker {
		font-size: 0.6875rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: #85a0bd;
	}

	.ac-title {
		font-size: 0.9375rem;
		font-weight: 700;
		color: #ffffff;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 320px;
	}

	.ac-ticker {
		font-size: 0.75rem;
		color: #85a0bd;
		font-variant-numeric: tabular-nums;
	}

	.ac-close {
		background: transparent;
		border: none;
		color: #85a0bd;
		cursor: pointer;
		padding: 4px;
		border-radius: 2px;
		flex-shrink: 0;
	}

	.ac-close:hover {
		background: rgba(255, 255, 255, 0.05);
		color: #ffffff;
	}

	.ac-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 16px;
	}

	/* Chart frame — flat, no rounded corners, minimal chrome. */
	.ac-chart-frame {
		width: 100%;
		min-height: 360px;
		background: #141519;
	}

	.ac-placeholder {
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	.ac-placeholder-text {
		font-size: 0.8125rem;
		line-height: 1.5;
		color: #85a0bd;
		font-style: italic;
	}

	.ac-meta {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 12px;
		background: rgba(255, 255, 255, 0.03);
		border: 1px solid rgba(64, 66, 73, 0.4);
	}

	.ac-meta-row {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		padding: 6px 0;
		font-size: 0.75rem;
		border-bottom: 1px solid rgba(64, 66, 73, 0.3);
	}

	.ac-meta-row:last-child {
		border-bottom: none;
	}

	.ac-meta-row dt {
		color: #85a0bd;
	}

	.ac-meta-row dd {
		color: #ffffff;
		font-weight: 500;
	}
</style>
