<!--
  Portfolio Builder — Phase 11 "Million Dollar" refactor.

  Permanent 3-column grid (280px | 1fr | 1fr):
    Col 1 — PortfolioListPanel (always visible, vertical scroll)
    Col 2 — UniverseColumn (4-col lean table, drag source)
    Col 3 — BuilderColumn with [Allocations | Policy Rules] tabs,
             action bar in footer (Run Construct always visible)

  Fund details open in FundDetailsDrawer (slide-out overlay).
  Construction results will be a full-screen overlay (Phase 12).
-->
<script lang="ts">
	import { getContext, onMount } from "svelte";

	import { workspace, type UniverseFund } from "$lib/state/portfolio-workspace.svelte";
	import UniverseColumn from "$lib/components/portfolio/UniverseColumn.svelte";
	import BuilderColumn from "$lib/components/portfolio/BuilderColumn.svelte";
	import PortfolioListPanel from "$lib/components/portfolio/PortfolioListPanel.svelte";
	import NewPortfolioDialog from "$lib/components/portfolio/NewPortfolioDialog.svelte";
	import FundDetailsDrawer from "$lib/components/portfolio/FundDetailsDrawer.svelte";
	import ConstructionResultsOverlay from "$lib/components/portfolio/ConstructionResultsOverlay.svelte";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	let portfolios = $derived((data.portfolios ?? []) as ModelPortfolio[]);

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	workspace.setGetToken(getToken);

	onMount(() => {
		workspace.resetBuilderEntry();
	});

	// ── State ──────────────────────────────────────────────────
	const hasSelectedPortfolio = $derived(workspace.portfolio !== null);

	function handleSelectPortfolio(mp: ModelPortfolio) {
		workspace.selectPortfolio(mp);
	}

	// ── New Portfolio dialog ──────────────────────────────────
	let newPortfolioOpen = $state(false);

	// ── Fund Details Drawer (click on universe row) ───────────
	let drawerFund = $state<UniverseFund | null>(null);

	// ── Construction Results Overlay ──────────────────────────
	let showResultsOverlay = $state(false);

	// Auto-open overlay when construction completes successfully
	$effect(() => {
		if (workspace.runPhase === "done" && workspace.constructionRun) {
			showResultsOverlay = true;
		}
	});

	// Initial universe load when a portfolio is selected
	$effect(() => {
		if (
			hasSelectedPortfolio &&
			workspace.universe.length === 0 &&
			!workspace.isLoadingUniverse
		) {
			workspace.loadUniverse();
		}
	});

	function handleSelectFund(fund: UniverseFund) {
		drawerFund = fund;
	}
</script>

<svelte:head>
	<title>Portfolio Builder — InvestIntell</title>
</svelte:head>

<div class="bld-grid">
	<!-- ── Col 1: Portfolio List (280px, always visible) ──────── -->
	<aside class="bld-col1">
		<PortfolioListPanel
			{portfolios}
			onSelect={handleSelectPortfolio}
			onNewPortfolio={() => (newPortfolioOpen = true)}
		/>
	</aside>

	<!-- ── Col 2: Universe (1fr) ─────────────────────────────── -->
	<section class="bld-col2">
		{#if hasSelectedPortfolio}
			<UniverseColumn onSelectFund={handleSelectFund} />
		{:else}
			<div class="bld-empty">
				<p class="bld-empty-title">Approved Universe</p>
				<p class="bld-empty-hint">Select a portfolio from the left panel to browse approved instruments.</p>
			</div>
		{/if}
	</section>

	<!-- ── Col 3: Builder (1fr) ───────────────────────────────── -->
	<section class="bld-col3">
		{#if hasSelectedPortfolio}
			<BuilderColumn />
		{:else}
			<div class="bld-empty">
				<p class="bld-empty-title">Portfolio Builder</p>
				<p class="bld-empty-hint">Select a portfolio from the left panel to start building.</p>
			</div>
		{/if}
	</section>
</div>

<!-- New Portfolio dialog -->
<NewPortfolioDialog
	open={newPortfolioOpen}
	onOpenChange={(v) => (newPortfolioOpen = v)}
	{portfolios}
/>

<!-- Fund Details Drawer (click on universe row) -->
{#if drawerFund}
	<FundDetailsDrawer
		fund={drawerFund}
		onClose={() => (drawerFund = null)}
	/>
{/if}

<!-- Construction Results Overlay (auto-opens on run completion) -->
{#if showResultsOverlay}
	<ConstructionResultsOverlay
		onClose={() => (showResultsOverlay = false)}
	/>
{/if}

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
	/* ── 3-column rigid grid ────────────────────────────────── */
	.bld-grid {
		display: grid;
		grid-template-columns: 280px 1fr 1fr;
		height: 100%;
		width: 100%;
		min-height: 0;
		overflow: hidden;
		background: #0e0f13;
	}

	.bld-col1 {
		min-height: 0;
		overflow: hidden;
	}

	.bld-col2,
	.bld-col3 {
		min-height: 0;
		overflow: hidden;
		border-left: 1px solid rgba(64, 66, 73, 0.4);
	}

	/* ── Empty states for Col 2 / Col 3 ─────────────────────── */
	.bld-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		gap: 8px;
		padding: 32px;
		background: #141519;
	}
	.bld-empty-title {
		margin: 0;
		font-size: 13px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, #85a0bd);
		font-family: "Urbanist", sans-serif;
	}
	.bld-empty-hint {
		margin: 0;
		font-size: 13px;
		color: var(--ii-text-muted, #85a0bd);
		text-align: center;
		max-width: 280px;
		line-height: 1.5;
		font-family: "Urbanist", sans-serif;
	}

	/* ── Error toast ──────────────────────────────────────────── */
	.bld-error-toast {
		position: fixed;
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
