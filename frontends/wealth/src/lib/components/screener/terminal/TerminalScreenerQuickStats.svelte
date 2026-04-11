<!--
  TerminalScreenerQuickStats — right panel showing selected asset detail.
  Ultra-dense KPI matrix driven by `/screener/catalog` rows.
-->
<script lang="ts">
	import { formatNumber } from "@investintell/ui";
	import type { ScreenerAsset } from "./TerminalDataGrid.svelte";

	interface Props {
		asset: ScreenerAsset | null;
	}

	let { asset }: Props = $props();

	function fmtPct(v: number | null, d: number = 2): string {
		if (v == null) return "—";
		return formatNumber(v, d) + "%";
	}

	function fmtNum(v: number | null, d: number = 2): string {
		if (v == null) return "—";
		return formatNumber(v, d);
	}

	function fmtAum(v: number | null): string {
		if (v == null || v <= 0) return "—";
		if (v >= 1e12) return "$" + formatNumber(v / 1e12, 2) + "T";
		if (v >= 1e9) return "$" + formatNumber(v / 1e9, 2) + "B";
		if (v >= 1e6) return "$" + formatNumber(v / 1e6, 0) + "M";
		return "$" + formatNumber(v, 0);
	}

	function retClass(v: number | null): string {
		if (v == null) return "";
		if (v > 0) return "pos";
		if (v < 0) return "neg";
		return "";
	}

	function orDash(v: string | null | undefined): string {
		return v && v.length > 0 ? v : "—";
	}

	interface KpiRow {
		label: string;
		value: string;
		colorClass?: string;
	}

	const kpis = $derived<KpiRow[]>(
		asset
			? [
					{ label: "1Y Return", value: fmtPct(asset.ret1y), colorClass: retClass(asset.ret1y) },
					{ label: "10Y Return", value: fmtPct(asset.ret10y), colorClass: retClass(asset.ret10y) },
					{ label: "AUM", value: fmtAum(asset.aum) },
					{ label: "Expense Ratio", value: fmtNum(asset.expenseRatioPct) + "%" },
					{ label: "Strategy", value: orDash(asset.strategy) },
					{ label: "Geography", value: orDash(asset.geography) },
					{ label: "Domicile", value: orDash(asset.domicile) },
					{ label: "Currency", value: orDash(asset.currency) },
					{ label: "Inception", value: orDash(asset.inceptionDate) },
					{ label: "ISIN", value: orDash(asset.isin) },
				]
			: [],
	);
</script>

<div class="qs-root">
	{#if asset}
		<div class="qs-header">
			<span class="qs-ticker">{asset.ticker ?? asset.isin ?? "—"}</span>
			<span class="qs-name">{asset.name}</span>
			{#if asset.managerName}
				<span class="qs-manager">{asset.managerName}</span>
			{/if}
		</div>

		<div class="qs-badge">{asset.universeLabel}</div>

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
		color: #9aa3b3;
		white-space: normal;
		word-wrap: break-word;
		line-height: 1.35;
	}

	.qs-manager {
		margin-top: 2px;
		font-size: 10px;
		color: #5a6577;
		font-style: italic;
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
