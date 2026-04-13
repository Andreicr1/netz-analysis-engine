<!--
  /portfolio/builder — Phase 4 Terminal Builder.

  2-column command center (40% command / 60% results).
  Left: Zone A (regime), Zone B (calibration), Zone C (run controls).
  Right: Zone D (cascade timeline), Zone E (6-tab results panel).

  Session 2: CascadeTimeline, SSE wiring, STRESS/RISK/ADVISOR tabs,
  tab-visit tracking gate for Session 3 activation unlock.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import type { PageData } from "./$types";

	import RegimeContextStrip from "$lib/components/terminal/builder/RegimeContextStrip.svelte";
	import RunControls from "$lib/components/terminal/builder/RunControls.svelte";
	import WeightsTab from "$lib/components/terminal/builder/WeightsTab.svelte";
	import CascadeTimeline from "$lib/components/terminal/builder/CascadeTimeline.svelte";
	import StressTab from "$lib/components/terminal/builder/StressTab.svelte";
	import RiskTab from "$lib/components/terminal/builder/RiskTab.svelte";
	import AdvisorTab from "$lib/components/terminal/builder/AdvisorTab.svelte";
	import BacktestTab from "$lib/components/terminal/builder/BacktestTab.svelte";
	import MonteCarloTab from "$lib/components/terminal/builder/MonteCarloTab.svelte";
	import ActivationBar from "$lib/components/terminal/builder/ActivationBar.svelte";
	import CalibrationPanel from "$lib/components/portfolio/CalibrationPanel.svelte";
	import { fly, fade } from "svelte/transition";
	import { svelteTransitionFor } from "@investintell/ui";
	import { resolve } from "$app/paths";

	const HREF_SCREENER = resolve("/terminal-screener");

	let { data }: { data: PageData } = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// Portfolio selection state
	let selectedPortfolio = $state<ModelPortfolio | null>(null);
	const portfolios = $derived((data.portfolios ?? []) as ModelPortfolio[]);

	// Initialize workspace on mount
	$effect(() => {
		workspace.setGetToken(getToken);

		// Auto-select first portfolio if available
		const first = portfolios[0];
		if (first && !selectedPortfolio) {
			selectPortfolio(first);
		}
	});

	function selectPortfolio(p: ModelPortfolio) {
		selectedPortfolio = p;
		workspace.selectPortfolio(p);
	}

	function handlePortfolioChange(e: Event) {
		const select = e.currentTarget as HTMLSelectElement;
		const p = portfolios.find((p) => p.id === select.value);
		if (p) selectPortfolio(p);
	}

	// Regime bands: prefer workspace (live-updated) over server-loaded initial
	const regimeBands = $derived(workspace.regimeBands ?? data.initialRegimeBands);

	// Tab state for right column
	const TABS = ["WEIGHTS", "RISK", "STRESS", "BACKTEST", "MONTE CARLO", "ADVISOR"] as const;
	type TabId = (typeof TABS)[number];
	let activeTab = $state<TabId>("WEIGHTS");

	// ── Tab-visit tracking gate (Session 3 activation unlock) ────
	let visitedTabs = $state<Set<TabId>>(new Set());

	$effect(() => {
		visitedTabs.add(activeTab);
	});

	/** All 6 tabs must be visited before activation unlocks (Session 3). */
	const allTabsVisited = $derived(visitedTabs.size === 6);

	// Cascade timeline phases from workspace
	const cascadePhases = $derived(workspace.optimizerPhases);
	const showCascade = $derived(workspace.runPhase !== "idle");
</script>

<svelte:head>
	<title>Builder — InvestIntell</title>
</svelte:head>

