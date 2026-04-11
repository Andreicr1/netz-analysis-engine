<!--
  TerminalDataGrid — high-density scrollable catalog grid.
  Real instrument data from `/screener/catalog`. Sticky header, strings
  left, numbers right (tabular-nums). Zebra-striping at near-invisible
  opacity for scanability.
-->
<script module lang="ts">
	export interface ScreenerAsset {
		id: string;                 // external_id from /screener/catalog
		/**
		 * Global instruments_universe UUID. Populated by the backend via
		 * ticker/ISIN lookup when the fund has NAV history; null for
		 * rows not yet imported into instruments_universe.
		 */
		instrumentId: string | null;
		ticker: string | null;
		name: string;
		fundType: string;           // raw fund_type key
		universeLabel: string;      // pretty label for fund_type
		strategy: string | null;    // strategy_label
		geography: string | null;   // investment_geography
		domicile: string | null;
		currency: string | null;
		managerName: string | null;
		managerId: string | null;
		aum: number | null;
		expenseRatioPct: number | null;
		ret1y: number | null;
		ret10y: number | null;
		inceptionDate: string | null;
		isin: string | null;
		navStatus: string | null;   // available | pending_import | unavailable | null
	}
</script>

<script lang="ts">
	import { formatNumber } from "@investintell/ui";
	import { sandboxBasket } from "$lib/stores/sandbox.svelte";

	interface Props {
		assets: ScreenerAsset[];
		total: number;
		loading: boolean;
		errorMessage: string | null;
		selectedId: string | null;
		onSelect: (asset: ScreenerAsset) => void;
		onOpenWarRoom?: (fundId: string) => void;
	}

	let {
		assets,
		total,
		loading,
		errorMessage,
		selectedId,
		onSelect,
		onOpenWarRoom,
	}: Props = $props();

	function fmtPct(v: number | null, decimals: number = 2): string {
		if (v == null) return "—";
		return formatNumber(v, decimals) + "%";
	}

	function fmtNum(v: number | null, decimals: number = 2): string {
		if (v == null) return "—";
		return formatNumber(v, decimals);
	}

	function fmtAum(v: number | null): string {
		if (v == null || v <= 0) return "—";
		if (v >= 1e12) return formatNumber(v / 1e12, 2) + "T";
		if (v >= 1e9) return formatNumber(v / 1e9, 1) + "B";
		if (v >= 1e6) return formatNumber(v / 1e6, 0) + "M";
		return formatNumber(v, 0);
	}

	function retClass(v: number | null): string {
		if (v == null) return "";
		if (v > 0) return "pos";
		if (v < 0) return "neg";
		return "";
	}
</script>

<div class="dg-root">
	<div class="dg-scroll">
		<table class="dg-table">
			<thead>
				<tr>
					<th class="dg-th dg-left">Ticker</th>
					<th class="dg-th dg-left dg-name-col">Name</th>
					<th class="dg-th dg-left">Universe</th>
					<th class="dg-th dg-left dg-strategy-col">Strategy</th>
					<th class="dg-th dg-left">Geo</th>
					<th class="dg-th dg-right">AUM</th>
					<th class="dg-th dg-right">1Y Ret</th>
					<th class="dg-th dg-right">10Y Ret</th>
					<th class="dg-th dg-right">ER%</th>
					<th class="dg-th dg-center"></th>
				</tr>
			</thead>
			<tbody>
				{#each assets as asset, i (asset.id)}
					<tr
						class="dg-row"
						class:selected={selectedId === asset.id}
						class:zebra={i % 2 === 1}
						onclick={() => {
							onSelect(asset);
							onOpenWarRoom?.(asset.id);
						}}
					>
						<td class="dg-td dg-left dg-ticker" title={asset.ticker ?? asset.isin ?? ""}>
							{asset.ticker ?? asset.isin ?? "—"}
						</td>
						<td class="dg-td dg-left dg-name-col dg-name" title={asset.name}>{asset.name}</td>
						<td class="dg-td dg-left dg-class">{asset.universeLabel}</td>
						<td class="dg-td dg-left dg-strategy-col dg-strategy" title={asset.strategy ?? ""}>
							{asset.strategy ?? "—"}
						</td>
						<td class="dg-td dg-left dg-geo">{asset.geography ?? "—"}</td>
						<td class="dg-td dg-right dg-num">{fmtAum(asset.aum)}</td>
						<td class="dg-td dg-right dg-num {retClass(asset.ret1y)}">{fmtPct(asset.ret1y)}</td>
						<td class="dg-td dg-right dg-num {retClass(asset.ret10y)}">{fmtPct(asset.ret10y)}</td>
						<td class="dg-td dg-right dg-num">{fmtNum(asset.expenseRatioPct)}</td>
						<td class="dg-td dg-center">
							<button
								class="sandbox-add-btn"
								onclick={(e) => {
									e.stopPropagation();
									if (!sandboxBasket.some((a) => a.instrument_id === asset.id)) {
										sandboxBasket.push({ instrument_id: asset.id, ticker: asset.ticker ?? asset.id });
									}
								}}
							>
								[ + SANDBOX ]
							</button>
						</td>
					</tr>
				{/each}

				{#if assets.length === 0 && !loading && !errorMessage}
					<tr>
						<td class="dg-empty" colspan="10">No instruments match the current filters.</td>
					</tr>
				{/if}
			</tbody>
		</table>
	</div>

	<div class="dg-footer">
		{#if errorMessage}
			<span class="dg-footer-err">{errorMessage}</span>
		{:else if loading}
			<span>Loading&hellip;</span>
		{:else}
			<span>
				Showing {assets.length} of {formatNumber(total, 0)} instruments
			</span>
		{/if}
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
		width: 80px;
	}

	.dg-name-col {
		width: auto;
		min-width: 160px;
	}

	.dg-name {
		color: #9aa3b3;
	}

	.dg-class {
		color: #5a6577;
		font-size: 10px;
		width: 90px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.dg-strategy-col {
		width: 150px;
	}

	.dg-strategy {
		color: #8a94a6;
		font-size: 10px;
	}

	.dg-geo {
		color: #5a6577;
		font-size: 10px;
		width: 80px;
	}

	.dg-num {
		font-variant-numeric: tabular-nums;
		font-weight: 500;
		width: 72px;
	}

	.pos { color: #22c55e; }
	.neg { color: #ef4444; }

	.dg-empty {
		padding: 32px;
		text-align: center;
		color: #5a6577;
		font-size: 11px;
		font-style: italic;
	}

	/* ── Sandbox add button ───────────────────────────── */
	.sandbox-add-btn {
		background: transparent;
		border: 1px solid rgba(45, 126, 247, 0.25);
		color: #2d7ef7;
		font-family: "JetBrains Mono", monospace;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.04em;
		padding: 2px 6px;
		cursor: pointer;
		transition: all 80ms ease;
	}
	.sandbox-add-btn:hover {
		background: rgba(45, 126, 247, 0.08);
		color: #93bbfc;
	}

	/* ── Footer ───────────────────────────────────────── */
	.dg-footer {
		flex-shrink: 0;
		padding: 4px 10px;
		font-size: 10px;
		color: #5a6577;
		border-top: 1px solid rgba(255, 255, 255, 0.06);
		background: #0d1220;
	}
	.dg-footer-err {
		color: #ef4444;
	}
</style>
