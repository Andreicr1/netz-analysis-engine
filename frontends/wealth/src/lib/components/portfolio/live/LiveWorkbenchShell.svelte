<!--
  LiveWorkbenchShell — Phase 9 Block B refactor.

  Consumes the new WorkbenchLayout primitive from @investintell/ui
  (promoted from the Phase 8 bespoke grid) and routes the main
  content based on the ``activeTool`` prop. The shell is pure
  presentation — the parent +page.svelte owns BOTH URL-derived
  inputs (``selectedId`` and ``activeTool``) and patches the URL
  via ``onSelect`` / ``onToolChange`` callbacks.

  Layout (now delegated to WorkbenchLayout):

    ┌── sidebar (280px) ┐ ┌─── header: title + ToolRibbon ──┐
    │  LivePortfolio    │ ├──────────────────────────────────┤
    │    Sidebar        │ │  main (switched on activeTool)   │
    │                   │ │   overview       → KPI+Table     │
    │                   │ │   drift_analysis → placeholder   │
    │                   │ │   execution_desk → placeholder   │
    └───────────────────┘ └──────────────────────────────────┘

  Execution constraints honored (Phase 9 Block B mandate):
    - Svelte 5 runes only ($state, $derived, $props, snippets)
    - Zero new ECharts / data tables — drift & execution are
      placeholder EmptyStates
    - Shell of the interface + state routing, not the data layer
    - DL15 — no localStorage, URL is source of truth via parent
    - DL16 — formatters imported from @investintell/ui
    - CLAUDE.md Stability Guardrails §3 — <svelte:boundary> +
      PanelErrorState failed snippet preserved from Phase 8
