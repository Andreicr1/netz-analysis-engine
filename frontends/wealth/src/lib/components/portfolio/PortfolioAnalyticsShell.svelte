<!--
  PortfolioAnalyticsShell — Phase 6 Block A orchestrator for the
  /portfolio/analytics surface.

  Layout (per plan §5.2 + components draft §B.2):

    ┌── header ─────────────────────────────────────────────────────┐
    │  Title block + Group switcher (Returns/Risk | Holdings | …)   │
    ├── body ───────────────────────────────────────────────────────┤
    │ ┌── FilterRail (260px) ──┐ ┌── AnalysisGrid (3×2) ─────────┐  │
    │ │  ScopeSwitcher          │ │                                │  │
    │ │  AnalyticsSubjectList   │ │   ChartCard / placeholder      │  │
    │ │                         │ │                                │  │
    │ └─────────────────────────┘ └────────────────────────────────┘  │
    ├── BottomTabDock ──────────────────────────────────────────────┤
    └────────────────────────────────────────────────────────────────┘

  All state (scope, group, selectedSubjectId, tabs, activeTabId) is
  owned by the parent page which persists it into the URL query +
  hash. This shell is pure presentation — no internal state, no
  workspace mutations, no localStorage (DL15).

  Per CLAUDE.md Stability Guardrails charter §3 — wrapped in
  <svelte:boundary> with PanelErrorState failed snippet.
-->
<script lang="ts">
	import {
		FilterRail,
		AnalysisGrid,
		ChartCard,
		BottomTabDock,
		type BottomTabItem,
	} from "@investintell/ui";
	import { PanelErrorState } from "@investintell/ui/runtime";
	import ScopeSwitcher from "./ScopeSwitcher.svelte";
	import AnalyticsSubjectList from "./AnalyticsSubjectList.svelte";
	import AnalyticsPlaceholderCell from "./AnalyticsPlaceholderCell.svelte";
	import {
		ANALYTICS_GROUPS,
		ANALYTICS_GROUP_LABEL,
		type AnalyticsGroupFocus,
		type AnalyticsScope,
		type AnalyticsSubject,
		type AnalyticsTab,
	} from "$lib/portfolio/analytics-types";
	import { buildGridSpec } from "$lib/portfolio/analytics-grid-spec";

	interface Props {
		scope: AnalyticsScope;
		group: AnalyticsGroupFocus;
		subjects: readonly AnalyticsSubject[];
		selectedSubjectId: string | null;
		isLoadingSubjects?: boolean;
		tabs: readonly AnalyticsTab[];
		activeTabId: string | null;
		onScopeChange: (scope: AnalyticsScope) => void;
		onGroupChange: (group: AnalyticsGroupFocus) => void;
		onSelectSubject: (subject: AnalyticsSubject) => void;
		onSelectTab: (tab: AnalyticsTab) => void;
		onCloseTab: (tab: AnalyticsTab) => void;
	}

	let {
		scope,
		group,
		subjects,
		selectedSubjectId,
		isLoadingSubjects = false,
		tabs,
		activeTabId,
		onScopeChange,
		onGroupChange,
		onSelectSubject,
		onSelectTab,
		onCloseTab,
	}: Props = $props();

	const selectedSubject = $derived.by(() => {
		if (!selectedSubjectId) return null;
		return subjects.find((s) => s.id === selectedSubjectId) ?? null;
	});

	const gridSpec = $derived(buildGridSpec(scope, group));

	// ── BottomTabDock generic adapter ───────────────────────────
	// The dock is generic over ``T extends BottomTabItem`` but Svelte 5
	// component prop variance is strict — passing AnalyticsTab handlers
	// directly would fail the assignability check. These thin adapters
	// take the base BottomTabItem the dock emits and delegate to the
	// AnalyticsTab callbacks. The cast is safe because every tab in
	// the dock comes from this shell's ``tabs`` prop.
	function adaptSelect(tab: BottomTabItem) {
		onSelectTab(tab as AnalyticsTab);
	}
	function adaptClose(tab: BottomTabItem) {
		onCloseTab(tab as AnalyticsTab);
	}
</script>

