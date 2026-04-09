<!--
  Portfolio Builder — Master-Detail pattern (Phase 10).

  Two states driven by ``workspace.portfolio``:

  1. **Master (selector)** — when no portfolio is selected, the page
     renders a centered ``PortfolioSelector`` grid with cards for
     Active / Drafts / Archived and a "+ New Portfolio" CTA. The PM
     picks a portfolio to enter the Builder.

  2. **Detail (builder)** — when a portfolio is selected, the page
     renders the FlexibleColumnsLayout with:
     * leftColumn — fixed header (← Back + portfolio name) + sub-pills
       (Universe | Policy only — Models tab removed per Phase 10 mandate).
     * centerColumn — BuilderColumn (allocation blocks, action bar).
     * rightColumn — AnalyticsColumn or BuilderRightStack (Calibration
       Results, Narrative, Stress, Chart tabs).

  The PM can return to Master view via the "← Back to Models" button
  which clears ``workspace.portfolio``. Universe and Policy tabs are
  never visible without a portfolio context.

  Reference: docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md
-->
<script lang="ts">
	import { getContext, onMount } from "svelte";
	import ArrowLeft from "lucide-svelte/icons/arrow-left";

	import { workspace, type UniverseFund } from "$lib/state/portfolio-workspace.svelte";
	import { FlexibleColumnLayout, type FCLState } from "@investintell/ui";
	import UniverseColumn from "$lib/components/portfolio/UniverseColumn.svelte";
	import BuilderColumn from "$lib/components/portfolio/BuilderColumn.svelte";
	import AnalyticsColumn from "$lib/components/portfolio/AnalyticsColumn.svelte";
	import BuilderRightStack, {
		type BuilderRightTab,
	} from "$lib/components/portfolio/BuilderRightStack.svelte";
	import CalibrationPanel from "$lib/components/portfolio/CalibrationPanel.svelte";
	import PortfolioSelector from "$lib/components/portfolio/PortfolioSelector.svelte";
	import NewPortfolioDialog from "$lib/components/portfolio/NewPortfolioDialog.svelte";
	import { portfolioDisplayName } from "$lib/constants/blocks";
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

	// ── Master-Detail state ────────────────────────────────────
	// Driven by workspace.portfolio. When null → Master (selector),
	// when populated → Detail (builder).
	const hasSelectedPortfolio = $derived(workspace.portfolio !== null);

	function handleSelectPortfolio(mp: ModelPortfolio) {
		workspace.selectPortfolio(mp);
	}

	function handleBackToModels() {
		workspace.portfolio = null;
	}

	// ── BuilderRightStack tab state (Phase 4 Task 4.5) ─────────
	let rightTab = $state<BuilderRightTab>("calibration");

	// ── New Portfolio dialog ───────────────────────────────────
	let newPortfolioOpen = $state(false);

	$effect(() => {
		if (workspace.runPhase === "done") {
			rightTab = "narrative";
		} else if (
			workspace.runPhase === "running" ||
			workspace.runPhase === "optimizer" ||
			workspace.runPhase === "stress"
		) {
			rightTab = "narrative";
		}
	});

	// Initial universe load
	$effect(() => {
		if (
			hasSelectedPortfolio &&
			workspace.universe.length === 0 &&
			!workspace.isLoadingUniverse
		) {
			workspace.loadUniverse();
		}
	});

	// ── Layout state — DERIVED, never stored ────────────────────
	const layoutState = $derived<FCLState>(
		workspace.analyticsMode !== null ? "expand-3" : "expand-2",
	);

	const PORTFOLIO_RATIOS: Record<FCLState, [number, number, number]> = {
		"expand-1": [0, 1, 0],
		"expand-2": [1.4, 1, 0],
		"expand-3": [1.5, 1, 1.1],
	};

	// ── Left column tab switching (Models tab removed) ──────────
	type BuilderSidebarTab = "universe" | "policy";
	const sidebarTabs: { value: BuilderSidebarTab; label: string }[] = [
		{ value: "universe", label: "Universe" },
		{ value: "policy", label: "Policy" },
	];

	// Reset to universe when coming back from models
	let sidebarTab = $state<BuilderSidebarTab>("universe");

	function handleSelectFund(fund: UniverseFund) {
		workspace.openAnalyticsForFund(fund);
	}
</script>

