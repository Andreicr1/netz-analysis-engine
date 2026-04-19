<!--
  X3.1 — PORTFOLIO tab content.

  Absorbs /portfolio/builder's 40/60 command-center:
    LEFT (40%)  — portfolio selector + CalibrationPanel + RunControls
    RIGHT (60%) — 7 sub-tabs (REGIME / WEIGHTS / RISK / STRESS /
                  BACKTEST / MONTE CARLO / ADVISOR),
                  CascadeTimeline overlay while a build runs,
                  ActivationBar that unlocks once every sub-tab
                  has been visited.

  Two adjustments vs the original page:
    1. Height is 100% (parent workspace owns the shell cage). The
       original `calc(100vh - 88px)` was page-level and would leak
       past the profile + regime + tab strips now sitting above it.
    2. Optional `?portfolio_id=<uuid>` URL param wins over the
       auto-select of portfolios[0] so the redirect from
       /portfolio/builder?id=<id> lands the user on the right
       portfolio. Falls back to portfolios[0] when the query id
       doesn't match anything.

  Zone A (regime strip) from the original is dropped — the workspace
  header already renders RegimeContextStrip above the tab strip, so
  Zone A would duplicate context.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { SvelteSet } from "svelte/reactivity";
	import { page } from "$app/state";
	import { fly, fade } from "svelte/transition";
	import { svelteTransitionFor } from "@investintell/ui";
	import { workspace } from "@investintell/ii-terminal-core/state/portfolio-workspace.svelte";
	import type { ModelPortfolio } from "@investintell/ii-terminal-core/types/model-portfolio";

	import RunControls from "@investintell/ii-terminal-core/components/terminal/builder/RunControls.svelte";
	import WeightsTab from "@investintell/ii-terminal-core/components/terminal/builder/WeightsTab.svelte";
	import CascadeTimeline from "@investintell/ii-terminal-core/components/terminal/builder/CascadeTimeline.svelte";
	import StressTab from "@investintell/ii-terminal-core/components/terminal/builder/StressTab.svelte";
	import RiskTab from "@investintell/ii-terminal-core/components/terminal/builder/RiskTab.svelte";
	import AdvisorTab from "@investintell/ii-terminal-core/components/terminal/builder/AdvisorTab.svelte";
	import BacktestTab from "@investintell/ii-terminal-core/components/terminal/builder/BacktestTab.svelte";
	import MonteCarloTab from "@investintell/ii-terminal-core/components/terminal/builder/MonteCarloTab.svelte";
	import RegimeTab from "@investintell/ii-terminal-core/components/terminal/builder/RegimeTab.svelte";
	import ActivationBar from "@investintell/ii-terminal-core/components/terminal/builder/ActivationBar.svelte";
	import CalibrationPanel from "@investintell/ii-terminal-core/components/portfolio/CalibrationPanel.svelte";

	interface Props {
		portfolios: ModelPortfolio[];
	}

	let { portfolios }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// ── Portfolio selection ──────────────────────────────────────
	let selectedPortfolio = $state<ModelPortfolio | null>(null);

	/** URL wins over auto-select so /portfolio/builder?id=X redirect preserves intent. */
	const urlPortfolioId = $derived(
		page.url.searchParams.get("portfolio_id"),
	);

	$effect(() => {
		workspace.setGetToken(getToken);

		// Prefer the portfolio the URL named — otherwise take the first.
		const targetId = urlPortfolioId;
		const target = targetId
			? (portfolios.find((p) => p.id === targetId) ?? portfolios[0] ?? null)
			: (portfolios[0] ?? null);

		if (target && target.id !== selectedPortfolio?.id) {
			selectPortfolio(target);
		}
	});

	function selectPortfolio(p: ModelPortfolio) {
		selectedPortfolio = p;
		workspace.selectPortfolio(p);
	}

	function handlePortfolioChange(e: Event) {
		const select = e.currentTarget as HTMLSelectElement;
		const p = portfolios.find((x) => x.id === select.value);
		if (p) selectPortfolio(p);
	}

	// ── Right-column 7-tab state ─────────────────────────────────
	const TABS = [
		"REGIME",
		"WEIGHTS",
		"RISK",
		"STRESS",
		"BACKTEST",
		"MONTE CARLO",
		"ADVISOR",
	] as const;
	type TabId = (typeof TABS)[number];

	let activeTab = $state<TabId>("REGIME");
	let userSwitchedTab = $state(false);
	let visitedTabs = $state<Set<TabId>>(new Set());

	$effect(() => {
		visitedTabs.add(activeTab);
	});

	/** ActivationBar unlocks only once every sub-tab has been visited. */
	const allTabsVisited = $derived(visitedTabs.size === TABS.length);

	function setActiveTab(t: TabId) {
		activeTab = t;
		userSwitchedTab = true;
	}

	// Cascade / pipeline phase mirroring the workspace run state.
	const cascadePhases = $derived(workspace.optimizerPhases);
	const showCascade = $derived(workspace.runPhase !== "idle");
	const showProgress = $derived(
		workspace.runPhase !== "idle" &&
			workspace.runPhase !== "done" &&
			workspace.runPhase !== "error",
	);
	const runProgress = $derived(workspace.runProgress);

	const pipelinePhase = $derived.by<
		| "IDLE"
		| "FACTOR_MODELING"
		| "SHRINKAGE"
		| "SOCP_OPTIMIZATION"
		| "BACKTESTING"
		| "COMPLETED"
	>(() => {
		switch (workspace.runPhase) {
			case "factor_modeling":
				return "FACTOR_MODELING";
			case "shrinkage":
				return "SHRINKAGE";
			case "optimizer":
				return "SOCP_OPTIMIZATION";
			case "stress":
				return "BACKTESTING";
			case "done":
				return "COMPLETED";
			default:
				return "IDLE";
		}
	});
	const pipelineErrored = $derived(workspace.runPhase === "error");

	/** Tabs that should pulse while their upstream phase is in flight. */
	const pulsingTabs = $derived.by<SvelteSet<TabId>>(() => {
		const set = new SvelteSet<TabId>();
		switch (workspace.runPhase) {
			case "factor_modeling":
			case "shrinkage":
				set.add("RISK");
				break;
			case "optimizer":
				set.add("WEIGHTS");
				break;
			case "stress":
				set.add("STRESS");
				set.add("BACKTEST");
				break;
			default:
				break;
		}
		return set;
	});

	$effect(() => {
		if (
			workspace.runPhase === "done" &&
			!userSwitchedTab &&
			activeTab === "REGIME"
		) {
			activeTab = "WEIGHTS";
		}
	});
	$effect(() => {
		if (workspace.runPhase === "running") {
			userSwitchedTab = false;
		}
	});