<div class="builder-shell">
	<!-- LEFT COLUMN (40%) — Command Panel -->
	<div class="builder-left">
		<!-- Breadcrumb back to screener -->
		<a href={HREF_SCREENER} class="builder-backlink" data-sveltekit-preload-data="hover">
			&larr; SCREENER
		</a>

		<!-- Portfolio selector -->
		<div class="builder-portfolio-select">
			<select
				class="builder-select"
				value={selectedPortfolio?.id ?? ""}
				onchange={handlePortfolioChange}
				aria-label="Select portfolio"
			>
				{#if portfolios.length === 0}
					<option value="" disabled>No portfolios available</option>
				{:else}
					{#each portfolios as p (p.id)}
						<option value={p.id}>{p.display_name}</option>
					{/each}
				{/if}
			</select>
		</div>

		<!-- Zone A: Regime Context Strip (120px) -->
		<RegimeContextStrip {regimeBands} />

		<!-- Zone B: Calibration Controls (scrollable) -->
		<div class="builder-calibration">
			{#if selectedPortfolio}
				<CalibrationPanel />
			{:else}
				<div class="builder-empty-zone">Select a portfolio to configure</div>
			{/if}
		</div>

		<!-- Zone C: Run Controls (pinned to bottom) -->
		{#if selectedPortfolio}
			<RunControls />
		{/if}
	</div>

	<!-- RIGHT COLUMN (60%) — Results Panel -->
	<div class="builder-right">
		<!-- Tab bar -->
		<div class="builder-tabs" role="tablist">
			{#each TABS as tab (tab)}
				<button
					type="button"
					role="tab"
					class="builder-tab"
					class:builder-tab--active={activeTab === tab}
					aria-selected={activeTab === tab}
					onclick={() => { activeTab = tab; }}
				>
					{tab}
				</button>
			{/each}
		</div>

		<!-- Zone D: Cascade Timeline (visible during/after run) -->
		{#if showCascade}
			<div in:fly={{ y: -8, ...svelteTransitionFor("primary", { duration: "update" }) }}>
				<CascadeTimeline phases={cascadePhases} />
			</div>
		{/if}

		<!-- Zone E: Tab content -->
		<div class="builder-tab-content" role="tabpanel">
			{#key activeTab}
				<div in:fade={svelteTransitionFor("chrome", { duration: "tick" })}>
					{#if activeTab === "WEIGHTS"}
						<WeightsTab />
					{:else if activeTab === "RISK"}
						<RiskTab />
					{:else if activeTab === "STRESS"}
						<StressTab />
					{:else if activeTab === "BACKTEST"}
						<BacktestTab />
					{:else if activeTab === "MONTE CARLO"}
						<MonteCarloTab />
					{:else if activeTab === "ADVISOR"}
						<AdvisorTab />
					{/if}
				</div>
			{/key}
		</div>

		<!-- Zone F: Activation Bar (Session 3) -->
		<ActivationBar {allTabsVisited} />
	</div>
</div>

<style>
	.builder-shell {
		display: grid;
		grid-template-columns: 40% 60%;
		height: calc(100vh - 88px);
		background: var(--terminal-bg-void);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-secondary);
	}

	/* ── Left Column ──────────────────────────────────── */

	.builder-left {
		display: flex;
		flex-direction: column;
		overflow: hidden;
		border-right: var(--terminal-border-hairline);
	}

	.builder-backlink {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-1);
		padding: var(--terminal-space-1) var(--terminal-space-2);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		text-decoration: none;
		color: var(--terminal-fg-tertiary);
		border-bottom: var(--terminal-border-hairline);
		transition: color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.builder-backlink:hover {
		color: var(--terminal-accent-amber);
	}

	.builder-portfolio-select {
		padding: var(--terminal-space-2);
		border-bottom: var(--terminal-border-hairline);
	}

	.builder-select {
		width: 100%;
		height: 28px;
		background: var(--terminal-bg-panel-sunken);
		color: var(--terminal-fg-primary);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		padding: 0 var(--terminal-space-2);
		cursor: pointer;
	}

	.builder-select:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}

	.builder-calibration {
		flex: 1;
		overflow-y: auto;
	}

	.builder-empty-zone {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: 1;
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-11);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
	}

	/* ── Right Column ─────────────────────────────────── */

	.builder-right {
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.builder-tabs {
		display: flex;
		align-items: stretch;
		height: 32px;
		border-bottom: var(--terminal-border-hairline);
		flex-shrink: 0;
	}

	.builder-tab {
		display: inline-flex;
		align-items: center;
		padding: 0 var(--terminal-space-3);
		background: transparent;
		border: none;
		border-bottom: 2px solid transparent;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
		cursor: pointer;
		transition:
			color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.builder-tab:hover {
		color: var(--terminal-accent-amber);
	}

	.builder-tab--active {
		color: var(--terminal-accent-amber);
		border-bottom-color: var(--terminal-accent-amber);
	}

	.builder-tab:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: -2px;
	}

	.builder-tab-content {
		flex: 1;
		overflow-y: auto;
		padding: var(--terminal-space-2);
	}

</style>
