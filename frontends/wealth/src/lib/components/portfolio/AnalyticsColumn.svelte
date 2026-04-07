<!--
  AnalyticsColumn — 3rd column of the Portfolio Builder Flexible
  Columns Layout. Placeholder v1: shows header with selected fund
  identity + close button + "Coming in Phase C" placeholder cards.

  Reference: docs/superpowers/specs/2026-04-08-portfolio-builder-flexible-columns.md §1.3

  Phase C will add:
    - Tabs: Fund / Portfolio / Stress / Compare
    - LayerChart NAV history inside Fund tab
    - Top holdings, rolling vol, peer comparison
    - Stress scenarios in plain-English narratives
    - "Add to Builder" CTA

  For now this placeholder is enough to validate Estado B → C
  transition visually and to exercise the Esc-to-close flow.
-->
<script lang="ts">
	import X from "lucide-svelte/icons/x";
	import { PanelEmptyState, PanelErrorState } from "@investintell/ui/runtime";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";

	function handleClose() {
		workspace.clearSelectedAnalyticsFund();
	}

	// Close on Escape — follow-up will promote to `onkeydown` listener
	// on the page + use createMountedGuard, for now a simple handler
	// bound to window via an effect.
	$effect(() => {
		function onKey(e: KeyboardEvent) {
			if (e.key === "Escape" && workspace.selectedAnalyticsFund) {
				handleClose();
			}
		}
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	});

	const fund = $derived(workspace.selectedAnalyticsFund);
</script>

<svelte:boundary>
	<div class="ac-root">
		<header class="ac-header">
			<div class="ac-title-block">
				<span class="ac-kicker">Analytics</span>
				{#if fund}
					<span class="ac-fund-name">{fund.fund_name}</span>
					{#if fund.ticker}
						<span class="ac-fund-ticker">{fund.ticker}</span>
					{/if}
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
			{#if !fund}
				<PanelEmptyState
					title="No fund selected"
					message="Click a fund in the Approved Universe to open its drill-down."
				/>
			{:else}
				<div class="ac-placeholder">
					<p class="ac-placeholder-text">
						Full analytics drill-down arrives in Phase C — tabs for Fund, Portfolio, Stress and Compare with LayerChart visuals.
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
	.ac-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		background: var(--ii-surface, #141519);
	}

	.ac-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		padding: 14px 16px;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		flex-shrink: 0;
	}

	.ac-title-block {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}

	.ac-kicker {
		font-size: 0.6875rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ii-text-muted, #85a0bd);
	}

	.ac-fund-name {
		font-size: 0.9375rem;
		font-weight: 700;
		color: var(--ii-text-primary, white);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.ac-fund-ticker {
		font-size: 0.75rem;
		color: var(--ii-text-muted, #85a0bd);
		font-variant-numeric: tabular-nums;
	}

	.ac-close {
		background: transparent;
		border: none;
		color: var(--ii-text-muted, #85a0bd);
		cursor: pointer;
		padding: 4px;
		border-radius: 6px;
		flex-shrink: 0;
	}

	.ac-close:hover {
		background: rgba(255, 255, 255, 0.05);
		color: var(--ii-text-primary, white);
	}

	.ac-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 16px;
	}

	.ac-placeholder {
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	.ac-placeholder-text {
		font-size: 0.8125rem;
		line-height: 1.5;
		color: var(--ii-text-muted, #85a0bd);
		font-style: italic;
	}

	.ac-meta {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 12px;
		background: rgba(255, 255, 255, 0.03);
		border-radius: 8px;
	}

	.ac-meta-row {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		padding: 6px 0;
		font-size: 0.75rem;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.3));
	}

	.ac-meta-row:last-child {
		border-bottom: none;
	}

	.ac-meta-row dt {
		color: var(--ii-text-muted, #85a0bd);
	}

	.ac-meta-row dd {
		color: var(--ii-text-primary, white);
		font-weight: 500;
	}
</style>