-->
<script lang="ts">
	import { Button, EmptyState, WorkbenchLayout } from "@investintell/ui";
	import { PanelErrorState } from "@investintell/ui/runtime";
	import { goto } from "$app/navigation";
	import { getContext } from "svelte";
	import LivePortfolioSidebar from "./LivePortfolioSidebar.svelte";
	import LivePortfolioKpiStrip from "./LivePortfolioKpiStrip.svelte";
	import LiveAllocationsTable from "./LiveAllocationsTable.svelte";
	import WorkbenchToolRibbon from "./WorkbenchToolRibbon.svelte";
	import WorkbenchCoreChart from "./charts/WorkbenchCoreChart.svelte";
	import WeightVectorTable from "./WeightVectorTable.svelte";
	import RebalanceSuggestionPanel from "./RebalanceSuggestionPanel.svelte";
	import { type WorkbenchTool } from "./workbench-state";
	import {
		LivePricePoller,
		LIVE_PRICE_SPARKLINE_SLICE,
		type PriceTick,
	} from "$lib/workers/live_price_poll.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import type { ModelPortfolio, InstrumentWeight } from "$lib/types/model-portfolio";

	interface Props {
		portfolios: readonly ModelPortfolio[];
		selectedId: string | null;
		onSelect: (portfolio: ModelPortfolio) => void;
		activeTool: WorkbenchTool;
		onToolChange: (tool: WorkbenchTool) => void;
	}

	let {
		portfolios,
		selectedId,
		onSelect,
		activeTool,
		onToolChange,
	}: Props = $props();

	const hasPortfolios = $derived(portfolios.length > 0);
	const selected = $derived.by(() => {
		if (!selectedId) return portfolios[0] ?? null;
		return (
			portfolios.find((p) => p.id === selectedId) ?? portfolios[0] ?? null
		);
	});

	// ── Actual holdings state (OMS integration) ───────────────
	// The shell owns the actual-holdings data so both
	// WeightVectorTable (drift view) and RebalanceSuggestionPanel
	// (execution desk) consume the same reactive source. After a
	// successful trade execution, the panel calls refreshHoldings()
	// and the drift table re-renders with zeroed drifts immediately.
	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	interface ActualHolding {
		instrument_id: string;
		fund_name: string;
		instrument_type: string | null;
		block_id: string;
		weight: number;
		score: number;
	}

	let actualHoldings = $state<ActualHolding[]>([]);
	let holdingsLoading = $state(false);
	let holdingsSource = $state<"actual" | "target_fallback" | "none">("none");
	let holdingsError = $state<string | null>(null);

	async function fetchHoldings(portfolioId: string): Promise<void> {
		holdingsLoading = true;
		holdingsError = null;
		try {
			const res = await api.get<{
				portfolio_id: string;
				source: "actual" | "target_fallback";
				holdings: ActualHolding[];
				last_rebalanced_at: string | null;
			}>(`/model-portfolios/${portfolioId}/actual-holdings`);
			actualHoldings = res.holdings;
			holdingsSource = res.source;
		} catch (err) {
			holdingsError =
				err instanceof Error ? err.message : "Failed to load holdings";
			actualHoldings = [];
			holdingsSource = "none";
		} finally {
			holdingsLoading = false;
		}
	}

	async function refreshHoldings(): Promise<void> {
		if (selected) {
			await fetchHoldings(selected.id);
		}
	}

	// Fetch actual holdings whenever the selected portfolio changes
	// and the active tool is drift or execution (or eagerly for all).
	$effect(() => {
		const p = selected;
		if (!p) {
			actualHoldings = [];
			holdingsSource = "none";
			return;
		}
		fetchHoldings(p.id);
	});

	const targetFunds = $derived<InstrumentWeight[]>(
		selected?.fund_selection_schema?.funds ?? [],
	);

	// ── Live price feed lifecycle ──────────────────────────────
	// The poller instance is torn down and rebuilt whenever the
	// active tool leaves "overview" OR the selected portfolio
	// changes. The $effect cleanup fires before the next run, so
	// the previous interval is always drained before a new one
	// starts. When the shell unmounts entirely, the cleanup fires
	// one last time via Svelte 5's $effect teardown.
	let poller = $state<LivePricePoller | null>(null);

	$effect(() => {
		// Dependency pickup — these identifiers must be read inside
		// the effect body so Svelte tracks them.
		const shouldRun = activeTool === "overview" && selected !== null;
		if (!shouldRun) {
			poller = null;
			return;
		}
		// Deterministic-ish base price seeded from the portfolio id
		// so switching between portfolios anchors the random walk
		// at visually distinct starting levels without a database
		// dependency. Range: [80, 140].
		const idStr = selected!.id ?? "";
		let hash = 0;
		for (let i = 0; i < idStr.length; i++) {
			hash = (hash * 31 + idStr.charCodeAt(i)) | 0;
		}
		const basePrice = 80 + Math.abs(hash % 60);

		const p = new LivePricePoller({ basePrice, intervalMs: 1500 });
		poller = p;
		p.start();

		return () => {
			p.stop();
		};
	});

	const liveTicks = $derived<readonly PriceTick[]>(poller?.ticks ?? []);
	const sparklineBuffer = $derived<readonly number[]>(
		liveTicks.slice(-LIVE_PRICE_SPARKLINE_SLICE).map((t) => t.price),
	);

	// ── Viewport-driven chart height ───────────────────────────
	// Terminal breakout mandate: the chart must fill the
	// available vertical space inside the workbench main area.
	// We reserve fixed budgets for the terminal chrome (sidebar
	// not included — it is horizontal), the ultra-compact header,
	// the allocations footer, and the inter-panel gaps, then hand
	// the remainder to WorkbenchCoreChart via its ``height`` prop.
	// A resize listener keeps the calc live so the chart tracks
	// window resizes without touching the ECharts option config.
	const TERMINAL_HEADER_HEIGHT = 44;
	const ALLOCATIONS_FOOTER_HEIGHT = 280;
	const OVERVIEW_VERTICAL_CHROME = 48; // paddings + gaps
	const MIN_CHART_HEIGHT = 320;

	let viewportHeight = $state(
		typeof window !== "undefined" ? window.innerHeight : 900,
	);

	$effect(() => {
		if (typeof window === "undefined") return;
		const handler = () => {
			viewportHeight = window.innerHeight;
		};
		window.addEventListener("resize", handler);
		return () => window.removeEventListener("resize", handler);
	});

	const chartHeight = $derived(
		Math.max(
			MIN_CHART_HEIGHT,
			viewportHeight -
				TERMINAL_HEADER_HEIGHT -
				ALLOCATIONS_FOOTER_HEIGHT -
				OVERVIEW_VERTICAL_CHROME,
		),
	);

	function openBuilder() {
		void goto("/portfolio");
	}

	function exitTerminal() {
		// Back to Workspace — land on the Builder, which lives
		// under the standard (app) chrome and gives the PM the
		// three-phase ribbon back.
		void goto("/portfolio");
	}