<svelte:boundary>
	<div class="pas-root">
		<!-- ── Header — title + group switcher ─────────────────── -->
		<header class="pas-header">
			<div class="pas-titles">
				<span class="pas-kicker">Portfolio Analytics</span>
				<h1 class="pas-title">
					{selectedSubject?.name ?? "Select a subject"}
				</h1>
				{#if selectedSubject?.subtitle}
					<p class="pas-subtitle">{selectedSubject.subtitle}</p>
				{/if}
			</div>

			<nav class="pas-groups" aria-label="Analysis groups">
				{#each ANALYTICS_GROUPS as g (g)}
					{@const isActive = group === g}
					<button
						type="button"
						class="pas-group-pill"
						class:pas-group-pill--active={isActive}
						aria-pressed={isActive}
						onclick={() => onGroupChange(g)}
					>
						{ANALYTICS_GROUP_LABEL[g]}
					</button>
				{/each}
			</nav>
		</header>

		<!-- ── Body — FilterRail (Col1) + AnalysisGrid (Col2) ──── -->
		<div class="pas-body">
			<FilterRail>
				{#snippet header()}
					<div class="pas-rail-header">
						<span class="pas-rail-kicker">Scope</span>
						<ScopeSwitcher value={scope} onValueChange={onScopeChange} />
					</div>
				{/snippet}
				{#snippet filters()}
					<div class="pas-rail-list">
						<span class="pas-rail-kicker pas-rail-kicker--list">Subjects</span>
						<AnalyticsSubjectList
							{scope}
							{subjects}
							selectedId={selectedSubjectId}
							isLoading={isLoadingSubjects}
							onSelect={onSelectSubject}
						/>
					</div>
				{/snippet}
			</FilterRail>

			<main class="pas-main">
				<header class="pas-grid-header">
					<h2 class="pas-grid-heading">{gridSpec.heading}</h2>
					{#if gridSpec.subtitle}
						<p class="pas-grid-subtitle">{gridSpec.subtitle}</p>
					{/if}
				</header>

				{#if gridSpec.cells.length === 0}
					<div class="pas-grid-empty">
						<AnalyticsPlaceholderCell
							chartName="Compare Both"
							description="Multi-subject diff lands in v1.1. Use Model Portfolios or Approved Universe in Phase 6 Block A."
							span={3}
						/>
					</div>
				{:else}
					<AnalysisGrid>
						{#each gridSpec.cells as cell (cell.id)}
							<ChartCard
								title={cell.chartName}
								subtitle="Block A placeholder"
								span={cell.span ?? 1}
								minHeight="280px"
							>
								<AnalyticsPlaceholderCell
									chartName={cell.chartName}
									description={cell.description}
								/>
							</ChartCard>
						{/each}
					</AnalysisGrid>
				{/if}
			</main>
		</div>

		<!-- ── BottomTabDock — cross-subject sessions ──────────── -->
		<footer class="pas-dock">
			<BottomTabDock
				{tabs}
				activeId={activeTabId}
				onSelect={adaptSelect}
				onClose={adaptClose}
				ariaLabel="Open analytics subjects"
			/>
		</footer>
	</div>

	{#snippet failed(err: unknown, reset: () => void)}
		<PanelErrorState
			title="Portfolio Analytics failed to render"
			message={err instanceof Error ? err.message : "Unexpected error in the analytics shell."}
			onRetry={reset}
		/>
	{/snippet}
</svelte:boundary>

<style>
	.pas-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		background: #0e0f13;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	/* ── Header ──────────────────────────────────────────────── */
	.pas-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 24px;
		padding: 16px 24px;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		background: #141519;
		flex-shrink: 0;
	}
	.pas-titles {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.pas-kicker {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, #85a0bd);
	}
	.pas-title {
		margin: 0;
		font-size: 18px;
		font-weight: 700;
		color: var(--ii-text-primary, #ffffff);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.pas-subtitle {
		margin: 0;
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	/* Group switcher (Returns & Risk | Holdings | Peer | Stress) */
	.pas-groups {
		display: inline-flex;
		gap: 6px;
		flex-shrink: 0;
	}
	.pas-group-pill {
		padding: 8px 16px;
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.6));
		border-radius: 999px;
		background: transparent;
		color: var(--ii-text-muted, #85a0bd);
		font-family: inherit;
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
	}
	.pas-group-pill:hover:not(.pas-group-pill--active) {
		background: rgba(255, 255, 255, 0.04);
		color: var(--ii-text-primary, #ffffff);
	}
	.pas-group-pill--active {
		background: var(--ii-primary, #0177fb);
		border-color: transparent;
		color: #ffffff;
	}

	/* ── Body — FCL-like 2 columns ───────────────────────────── */
	.pas-body {
		flex: 1;
		display: flex;
		min-height: 0;
		min-width: 0;
	}

	.pas-rail-header {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 16px 12px 4px;
	}
	.pas-rail-list {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 12px 12px 16px;
	}
	.pas-rail-kicker {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, #85a0bd);
	}
	.pas-rail-kicker--list {
		padding: 0 4px 4px;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
	}

	.pas-main {
		flex: 1;
		min-width: 0;
		min-height: 0;
		overflow-y: auto;
		container-type: inline-size;
	}

	.pas-grid-header {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 24px 24px 0;
	}
	.pas-grid-heading {
		margin: 0;
		font-size: 16px;
		font-weight: 700;
		color: var(--ii-text-primary, #ffffff);
	}
	.pas-grid-subtitle {
		margin: 0;
		font-size: 12px;
		color: var(--ii-text-muted, #85a0bd);
	}

	.pas-grid-empty {
		padding: 24px;
	}

	/* ── BottomTabDock footer ────────────────────────────────── */
	.pas-dock {
		flex-shrink: 0;
	}
</style>