<svelte:head>
	<title>Portfolio Builder — InvestIntell</title>
</svelte:head>

{#if !hasSelectedPortfolio}
	<!-- ── MASTER VIEW: Portfolio Selector ────────────────────── -->
	<div class="bld-shell">
		<PortfolioSelector
			{portfolios}
			onSelect={handleSelectPortfolio}
			onNewPortfolio={() => (newPortfolioOpen = true)}
		/>
	</div>
{:else}
	<!-- ── DETAIL VIEW: Builder ───────────────────────────────── -->
	<div class="bld-shell">
		<FlexibleColumnLayout
			state={layoutState}
			ratios={PORTFOLIO_RATIOS}
			column1Label="Builder Tools"
			column2Label="Portfolio Builder"
			column3Label="Analytics"
			column1={leftColumn}
			column2={centerColumn}
			column3={rightColumn}
		/>

		{#snippet leftColumn()}
			<div class="bld-left">
				<!-- Fixed header: Back button + portfolio name -->
				<div class="bld-left-context">
					<button
						type="button"
						class="bld-back-btn"
						onclick={handleBackToModels}
						title="Back to portfolio list"
					>
						<ArrowLeft size={14} />
						<span>Models</span>
					</button>
					<div class="bld-active-portfolio">
						<span class="bld-active-name">
							{workspace.portfolio?.display_name ?? ""}
						</span>
						<span class="bld-active-state">
							{workspace.portfolio?.state ?? ""}
						</span>
					</div>
				</div>

				<!-- Sub-pills: Universe | Policy (no Models) -->
				<div class="bld-sub-pills">
					{#each sidebarTabs as tab (tab.value)}
						{@const active = sidebarTab === tab.value}
						<button
							type="button"
							class="bld-sub-pill"
							class:bld-sub-pill--active={active}
							onclick={() => (sidebarTab = tab.value)}
						>
							{tab.label}
						</button>
					{/each}
				</div>

				<div class="bld-left-content">
					{#if sidebarTab === "universe"}
						<UniverseColumn onSelectFund={handleSelectFund} />
					{:else}
						<CalibrationPanel />
					{/if}
				</div>
			</div>
		{/snippet}

		{#snippet centerColumn()}
			<BuilderColumn />
		{/snippet}

		{#snippet rightColumn()}
			{#if workspace.analyticsMode === "fund"}
				<AnalyticsColumn />
			{:else}
				<BuilderRightStack
					active={rightTab}
					onActiveChange={(t) => (rightTab = t)}
				/>
			{/if}
		{/snippet}
	</div>
{/if}

<!-- New Portfolio dialog — available from both Master and Detail -->
<NewPortfolioDialog
	open={newPortfolioOpen}
	onOpenChange={(v) => (newPortfolioOpen = v)}
	{portfolios}
/>

<!-- Error toast -->
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

<style>
	.bld-shell {
		height: 100%;
		width: 100%;
		min-height: 0;
		overflow: hidden;
		position: relative;
		background: #0e0f13;
	}

	/* ── Left column chrome ──────────────────────────────────── */
	.bld-left {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		background: #141519;
	}

	/* Context header: Back + active portfolio name */
	.bld-left-context {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 14px 16px 12px;
		border-bottom: 1px solid rgba(64, 66, 73, 0.4);
		flex-shrink: 0;
	}
	.bld-back-btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 4px 0;
		background: transparent;
		border: none;
		color: var(--ii-text-muted, #85a0bd);
		font-family: "Urbanist", sans-serif;
		font-size: 11px;
		font-weight: 600;
		cursor: pointer;
		transition: color 120ms ease;
	}
	.bld-back-btn:hover {
		color: #ffffff;
	}
	.bld-back-btn:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: 2px;
	}
	.bld-active-portfolio {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
	}
	.bld-active-name {
		font-size: 14px;
		font-weight: 700;
		color: var(--ii-text-primary, #ffffff);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		min-width: 0;
	}
	.bld-active-state {
		font-size: 9px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, #85a0bd);
		flex-shrink: 0;
		padding: 2px 6px;
		border: 1px solid rgba(255, 255, 255, 0.12);
		border-radius: 3px;
	}

	.bld-sub-pills {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 12px 16px;
		flex-shrink: 0;
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

	/* ── Error toast ──────────────────────────────────────────── */
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
