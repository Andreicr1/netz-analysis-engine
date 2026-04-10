<!--
  TerminalDataGrid — high-density scrollable data table.
  Sticky header, strings left, numbers right (tabular-nums).
  Zebra-striping at near-invisible opacity for scanability.
-->
<script lang="ts">
	import { sandboxBasket } from "$lib/stores/sandbox.svelte";

	export interface MockAsset {
		id: string;
		ticker: string;
		name: string;
		assetClass: string;
		sector: string;
		ret1y: number;
		ret3y: number;
		volatility: number;
		sharpe: number;
		maxDrawdown: number;
		beta: number;
		alpha: number;
		aum: number;
		expenseRatio: number;
		managerScore?: number;
		dtwDriftScore?: number | null;
	}

	interface Props {
		assets: MockAsset[];
		selectedId: string | null;
		onSelect: (asset: MockAsset) => void;
	}

	let { assets, selectedId, onSelect }: Props = $props();

	function fmt(v: number, decimals: number = 2): string {
		return v.toFixed(decimals);
	}

	function fmtAum(v: number): string {
		if (v >= 1e9) return (v / 1e9).toFixed(1) + "B";
		if (v >= 1e6) return (v / 1e6).toFixed(0) + "M";
		return v.toFixed(0);
	}

	function retClass(v: number): string {
		if (v > 0) return "pos";
		if (v < 0) return "neg";
		return "";
	}

	type DriftTag = { label: string; cssClass: string };

	const driftTag = $derived.by((): Map<string, DriftTag> => {
		const map = new Map<string, DriftTag>();
		for (const a of assets) {
			const score = a.dtwDriftScore;
			if (score == null) {
				map.set(a.id, { label: "-", cssClass: "drift-none" });
			} else if (score > 0.90) {
				map.set(a.id, { label: "[ CRITICAL DRIFT ]", cssClass: "drift-critical" });
			} else if (score > 0.40) {
				map.set(a.id, { label: "[ WARN: DRIFT ]", cssClass: "drift-warn" });
			} else {
				map.set(a.id, { label: fmt(score), cssClass: "drift-ok" });
			}
		}
		return map;
	});
</script>

