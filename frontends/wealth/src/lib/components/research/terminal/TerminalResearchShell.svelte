<!--
  TerminalResearchShell — 3-column research & risk desk.

  Grid topology:
    ┌──────────┬──────────────────────┬─────────────┐
    │          │                      │             │
    │  ASSET   │   CHART WORKSPACE    │  RISK KPIs  │
    │  TREE    │     (TradingView)    │             │
    │ (280px)  │       (1fr)          │   (320px)   │
    │          │                      │             │
    └──────────┴──────────────────────┴─────────────┘
-->
<script lang="ts">
	import TerminalAssetTree, { type TreeNode } from "./TerminalAssetTree.svelte";
	import TerminalResearchChart from "./TerminalResearchChart.svelte";
	import TerminalHoldingsGrid from "./TerminalHoldingsGrid.svelte";
	import TerminalRiskKpis from "./TerminalRiskKpis.svelte";

	// ── Mock portfolio tree ───────────────────────────
	const TREE: TreeNode[] = [
		{
			id: "root",
			label: "Portfolio Root",
			type: "root",
			children: [
				{
					id: "equities",
					label: "Equities",
					type: "class",
					children: [
						{ id: "f-vfiax", label: "Vanguard 500 Index", ticker: "VFIAX", type: "fund" },
						{ id: "f-fcntx", label: "Fidelity Contrafund", ticker: "FCNTX", type: "fund" },
						{ id: "f-trbcx", label: "T. Rowe Blue Chip Growth", ticker: "TRBCX", type: "fund" },
						{ id: "f-gqetx", label: "GMO Quality Fund", ticker: "GQETX", type: "fund" },
						{ id: "f-vpccx", label: "Vanguard PRIMECAP Core", ticker: "VPCCX", type: "fund" },
						{ id: "f-dodfx", label: "Dodge & Cox Intl Stock", ticker: "DODFX", type: "fund" },
						{ id: "f-vemmx", label: "Vanguard Emerging Markets", ticker: "VEMMX", type: "fund" },
					],
				},
				{
					id: "fixed-income",
					label: "Fixed Income",
					type: "class",
					children: [
						{ id: "f-pimix", label: "PIMCO Income Fund", ticker: "PIMIX", type: "fund" },
						{ id: "f-vbtlx", label: "Vanguard Total Bond Mkt", ticker: "VBTLX", type: "fund" },
						{ id: "f-pttrx", label: "PIMCO Total Return", ticker: "PTTRX", type: "fund" },
						{ id: "f-mwtrx", label: "MetWest Total Return Bd", ticker: "MWTRX", type: "fund" },
						{ id: "f-vipsx", label: "Vanguard Inflation-Prot", ticker: "VIPSX", type: "fund" },
					],
				},
				{
					id: "alternatives",
					label: "Alternatives",
					type: "class",
					children: [
						{ id: "f-vgslx", label: "Vanguard Real Estate Idx", ticker: "VGSLX", type: "fund" },
						{ id: "f-bcoix", label: "BlackRock Commodity", ticker: "BCOIX", type: "fund" },
					],
				},
				{
					id: "multi-asset",
					label: "Multi-Asset",
					type: "class",
					children: [
						{ id: "f-vwelx", label: "Vanguard Wellington", ticker: "VWELX", type: "fund" },
						{ id: "f-prwcx", label: "T. Rowe Capital Apprec", ticker: "PRWCX", type: "fund" },
						{ id: "f-fbalx", label: "Fidelity Balanced Fund", ticker: "FBALX", type: "fund" },
					],
				},
			],
		},
	];

	// ── Selection state ───────────────────────────────
	let selectedId = $state<string | null>(null);
	let activeTab = $state<"CHART" | "HOLDINGS">("CHART");

	function findNode(nodes: TreeNode[], id: string): TreeNode | null {
		for (const n of nodes) {
			if (n.id === id) return n;
			if (n.children) {
				const found = findNode(n.children, id);
				if (found) return found;
			}
		}
		return null;
	}

	const selectedNode = $derived<TreeNode | null>(
		selectedId ? findNode(TREE, selectedId) : null,
	);

	// Resolve the chart ticker — fund nodes have a ticker, class/root show "PORTFOLIO"
	const chartTicker = $derived(
		selectedNode?.ticker ?? "PORTFOLIO",
	);

	const chartLabel = $derived(
		selectedNode?.label ?? "Select an asset from the tree",
	);

	function handleSelect(node: TreeNode) {
		selectedId = node.id;
	}
</script>

<div class="tr-root">
	<div class="tr-zone tr-tree" aria-label="Asset tree">
		<TerminalAssetTree tree={TREE} {selectedId} onSelect={handleSelect} />
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
				<TerminalResearchChart ticker={chartTicker} tickerLabel={chartLabel} />
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
		background: #000000;
		font-family: "Urbanist", system-ui, sans-serif;
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
		border-bottom: 1px solid rgba(255, 255, 255, 0.08);
		background: #05080f;
		padding: 0 8px;
		gap: 16px;
	}

	.tr-tab {
		height: 100%;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.05em;
		color: #64748b;
		background: transparent;
		border: none;
		border-bottom: 2px solid transparent;
		padding: 0 4px;
		cursor: pointer;
		outline: none;
	}

	.tr-tab:hover {
		color: #cbd5e1;
	}

	.tr-tab-active {
		color: #ffffff;
		border-bottom-color: #2d7ef7;
	}

	.tr-panel-content {
		flex: 1;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
	}
</style>
