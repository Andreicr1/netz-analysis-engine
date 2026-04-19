<!--
  TerminalResearchShell — 3-column research & risk desk.

  Grid topology:
    ┌──────────┬──────────────────────┬─────────────┐
    │          │                      │             │
    │  ASSET   │   CHART WORKSPACE    │  RISK KPIs  │
    │ BROWSER  │   (lightweight-      │             │
    │ (280px)  │     charts)          │   (320px)   │
    │          │       (1fr)          │             │
    └──────────┴──────────────────────┴─────────────┘

  The asset browser hits `/screener/catalog?in_universe=true` for
  real fund data (~9k funds with NAV history). Selection produces a
  `TreeNode` whose `instrumentId` is the global instruments_universe
  UUID — the Research chart uses it to fetch the risk timeseries
  (drawdown, GARCH vol, macro regime) straight from TimescaleDB.
-->
<script lang="ts">
	import TerminalAssetTree, { type TreeNode } from "./TerminalAssetTree.svelte";
	import TerminalResearchChart from "./TerminalResearchChart.svelte";
	import TerminalHoldingsGrid from "./TerminalHoldingsGrid.svelte";
	import TerminalRiskKpis from "./TerminalRiskKpis.svelte";
	import LibraryWrapper from "./LibraryWrapper.svelte";
	import ReportsPanel from "./ReportsPanel.svelte";

	// ── Top-level view tab ────────────────────────────
	type ViewTab = "ANALYTICS" | "LIBRARY" | "REPORTS";
	let activeView = $state<ViewTab>("ANALYTICS");

	// ── Analytics selection state ─────────────────────
	let selectedNode = $state<TreeNode | null>(null);
	let activeTab = $state<"CHART" | "HOLDINGS">("CHART");

	const selectedId = $derived(selectedNode?.id ?? null);

	const chartTicker = $derived(selectedNode?.ticker ?? "—");
	const chartLabel = $derived(selectedNode?.label ?? "Select a fund from the browser");
	const chartInstrumentId = $derived(selectedNode?.instrumentId ?? null);

	function handleSelect(node: TreeNode) {
		selectedNode = node;
	}
</script>

<div class="tr-shell">
	<!-- Top-level view tab bar -->
	<div class="tr-view-bar">
		{#each (["ANALYTICS", "LIBRARY", "REPORTS"] as ViewTab[]) as tab (tab)}
			<button
				class="tr-view-tab {activeView === tab ? 'tr-view-tab-active' : ''}"
				onclick={() => activeView = tab}
			>
				{tab}
			</button>
		{/each}
	</div>

	<!-- View content -->
	<div class="tr-view-content">
		{#if activeView === "ANALYTICS"}
			<div class="tr-root">
				<div class="tr-zone tr-tree" aria-label="Asset browser">
					<TerminalAssetTree {selectedId} onSelect={handleSelect} />
				</div>
				<div class="tr-zone tr-chart" aria-label="Chart workspace">
					<div class="tr-panel-header">
						<button
							class="tr-tab {activeTab === 'CHART' ? 'tr-tab-active' : ''}"
							onclick={() => activeTab = 'CHART'}
						>
							CHART
						</button>
						<button
							class="tr-tab {activeTab === 'HOLDINGS' ? 'tr-tab-active' : ''}"
							onclick={() => activeTab = 'HOLDINGS'}
						>
							HOLDINGS
						</button>
					</div>
					<div class="tr-panel-content">
						{#if activeTab === 'CHART'}
							<TerminalResearchChart
								ticker={chartTicker}
								tickerLabel={chartLabel}
								instrumentId={chartInstrumentId}
							/>
						{:else}
							<TerminalHoldingsGrid ticker={chartTicker} />
						{/if}
					</div>
				</div>
				<div class="tr-zone tr-kpis" aria-label="Risk KPIs">
					<TerminalRiskKpis {selectedNode} />
				</div>
			</div>
		{:else if activeView === "LIBRARY"}
			<LibraryWrapper />
		{:else}
			<ReportsPanel />
		{/if}
	</div>
</div>

<style>
	.tr-shell {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		overflow: hidden;
		background: var(--terminal-bg-void);
		font-family: var(--terminal-font-mono);
	}

	/* ── View tab bar ── */
	.tr-view-bar {
		display: flex;
		align-items: flex-end;
		gap: 20px;
		padding: 0 16px;
		height: 30px;
		flex-shrink: 0;
		border-bottom: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
	}

	.tr-view-tab {
		height: 100%;
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: 0.08em;
		color: var(--terminal-fg-tertiary);
		background: transparent;
		border: none;
		border-bottom: 2px solid transparent;
		padding: 0 2px;
		cursor: pointer;
		outline: none;
		font-family: var(--terminal-font-mono);
		transition: color 120ms ease;
	}

	.tr-view-tab:hover {
		color: var(--terminal-fg-secondary);
	}

	.tr-view-tab-active {
		color: var(--terminal-fg-primary);
		border-bottom-color: var(--terminal-accent-cyan);
	}

	.tr-view-content {
		flex: 1;
		min-height: 0;
		overflow: hidden;
	}

	/* ── Analytics grid ── */
	.tr-root {
		display: grid;
		grid-template-areas: "tree chart kpis";
		grid-template-columns: 280px 1fr 320px;
		grid-template-rows: 100%;
		gap: 2px;
		width: 100%;
		height: 100%;
		overflow: hidden;
		background: var(--terminal-bg-void);
		font-family: var(--terminal-font-mono);
	}

	.tr-zone {
		min-width: 0;
		min-height: 0;
		overflow: hidden;
	}

	.tr-tree { grid-area: tree; }
	.tr-chart {
		grid-area: chart;
		display: flex;
		flex-direction: column;
	}
	.tr-kpis { grid-area: kpis; }

	.tr-panel-header {
		height: 32px;
		flex-shrink: 0;
		display: flex;
		align-items: flex-end;
		border-bottom: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
		padding: 0 8px;
		gap: 16px;
	}

	.tr-tab {
		height: 100%;
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: 0.05em;
		color: var(--terminal-fg-tertiary);
		background: transparent;
		border: none;
		border-bottom: 2px solid transparent;
		padding: 0 4px;
		cursor: pointer;
		outline: none;
		font-family: var(--terminal-font-mono);
	}

	.tr-tab:hover {
		color: var(--terminal-fg-secondary);
	}

	.tr-tab-active {
		color: var(--terminal-fg-primary);
		border-bottom-color: var(--terminal-accent-cyan);
	}

	.tr-panel-content {
		flex: 1;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
	}
</style>