</script>

<svelte:boundary>
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
		<WorkbenchLayout
			sidebarLabel="Live portfolios"
			headerLabel="Workbench toolbar"
			mainLabel="Active workbench tool"
		>
			{#snippet sidebar()}
				<LivePortfolioSidebar
					{portfolios}
					{selectedId}
					{onSelect}
				/>
			{/snippet}

			{#snippet header()}
				<div class="lws-term-header">
					<div class="lws-term-title">
						{#if selected}
							<span class="lws-term-name">{selected.display_name}</span>
						{:else}
							<span class="lws-term-name lws-term-name--muted">
								No portfolio selected
							</span>
						{/if}
						<span class="lws-term-sep">·</span>
						<span class="lws-term-mode">Live Execution</span>
					</div>
					<div class="lws-term-ribbon-slot">
						<WorkbenchToolRibbon {activeTool} {onToolChange} />
					</div>
					<div class="lws-term-actions">
						<button
							type="button"
							class="lws-term-exit"
							onclick={exitTerminal}
							title="Leave the terminal and return to the workspace"
							aria-label="Exit terminal"
						>
							<span class="lws-term-exit-glyph" aria-hidden="true">←</span>
							Exit Terminal
						</button>
					</div>
				</div>
			{/snippet}

			{#snippet main()}
				{#if selected}
					{#if activeTool === "overview"}
						<div class="lws-overview-stack">
							<section
								class="lws-overview-grid"
								aria-label="Overview surface"
							>
								<div class="lws-panel lws-panel--chart">
									<WorkbenchCoreChart
										ticks={liveTicks}
										height={chartHeight}
									/>
								</div>
								<aside
									class="lws-panel lws-panel--kpis"
									aria-label="Portfolio KPI stack"
								>
									<LivePortfolioKpiStrip
										portfolio={selected}
										priceBuffer={sparklineBuffer}
									/>
								</aside>
							</section>
							<div class="lws-panel lws-panel--allocations">
								<LiveAllocationsTable portfolio={selected} />
							</div>
						</div>
					{:else if activeTool === "drift_analysis"}
						<div class="lws-panel lws-panel--drift">
							<WeightVectorTable
								{targetFunds}
								{actualHoldings}
								loading={holdingsLoading}
							/>
						</div>
					{:else if activeTool === "execution_desk"}
						<div class="lws-execution-grid">
							<div class="lws-panel lws-panel--exec-table">
								<WeightVectorTable
									{targetFunds}
									{actualHoldings}
									loading={holdingsLoading}
									compact
								/>
							</div>
							<div class="lws-panel lws-panel--exec-orders">
								<RebalanceSuggestionPanel
									portfolioId={selected.id}
									portfolioName={selected.display_name}
									{targetFunds}
									{actualHoldings}
									loading={holdingsLoading}
									onTradesExecuted={refreshHoldings}
									apiPost={api.post.bind(api)}
								/>
							</div>
						</div>
					{/if}
				{:else}
					<div class="lws-tool-placeholder">
						<EmptyState
							title="Select a portfolio"
							message="Pick a live portfolio from the left rail to activate the workbench tools."
						/>
					</div>
				{/if}
			{/snippet}
		</WorkbenchLayout>
	{/if}

	{#snippet failed(err: unknown, reset: () => void)}
		<PanelErrorState
			title="Live Workbench failed to render"
			message={err instanceof Error
				? err.message
				: "Unexpected error in the Live Workbench."}
			onRetry={reset}
		/>
	{/snippet}
</svelte:boundary>

<style>
	.lws-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 20px;
		height: 100%;
		padding: 48px 24px;
		background: var(--ii-bg, #0e0f13);
	}
	.lws-empty-actions {
		display: flex;
		gap: 12px;
	}

	/* Ultra-compact terminal header — 44px target including borders.
	   Three-region layout: title left, tool ribbon center, exit
	   button right. Overrides the WorkbenchLayout primitive's
	   default ``.wb-header`` padding via :global() so the shell
	   stays in control of its own density without touching the
	   shared @investintell/ui primitive. */
	:global(.terminal-root .wb-header) {
		padding: 0 14px;
		height: 44px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.1);
		background: #0e1320;
	}
	/* Override WorkbenchLayout primitive padding — the terminal
	   uses its own tight budget so the chart + KPI + footer trio
	   can claim the full viewport minus the 44px header. */
	:global(.terminal-root .wb-main) {
		padding: 12px;
		gap: 12px;
	}
	:global(.terminal-root .wb-sidebar) {
		background: #0e1320;
		border-right-color: rgba(255, 255, 255, 0.1);
	}

	.lws-term-header {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
		align-items: center;
		gap: 12px;
		width: 100%;
		min-width: 0;
		height: 100%;
	}

	.lws-term-title {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
		font-size: 12px;
		font-weight: 600;
		letter-spacing: 0.02em;
		color: var(--ii-text-primary, #ffffff);
	}
	.lws-term-name {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		min-width: 0;
	}
	.lws-term-name--muted {
		color: var(--ii-text-muted, #85a0bd);
		font-weight: 500;
	}
	.lws-term-sep {
		color: rgba(255, 255, 255, 0.2);
		flex-shrink: 0;
	}
	.lws-term-mode {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: #2d7ef7;
		flex-shrink: 0;
	}

	.lws-term-ribbon-slot {
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.lws-term-actions {
		display: flex;
		align-items: center;
		justify-content: flex-end;
	}
	.lws-term-exit {
		appearance: none;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 5px 10px;
		font-family: inherit;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: #85a0bd;
		background: transparent;
		border: 1px solid rgba(255, 255, 255, 0.12);
		border-radius: 2px;
		cursor: pointer;
		transition:
			color 120ms ease,
			border-color 120ms ease,
			background-color 120ms ease;
	}
	.lws-term-exit:hover {
		color: #ffffff;
		border-color: rgba(255, 255, 255, 0.3);
		background: rgba(255, 255, 255, 0.04);
	}
	.lws-term-exit:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: 2px;
	}
	.lws-term-exit-glyph {
		font-size: 12px;
		line-height: 1;
	}

	.lws-tool-placeholder {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 320px;
		background: var(--ii-surface, #141519);
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		border-radius: 8px;
		padding: 32px 24px;
	}

	/* Phase 9 Block C terminal density — cockpit-style panel geometry.
	   Vertical stack of overview → allocations with a tight gap,
	   inner grid for chart (left) + KPI rail (right 320px), every
	   macro-component encapsulated in an .lws-panel "module" with
	   the shared terminal palette. */
	.lws-overview-stack {
		display: flex;
		flex-direction: column;
		gap: 12px;
		min-width: 0;
	}
	.lws-overview-grid {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 320px;
		gap: 12px;
		align-items: stretch;
		min-width: 0;
	}

	/* Shared panel module — "caixa fechada" aesthetic. Reused by
	   the chart wrapper, the KPI rail, and the allocations wrap. */
	.lws-panel {
		background: #131722;
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 2px;
		min-width: 0;
		min-height: 0;
	}
	.lws-panel--chart {
		padding: 8px;
		display: flex;
		flex-direction: column;
	}
	.lws-panel--kpis {
		padding: 0;
		display: flex;
		flex-direction: column;
	}
	.lws-panel--allocations {
		padding: 0;
		overflow: hidden; /* clip rounded corners of inner scroll area */
		/* Terminal breakout: pin the allocations footer to a fixed
		   vertical budget so the chart + KPI rail can claim the
		   rest of the viewport. The footer scrolls internally. */
		max-height: 260px;
		display: flex;
		flex-direction: column;
	}

	/* Chart root override — strip WorkbenchCoreChart's own panel
	   chrome (background gradient, border, rounded, padding) so the
	   outer .lws-panel--chart is the sole visible module. Scoped
	   :global() so the WorkbenchCoreChart component file itself
	   stays untouched per the mandate. */
	.lws-panel--chart :global(.wcc-root) {
		background: transparent;
		border: none;
		border-radius: 0;
		padding: 0;
	}
	/* Allocations table root override — same pattern for the table
	   so the outer .lws-panel--allocations is the sole border, and
	   the table body scrolls inside the terminal-height budget. */
	.lws-panel--allocations :global(.lat-root) {
		background: transparent;
		border: none;
		border-radius: 0;
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	/* ── Drift Analysis panel — full-width table ──────────── */
	.lws-panel--drift {
		padding: 0;
		flex: 1;
		min-height: 0;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}

	/* ── Execution Desk — table center + orders rail ─────── */
	.lws-execution-grid {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 340px;
		gap: 12px;
		flex: 1;
		min-height: 0;
		align-items: stretch;
	}
	.lws-panel--exec-table {
		padding: 0;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}
	.lws-panel--exec-orders {
		padding: 0;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	/* Container query keyed on workbench-main — when the main area
	   is too narrow, collapse grids to a single column so the
	   secondary rail drops below. */
	@container workbench-main (max-width: 960px) {
		.lws-overview-grid {
			grid-template-columns: minmax(0, 1fr);
		}
		.lws-execution-grid {
			grid-template-columns: minmax(0, 1fr);
		}
	}

	/* ── @media print — Trade Sheet compliance output ─────────
	   When window.print() fires from the Execution Desk, produce
	   a clean A4 page: white background, black text, no terminal
	   chrome, no dark mode bleeding. Only the trade panel content
	   (with its own print-only header) hits paper.

	   Hide:  sidebar, header bar, overview stack, chart, KPIs,
	          allocations table, placeholders, empty states.
	   Show:  execution grid → orders panel only (table optional).
	   Force: white bg, auto height, no overflow clipping. */
	@media print {
		/* Kill terminal root dark bg */
		:global(.terminal-root) {
			position: static !important;
			width: auto !important;
			height: auto !important;
			overflow: visible !important;
			background: #fff !important;
		}
		:global(body) {
			overflow: visible !important;
			background: #fff !important;
		}

		/* Hide all non-printable chrome */
		:global(.wb-sidebar),
		:global(.wb-header) {
			display: none !important;
		}
		:global(.wb-main-area) {
			display: block !important;
			background: #fff !important;
		}
		:global(.wb-main) {
			padding: 0 !important;
			overflow: visible !important;
			height: auto !important;
			background: #fff !important;
		}

		/* Overview stack — hide entirely on print */
		.lws-overview-stack {
			display: none !important;
		}

		/* Tool placeholder — hide */
		.lws-tool-placeholder {
			display: none !important;
		}

		/* Drift table panel — hide (only orders panel prints) */
		.lws-panel--drift {
			display: none !important;
		}

		/* Execution grid — flatten to single column, orders only */
		.lws-execution-grid {
			display: block !important;
			background: #fff !important;
		}
		.lws-panel--exec-table {
			display: none !important;
		}
		.lws-panel--exec-orders {
			background: #fff !important;
			border: none !important;
			max-height: none !important;
			overflow: visible !important;
			height: auto !important;
		}

		/* All panels — strip terminal panel chrome on paper */
		.lws-panel {
			background: #fff !important;
			border: none !important;
			border-radius: 0 !important;
		}

		/* Empty state — hide */
		.lws-empty {
			display: none !important;
		}

		/* Page setup */
		@page {
			size: A4 portrait;
			margin: 20mm 15mm;
		}
	}
</style>