</script>

<div class="builder-shell">
	<!-- LEFT COLUMN (40%) — Command Panel -->
	<div class="builder-left">
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

		<div class="builder-calibration">
			{#if selectedPortfolio}
				<CalibrationPanel />
			{:else}
				<div class="builder-empty-zone">Select a portfolio to configure</div>
			{/if}
		</div>

		{#if selectedPortfolio}
			<RunControls />
		{/if}
	</div>

	<!-- RIGHT COLUMN (60%) — Results Panel -->
	<div class="builder-right">
		<div class="builder-tabs" role="tablist">
			{#each TABS as tab (tab)}
				<button
					type="button"
					role="tab"
					class="builder-tab"
					class:builder-tab--active={activeTab === tab}
					aria-selected={activeTab === tab}
					onclick={() => setActiveTab(tab)}
				>
					{tab}
					{#if pulsingTabs.has(tab)}
						<span
							class="builder-tab-pulse"
							aria-label="Pipeline phase in flight"
						></span>
					{/if}
				</button>
			{/each}
		</div>

		{#if showCascade}
			<div
				in:fly={{ y: -8, ...svelteTransitionFor("primary", { duration: "update" }) }}
			>
				<CascadeTimeline
					phases={cascadePhases}
					{runProgress}
					{showProgress}
					{pipelinePhase}
					{pipelineErrored}
				/>
			</div>
		{/if}

		<div class="builder-tab-content" role="tabpanel">
			{#key activeTab}
				<div in:fade={svelteTransitionFor("chrome", { duration: "tick" })}>
					{#if activeTab === "REGIME"}
						<RegimeTab />
					{:else if activeTab === "WEIGHTS"}
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

		<ActivationBar {allTabsVisited} />
	</div>
</div>

<style>
	/*
	 * Height is 100% — the workspace shell already cages the page to
	 * calc(100vh - 88px) and leaves us the remaining space after the
	 * breadcrumb / profile strip / regime strip / tab strip.
	 */
	.builder-shell {
		display: grid;
		grid-template-columns: 40% 60%;
		height: 100%;
		min-height: 0;
		background: var(--terminal-bg-void);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-secondary);
	}

	.builder-left {
		display: flex;
		flex-direction: column;
		overflow: hidden;
		border-right: var(--terminal-border-hairline);
		min-height: 0;
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
		min-height: 0;
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

	.builder-right {
		display: flex;
		flex-direction: column;
		overflow: hidden;
		min-height: 0;
	}

	.builder-tabs {
		display: flex;
		align-items: stretch;
		height: 32px;
		border-bottom: var(--terminal-border-hairline);
		flex-shrink: 0;
	}

	.builder-tab {
		position: relative;
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-1);
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
		min-height: 0;
	}

	.builder-tab-pulse {
		display: inline-block;
		width: 4px;
		height: 4px;
		border-radius: 50%;
		background: var(--terminal-status-warn, var(--terminal-accent-amber));
		animation: builder-tab-pulse 1s ease-in-out infinite;
	}
	@keyframes builder-tab-pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.4;
		}
	}
</style>