<div class="dg-root">
	<div class="dg-scroll">
		<table class="dg-table">
			<thead>
				<tr>
					<th class="dg-th dg-left">Ticker</th>
					<th class="dg-th dg-left dg-name-col">Name</th>
					<th class="dg-th dg-left">Class</th>
					<th class="dg-th dg-center">Score</th>
					<th class="dg-th dg-center">Style Drift</th>
					<th class="dg-th dg-right">1Y Ret</th>
					<th class="dg-th dg-right">3Y Ret</th>
					<th class="dg-th dg-right">Vol</th>
					<th class="dg-th dg-right">Sharpe</th>
				</tr>
			</thead>
			<tbody>
				{#each assets as asset, i (asset.id)}
					<tr
						class="dg-row"
						class:selected={selectedId === asset.id}
						class:zebra={i % 2 === 1}
						onclick={() => onSelect(asset)}
					>
						<td class="dg-td dg-left dg-ticker">{asset.ticker}</td>
						<td class="dg-td dg-left dg-name-col dg-name">{asset.name}</td>
						<td class="dg-td dg-left dg-class">{asset.assetClass}</td>
						<td class="dg-td dg-center">
							{#if asset.managerScore !== undefined}
								{#if asset.managerScore >= 75}
									<span class="dg-badge elite">[ ELITE ]</span>
								{:else if asset.managerScore < 40}
									<span class="dg-badge eviction">[ EVICTION ]</span>
								{:else}
									<span class="dg-num score-num">{fmt(asset.managerScore, 1)}</span>
								{/if}
							{:else}
								<span class="dg-num">-</span>
							{/if}
						</td>
						<td class="dg-td dg-center">
							{#if driftTag.get(asset.id)}
								<span class="dg-badge {driftTag.get(asset.id)?.cssClass}">{driftTag.get(asset.id)?.label}</span>
							{/if}
						</td>
						<td class="dg-td dg-right dg-num {retClass(asset.ret1y)}">{fmt(asset.ret1y)}%</td>
						<td class="dg-td dg-right dg-num {retClass(asset.ret3y)}">{fmt(asset.ret3y)}%</td>
						<td class="dg-td dg-right dg-num">{fmt(asset.volatility)}%</td>
						<td class="dg-td dg-right dg-num">{fmt(asset.sharpe)}</td>
						<td class="dg-td dg-center">
							<button
								class="sandbox-add-btn"
								onclick={(e) => {
									e.stopPropagation();
									if (!sandboxBasket.some(a => a.instrument_id === asset.id)) {
										sandboxBasket.push({ instrument_id: asset.id, ticker: asset.ticker });
									}
								}}
							>
								[ + SANDBOX ]
							</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
	<div class="dg-footer">
		<span>{assets.length} instruments</span>
	</div>
</div>

<style>
	.dg-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: #0b0f1a;
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		color: #c8d0dc;
	}

	.dg-scroll {
		flex: 1;
		overflow-y: auto;
		overflow-x: auto;
		min-height: 0;
	}

	.dg-table {
		width: 100%;
		border-collapse: collapse;
		table-layout: fixed;
	}

	/* ── Header ───────────────────────────────────────── */
	thead {
		position: sticky;
		top: 0;
		z-index: 2;
	}

	.dg-th {
		padding: 6px 10px;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: #5a6577;
		background: #0d1220;
		border-bottom: 1px solid rgba(255, 255, 255, 0.08);
		white-space: nowrap;
		user-select: none;
	}

	/* ── Rows ─────────────────────────────────────────── */
	.dg-row {
		cursor: pointer;
		transition: background 80ms ease;
	}
	.dg-row:hover {
		background: rgba(45, 126, 247, 0.06);
	}
	.dg-row.selected {
		background: rgba(45, 126, 247, 0.10);
	}
	.dg-row.zebra {
		background: rgba(255, 255, 255, 0.012);
	}
	.dg-row.zebra:hover {
		background: rgba(45, 126, 247, 0.06);
	}
	.dg-row.zebra.selected {
		background: rgba(45, 126, 247, 0.10);
	}

	/* ── Cells ────────────────────────────────────────── */
	.dg-td {
		padding: 5px 10px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.03);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.dg-left { text-align: left; }
	.dg-right { text-align: right; }
	.dg-center { text-align: center; }

	.dg-ticker {
		font-weight: 700;
		color: #e2e8f0;
		width: 70px;
	}

	.dg-name-col {
		width: 200px;
		min-width: 120px;
	}

	.dg-name {
		color: #9aa3b3;
	}

	.dg-class {
		color: #5a6577;
		font-size: 10px;
		width: 80px;
	}

	.dg-num {
		font-variant-numeric: tabular-nums;
		font-weight: 500;
	}

	.score-num {
		color: #e2e8f0;
	}

	.dg-badge {
		font-family: monospace;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.05em;
	}

	.elite {
		color: #2d7ef7;
	}

	.eviction {
		color: #ca8a04;
	}

	.drift-critical {
		color: #ef4444;
		font-family: monospace;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.05em;
	}

	.drift-warn {
		color: #ca8a04;
		font-family: monospace;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.05em;
	}

	.drift-ok {
		color: #5a6577;
		font-variant-numeric: tabular-nums;
	}

	.drift-none {
		color: #3a4255;
	}

	.pos { color: #22c55e; }
	.neg { color: #ef4444; }

	/* ── Footer ───────────────────────────────────────── */
	.dg-footer {
		flex-shrink: 0;
		padding: 4px 10px;
		font-size: 10px;
		color: #5a6577;
		border-top: 1px solid rgba(255, 255, 255, 0.06);
		background: #0d1220;
	}
</style>
