<!--
  TerminalScreenerQuickStats — right panel showing selected asset detail.
  Ultra-dense KPI matrix when an asset is selected, placeholder otherwise.
-->
<script lang="ts">
	import type { MockAsset } from "./TerminalDataGrid.svelte";

	interface Props {
		asset: MockAsset | null;
	}

	let { asset }: Props = $props();

	function fmt(v: number, d: number = 2): string {
		return v.toFixed(d);
	}

	function fmtAum(v: number): string {
		if (v >= 1e9) return "$" + (v / 1e9).toFixed(2) + "B";
		if (v >= 1e6) return "$" + (v / 1e6).toFixed(0) + "M";
		return "$" + v.toFixed(0);
	}

	function retClass(v: number): string {
		if (v > 0) return "pos";
		if (v < 0) return "neg";
		return "";
	}

	interface KpiRow {
		label: string;
		value: string;
		colorClass?: string;
	}

	const kpis = $derived<KpiRow[]>(
		asset
			? [
					{ label: "1Y Return", value: fmt(asset.ret1y) + "%", colorClass: retClass(asset.ret1y) },
					{ label: "3Y Return", value: fmt(asset.ret3y) + "%", colorClass: retClass(asset.ret3y) },
					{ label: "Volatility", value: fmt(asset.volatility) + "%" },
					{ label: "Sharpe Ratio", value: fmt(asset.sharpe) },
					{ label: "Max Drawdown", value: fmt(asset.maxDrawdown) + "%", colorClass: "neg" },
					{ label: "Beta", value: fmt(asset.beta) },
					{ label: "Alpha", value: fmt(asset.alpha) + "%", colorClass: retClass(asset.alpha) },
					{ label: "AUM", value: fmtAum(asset.aum) },
					{ label: "Expense Ratio", value: fmt(asset.expenseRatio) + "%" },
					{ label: "Sector", value: asset.sector },
				]
			: [],
	);
</script>

<div class="qs-root">
	{#if asset}
		<div class="qs-header">
			<span class="qs-ticker">{asset.ticker}</span>
			<span class="qs-name">{asset.name}</span>
		</div>

		<div class="qs-badge">{asset.assetClass}</div>

		<div class="qs-grid">
			{#each kpis as kpi}
				<div class="qs-cell">
					<span class="qs-label">{kpi.label}</span>
					<span class="qs-value {kpi.colorClass ?? ''}">{kpi.value}</span>
				</div>
			{/each}
		</div>
	{:else}
		<div class="qs-empty">
			<span class="qs-empty-icon">&#9632;</span>
			<span class="qs-empty-text">Select an asset to view details</span>
		</div>
	{/if}
</div>

<style>
	.qs-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: #0c1018;
		border-left: 1px solid rgba(255, 255, 255, 0.06);
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		color: #c8d0dc;
		overflow-y: auto;
		overflow-x: hidden;
	}

	/* ── Header ─────────────────────────────────────── */
	.qs-header {
		padding: 12px 14px 4px;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.qs-ticker {
		font-size: 16px;
		font-weight: 800;
		color: #e2e8f0;
		letter-spacing: 0.04em;
	}

	.qs-name {
		font-size: 11px;
		color: #5a6577;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.qs-badge {
		margin: 6px 14px 8px;
		display: inline-block;
		width: fit-content;
		padding: 2px 8px;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: #2d7ef7;
		background: rgba(45, 126, 247, 0.08);
		border-radius: 3px;
	}

	/* ── KPI Grid (2 columns) ─────────────────────── */
	.qs-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1px;
		padding: 0 14px 14px;
	}

	.qs-cell {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: 8px 0;
		border-bottom: 1px solid rgba(255, 255, 255, 0.04);
	}

	.qs-label {
		font-size: 9px;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: #5a6577;
	}

	.qs-value {
		font-size: 13px;
		font-weight: 700;
		color: #e2e8f0;
		font-variant-numeric: tabular-nums;
	}

	.pos { color: #22c55e; }
	.neg { color: #ef4444; }

	/* ── Empty state ──────────────────────────────── */
	.qs-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 8px;
		height: 100%;
		color: #3a4455;
	}

	.qs-empty-icon {
		font-size: 24px;
		opacity: 0.3;
	}

	.qs-empty-text {
		font-size: 11px;
		letter-spacing: 0.04em;
	}
</style>
