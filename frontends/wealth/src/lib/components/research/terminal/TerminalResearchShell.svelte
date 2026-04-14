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

	// ── Selection state ───────────────────────────────
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

<style>
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
