<!--
  LiveWorkbenchShell — Phase 8 Live Workbench orchestrator.

  Final major UI surface of netz-wealth-os. Renders the monitoring
  dashboard for portfolios in state === "live" with a persistent
  left sidebar + main KPI/allocations column.

  Layout (NOT AnalysisGrid — monitoring surface per user mandate):

    ┌── sidebar (280px) ─┐ ┌── main ───────────────────────┐
    │ LivePortfolio      │ │ LivePortfolioKpiStrip (6 card) │
    │   Sidebar          │ │                                │
    │   (state=live      │ │ LiveAllocationsTable           │
    │    portfolios)     │ │   (grouped by block, sticky    │
    │                    │ │    thead, scroll inside)       │
    └────────────────────┘ └────────────────────────────────┘

  The parent +page.svelte owns the URL state (``?portfolio=<id>``)
  and passes it in + out via ``selectedId`` + ``onSelect``. The shell
  is pure presentation — no fetches, no workspace reads, no
  localStorage.

  Per CLAUDE.md Stability Guardrails charter §3 — wrapped in
  <svelte:boundary> with PanelErrorState failed snippet.

  Per the Phase 8 user mandate:
    - PortfolioSubNav ribbon is visible (handled by the Phase 5
      /portfolio/+layout.svelte which mounts the ribbon for every
      /portfolio/* route, including /portfolio/live)
    - Empty state guides the PM to the Builder (/portfolio) when
      no live portfolios exist — institutional CTA, zero MOCK data
    - No ECharts, tabular/KPI only, formatters from @investintell/ui
-->
<script lang="ts">
	import { Button, EmptyState } from "@investintell/ui";
	import { PanelErrorState } from "@investintell/ui/runtime";
	import { goto } from "$app/navigation";
	import LivePortfolioSidebar from "./LivePortfolioSidebar.svelte";
	import LivePortfolioKpiStrip from "./LivePortfolioKpiStrip.svelte";
	import LiveAllocationsTable from "./LiveAllocationsTable.svelte";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";

	interface Props {
		portfolios: readonly ModelPortfolio[];
		selectedId: string | null;
		onSelect: (portfolio: ModelPortfolio) => void;
	}

	let { portfolios, selectedId, onSelect }: Props = $props();

	const hasPortfolios = $derived(portfolios.length > 0);
	const selected = $derived.by(() => {
		if (!selectedId) return portfolios[0] ?? null;
		return portfolios.find((p) => p.id === selectedId) ?? portfolios[0] ?? null;
	});

	function openBuilder() {
		void goto("/portfolio");
	}
</script>

<svelte:boundary>
	<div class="lws-root">
		{#if !hasPortfolios}
			<div class="lws-empty">
				<EmptyState
					title="No live portfolios yet"
					message="A portfolio enters the Live Workbench after it is constructed, validated, approved, and activated. Open the Builder to start a new portfolio or activate a draft."
				/>
				<div class="lws-empty-actions">
					<Button variant="default" onclick={openBuilder}>
						Open Builder →
					</Button>
				</div>
			</div>
		{:else}
			<div class="lws-grid">
				<LivePortfolioSidebar
					{portfolios}
					{selectedId}
					{onSelect}
				/>

				<main class="lws-main">
					{#if selected}
						<header class="lws-main-header">
							<div class="lws-title-block">
								<span class="lws-kicker">Live Portfolio</span>
								<h1 class="lws-title">{selected.display_name}</h1>
								{#if selected.description}
									<p class="lws-description">{selected.description}</p>
								{/if}
							</div>
						</header>

						<LivePortfolioKpiStrip portfolio={selected} />

						<LiveAllocationsTable portfolio={selected} />
					{:else}
						<div class="lws-empty lws-empty--inner">
							<EmptyState
								title="Select a portfolio"
								message="Pick a live portfolio from the left rail to view its KPIs and allocations."
							/>
						</div>
					{/if}
				</main>
			</div>
		{/if}
	</div>

	{#snippet failed(err: unknown, reset: () => void)}
		<PanelErrorState
			title="Live Workbench failed to render"
			message={err instanceof Error ? err.message : "Unexpected error in the Live Workbench."}
			onRetry={reset}
		/>
	{/snippet}
</svelte:boundary>

<style>
	.lws-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		background: #0e0f13;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.lws-grid {
		display: grid;
		grid-template-columns: 280px minmax(0, 1fr);
		height: 100%;
		min-height: 0;
	}

	.lws-main {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding: 20px 24px 24px;
		min-height: 0;
		min-width: 0;
		overflow-y: auto;
		container-type: inline-size;
	}

	.lws-main-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
		flex-shrink: 0;
	}
	.lws-title-block {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.lws-kicker {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--ii-text-muted, #85a0bd);
	}
	.lws-title {
		margin: 0;
		font-size: 20px;
		font-weight: 700;
		color: var(--ii-text-primary, #ffffff);
		line-height: 1.2;
	}
	.lws-description {
		margin: 0;
		font-size: 12px;
		color: var(--ii-text-muted, #85a0bd);
		max-width: 72ch;
	}

	.lws-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 20px;
		height: 100%;
		padding: 48px 24px;
	}
	.lws-empty--inner {
		background: #141519;
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		border-radius: 8px;
		margin: 24px;
		min-height: 240px;
	}
	.lws-empty-actions {
		display: flex;
		gap: 12px;
	}
</style>
