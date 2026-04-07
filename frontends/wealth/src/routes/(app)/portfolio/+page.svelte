<!--
  Portfolio Builder — Flexible Columns Layout orchestrator.

  Reference: docs/superpowers/specs/2026-04-08-portfolio-builder-flexible-columns.md

  This file is a pure orchestrator. It:
    - Reads the portfolio workspace store (single source of truth).
    - Derives `layoutState` from observable facts
      (`selectedAnalyticsFund` + `portfolioId`) — never stored.
    - Mounts the `FlexibleColumnsLayout` primitive with 3 snippets:
      * leftColumn — switches between Models / Universe / Policy panels
        based on `workspace.activeBuilderTab`. The sub-pills header is
        preserved from the previous design — all three panels benefit
        from the wider column granted by the FCL.
      * centerColumn — `BuilderColumn` (action bar + main chart +
        allocation blocks with DnD drop targets).
      * rightColumn — `AnalyticsColumn` (Estado C drill-down). Placeholder
        v1; Phase C adds Fund / Portfolio / Stress / Compare tabs.
    - Wires `onSelectFund` from the Universe table to
      `workspace.setSelectedAnalyticsFund` (triggers Estado B → C).
    - Calls `workspace.resetBuilderEntry()` on mount to enforce the
      "reset ao voltar" rule from spec §1.3 — re-entering /portfolio
      always starts in Estado B, never in Estado C.
-->
<script lang="ts">
	import { getContext, onMount } from "svelte";
	import Plus from "lucide-svelte/icons/plus";

	import { workspace, type UniverseFund } from "$lib/state/portfolio-workspace.svelte";
	import FlexibleColumnsLayout, {
		type LayoutState,
	} from "$lib/components/layout/FlexibleColumnsLayout.svelte";
	import UniverseColumn from "$lib/components/portfolio/UniverseColumn.svelte";
	import BuilderColumn from "$lib/components/portfolio/BuilderColumn.svelte";
	import AnalyticsColumn from "$lib/components/portfolio/AnalyticsColumn.svelte";
	import ModelListPanel from "$lib/components/portfolio/ModelListPanel.svelte";
	import PolicyPanel from "$lib/components/portfolio/PolicyPanel.svelte";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	let portfolios = $derived((data.portfolios ?? []) as ModelPortfolio[]);

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	workspace.setGetToken(getToken);

	// Reset entry per spec §1.3 — 3rd column always starts closed.
	onMount(() => {
		workspace.resetBuilderEntry();
	});

	// Initial universe load — subsequent re-loads happen when the
	// Builder composition changes (see below) so `current_holdings`
	// stays fresh for correlation computation.
	$effect(() => {
		if (workspace.universe.length === 0 && !workspace.isLoadingUniverse) {
			workspace.loadUniverse();
		}
	});

	// ── Layout state — DERIVED, never stored ────────────────────────
	// The layout state is a pure function of observable facts in the
	// store. Storing it creates classes of bug like "three-col but
	// analyticsMode is null". See spec §2.2.
	//
	// analyticsMode drives Estado C openness:
	//   - "fund"      → row click in Universe table
	//   - "portfolio" → "View Chart" button in Builder action bar
	//   - null        → Estado B (2 columns)
	const layoutState = $derived<LayoutState>(
		workspace.analyticsMode !== null ? "three-col" : "two-col",
	);

	// ── Left column tab switching ───────────────────────────────────
	// The sub-pills (Models | Universe | Policy) survive the FCL
	// migration. All three panels now get the same wide column (45%
	// of workspace in Estado B, 30% in Estado C) — Models and Policy
	// simply benefit from the extra space.
	const sidebarTabs = [
		{ value: "models", label: "Models" },
		{ value: "universe", label: "Universe" },
		{ value: "policy", label: "Policy" },
	] as const;

	function handleSelectFund(fund: UniverseFund) {
		workspace.openAnalyticsForFund(fund);
	}
</script>

<svelte:head>
	<title>Portfolio Builder — InvestIntell</title>
</svelte:head>

<div class="bld-shell">
	<FlexibleColumnsLayout {layoutState}>
		{#snippet leftColumn()}
			<div class="bld-left">
				<div class="bld-left-header">
					<button type="button" class="bld-pill bld-pill--new">
						<Plus size={16} />
						<span>New Portfolio</span>
					</button>
				</div>

				<div class="bld-sub-pills">
					{#each sidebarTabs as tab (tab.value)}
						{@const active = workspace.activeBuilderTab === tab.value}
						<button
							type="button"
							class="bld-sub-pill"
							class:bld-sub-pill--active={active}
							onclick={() => (workspace.activeBuilderTab = tab.value)}
						>
							{tab.label}
						</button>
					{/each}
				</div>

				<div class="bld-left-content">
					{#if workspace.activeBuilderTab === "models"}
						<ModelListPanel {portfolios} />
					{:else if workspace.activeBuilderTab === "universe"}
						<UniverseColumn onSelectFund={handleSelectFund} />
					{:else}
						<PolicyPanel />
					{/if}
				</div>
			</div>
		{/snippet}

		{#snippet centerColumn()}
			<BuilderColumn />
		{/snippet}

		{#snippet rightColumn()}
			<AnalyticsColumn />
		{/snippet}
	</FlexibleColumnsLayout>

	<!-- Error toast — preserved from previous design -->
	{#if workspace.lastError}
		<div class="bld-error-toast">
			<span>
				<strong>{workspace.lastError.action} failed:</strong>
				{workspace.lastError.message}
			</span>
			<button
				class="bld-error-close"
				onclick={() => { workspace.lastError = null; }}
				aria-label="Dismiss error"
			>
				&times;
			</button>
		</div>
	{/if}
</div>

<style>
	/* ── Hardcoded dark palette — matches legacy UniversePanel ─────
	 * No var() fallbacks — the component is force-rendered dark
	 * regardless of theme context so visual validation on dev
	 * server without a theme provider matches production. */

	.bld-shell {
		height: 100%;
		width: 100%;
		min-height: 0;
		overflow: hidden;
		position: relative;
		background: #0e0f13;
	}

	/* ── Left column chrome ──────────────────────────────────────── */
	.bld-left {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		background: #141519;
	}

	.bld-left-header {
		display: flex;
		align-items: center;
		padding: 16px;
		flex-shrink: 0;
	}

	/* New Portfolio pill — matches Screener .scr-pill pattern */
	.bld-pill {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 10px 18px;
		border: 1px solid #ffffff;
		border-radius: 36px;
		background: #000000;
		color: #ffffff;
		font-family: "Urbanist", sans-serif;
		font-size: 13px;
		font-weight: 400;
		cursor: pointer;
		transition: background 120ms ease;
		white-space: nowrap;
	}

	.bld-pill:hover {
		background: #1a1b20;
	}

	.bld-sub-pills {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 0 16px 16px;
		flex-shrink: 0;
		border-bottom: 1px solid rgba(64, 66, 73, 0.4);
	}

	.bld-sub-pill {
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

	.bld-sub-pill:hover {
		color: #ffffff;
		background: rgba(255, 255, 255, 0.03);
	}

	.bld-sub-pill--active {
		background: #0177fb;
		color: #ffffff;
		font-weight: 600;
	}

	.bld-sub-pill--active:hover {
		background: #0177fb;
	}

	.bld-left-content {
		flex: 1;
		min-height: 0;
		overflow: hidden;
	}

	/* ── Error toast (preserved) ─────────────────────────────────── */
	.bld-error-toast {
		position: absolute;
		bottom: 20px;
		right: 20px;
		max-width: 480px;
		padding: 12px 16px;
		background: var(--ii-danger, #dc2626);
		color: white;
		border-radius: 10px;
		box-shadow: 0 8px 24px -8px rgba(0, 0, 0, 0.4);
		display: flex;
		align-items: flex-start;
		gap: 12px;
		font-size: 0.8125rem;
		z-index: 100;
	}

	.bld-error-close {
		background: transparent;
		border: none;
		color: white;
		cursor: pointer;
		font-size: 1.25rem;
		line-height: 1;
		padding: 0 4px;
	}
</style>
