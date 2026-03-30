<!--
  Asset Universe — approved instruments only (post DD-approval).
  Master/Detail: results table + ContextPanel with risk/scoring data.
  No ESMA/OFR tabs — this view looks only at internal bank data.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import {
		PageHeader, ContextPanel, StatusBadge, EmptyState,
		formatDateTime, formatNumber, formatPercent, formatCurrency,
	} from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { UniverseAsset, InstrumentRiskMetrics } from "$lib/types/universe";
	import { instrumentTypeLabel, instrumentTypeColor } from "$lib/types/universe";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let assets = $derived((data.assets ?? []) as UniverseAsset[]);

	// ── Search filter ─────────────────────────────────────────────────────

	let search = $state("");
	let blockFilter = $state<string | null>(null);
	let typeFilter = $state<string | null>(null);

	let distinctBlocks = $derived(
		[...new Set(assets.map((a) => a.block_id).filter(Boolean))] as string[]
	);
	let distinctTypes = $derived(
		[...new Set(assets.map((a) => a.instrument_type).filter(Boolean))] as string[]
	);

	let filtered = $derived.by(() => {
		let rows = assets;
		if (blockFilter) {
			rows = rows.filter((a) => a.block_id === blockFilter);
		}
		if (typeFilter) {
			rows = rows.filter((a) => a.instrument_type === typeFilter);
		}
		if (search) {
			const q = search.toLowerCase();
			rows = rows.filter((a) =>
				a.fund_name?.toLowerCase().includes(q) ||
				a.block_id?.toLowerCase().includes(q) ||
				a.geography?.toLowerCase().includes(q) ||
				a.asset_class?.toLowerCase().includes(q)
			);
		}
		return rows;
	});

	// ── Detail panel ──────────────────────────────────────────────────────

	let panelOpen = $state(false);
	let selectedAsset = $state<UniverseAsset | null>(null);
	let riskMetrics = $state<InstrumentRiskMetrics | null>(null);
	let loadingRisk = $state(false);

	async function openDetail(asset: UniverseAsset) {
		selectedAsset = asset;
		panelOpen = true;
		riskMetrics = null;
		loadingRisk = true;
		try {
			const api = createClientApiClient(getToken);
			riskMetrics = await api.get<InstrumentRiskMetrics>(`/funds/${asset.instrument_id}/risk`);
		} catch {
			riskMetrics = null;
		} finally {
			loadingRisk = false;
		}
	}

	function closeDetail() {
		panelOpen = false;
		selectedAsset = null;
		riskMetrics = null;
	}

	// ── Helpers ───────────────────────────────────────────────────────────
	// Backend may return Decimal fields as strings — always coerce to number.

	function toNum(v: unknown): number | null {
		if (v === null || v === undefined) return null;
		const n = Number(v);
		return isNaN(n) ? null : n;
	}

	function riskValue(v: unknown): string {
		const n = toNum(v);
		if (n === null) return "—";
		return formatPercent(n);
	}

	function ratioValue(v: unknown): string {
		const n = toNum(v);
		if (n === null) return "—";
		return n.toFixed(2);
	}

	function scoreValue(v: unknown): string {
		const n = toNum(v);
		if (n === null) return "—";
		return n.toFixed(1);
	}

	function scoreColor(v: unknown): string {
		const n = toNum(v);
		if (n === null) return "var(--ii-text-muted)";
		if (n >= 70) return "var(--ii-success)";
		if (n >= 40) return "var(--ii-warning)";
		return "var(--ii-danger)";
	}

	function momentumLabel(v: unknown): string {
		const n = toNum(v);
		if (n === null) return "—";
		if (n >= 60) return "Bullish";
		if (n >= 40) return "Neutral";
		return "Bearish";
	}

	function momentumColor(v: unknown): string {
		const n = toNum(v);
		if (n === null) return "var(--ii-text-muted)";
		if (n >= 60) return "var(--ii-success)";
		if (n >= 40) return "var(--ii-text-secondary)";
		return "var(--ii-danger)";
	}
</script>

<PageHeader title="Asset Universe" />

<div class="universe-page">
	<!-- Filters bar -->
	<div class="universe-toolbar">
		<input
			type="text"
			class="universe-search"
			placeholder="Search by name, block, geography…"
			bind:value={search}
		/>
		<select class="universe-select" bind:value={typeFilter}>
			<option value={null}>All types</option>
			{#each distinctTypes as t (t)}
				<option value={t}>{instrumentTypeLabel(t)}</option>
			{/each}
		</select>
		<select class="universe-select" bind:value={blockFilter}>
			<option value={null}>All blocks</option>
			{#each distinctBlocks as b (b)}
				<option value={b}>{b}</option>
			{/each}
		</select>
		<span class="universe-count">
			{filtered.length} asset{filtered.length !== 1 ? "s" : ""}
		</span>
	</div>

	<!-- Master table -->
	{#if filtered.length === 0}
		<EmptyState
			title={assets.length === 0 ? "No approved assets" : "No results"}
			message={assets.length === 0
				? "Instruments enter the universe after DD Report approval."
				: "No assets match current filters."
			}
		/>
	{:else}
		<div class="table-wrap">
			<table class="universe-table">
				<thead>
					<tr>
						<th class="th-name">Instrument</th>
						<th class="th-type">Type</th>
						<th class="th-block">Block</th>
						<th class="th-geo">Geography</th>
						<th class="th-class">Asset Class</th>
						<th class="th-decision">Decision</th>
						<th class="th-date">Approved</th>
					</tr>
				</thead>
				<tbody>
					{#each filtered as asset (asset.instrument_id)}
						<tr
							class="universe-row"
							class:selected={selectedAsset?.instrument_id === asset.instrument_id}
							onclick={() => openDetail(asset)}
						>
							<td class="td-name">{asset.fund_name ?? "—"}</td>
							<td class="td-type">
								<span class="type-badge" style:color={instrumentTypeColor(asset.instrument_type)} style:background="color-mix(in srgb, {instrumentTypeColor(asset.instrument_type)} 12%, transparent)">
									{instrumentTypeLabel(asset.instrument_type)}
								</span>
							</td>
							<td class="td-block">{asset.block_id ?? "—"}</td>
							<td class="td-geo">{asset.geography ?? "—"}</td>
							<td class="td-class">{asset.asset_class ?? "—"}</td>
							<td class="td-decision">
								{#if asset.approval_decision}
									<StatusBadge status={asset.approval_decision} />
								{:else}
									<span>—</span>
								{/if}
							</td>
							<td class="td-date">
								{asset.approved_at ? formatDateTime(asset.approved_at) : "—"}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- DETAIL PANEL — risk metrics + scoring cross-referenced with approval   -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
<ContextPanel open={panelOpen} onClose={closeDetail} title={selectedAsset?.fund_name ?? ""}>
	<svelte:boundary onerror={(e) => console.error("Universe detail panel error:", e)}>
	{#if selectedAsset}
		<div class="detail">
			<!-- Approval info -->
			<section class="detail-section">
				<h4 class="detail-section-title">Approval</h4>
				<div class="detail-grid">
					<div class="detail-kv">
						<span class="detail-k">Decision</span>
						{#if selectedAsset.approval_decision}
							<StatusBadge status={selectedAsset.approval_decision} />
						{:else}
							<span class="detail-v">—</span>
						{/if}
					</div>
					<div class="detail-kv">
						<span class="detail-k">Status</span>
						<span class="detail-v">{selectedAsset.approval_status ?? "—"}</span>
					</div>
					<div class="detail-kv">
						<span class="detail-k">Approved</span>
						<span class="detail-v">{selectedAsset.approved_at ? formatDateTime(selectedAsset.approved_at) : "—"}</span>
					</div>
					<div class="detail-kv">
						<span class="detail-k">Block</span>
						<span class="detail-v">{selectedAsset.block_id ?? "—"}</span>
					</div>
					<div class="detail-kv">
						<span class="detail-k">Geography</span>
						<span class="detail-v">{selectedAsset.geography ?? "—"}</span>
					</div>
					<div class="detail-kv">
						<span class="detail-k">Asset Class</span>
						<span class="detail-v">{selectedAsset.asset_class ?? "—"}</span>
					</div>
				</div>
			</section>

			<!-- Risk metrics -->
			{#if loadingRisk}
				<section class="detail-section">
					<h4 class="detail-section-title">Risk Metrics</h4>
					<p class="detail-loading">Loading risk data…</p>
				</section>
			{:else if riskMetrics}
				<!-- Manager Score -->
				<section class="detail-section">
					<h4 class="detail-section-title">Composite Score</h4>
					<div class="score-hero" style:color={scoreColor(riskMetrics.manager_score)}>
						{scoreValue(riskMetrics.manager_score)}
					</div>
					<div class="detail-kv">
						<span class="detail-k">Calc Date</span>
						<span class="detail-v">{riskMetrics.calc_date ?? "—"}</span>
					</div>
				</section>

				<!-- CVaR -->
				<section class="detail-section">
					<h4 class="detail-section-title">CVaR (95%)</h4>
					<div class="detail-grid">
						<div class="detail-kv">
							<span class="detail-k">1M</span>
							<span class="detail-v">{riskValue(riskMetrics.cvar_95_1m)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">3M</span>
							<span class="detail-v">{riskValue(riskMetrics.cvar_95_3m)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">6M</span>
							<span class="detail-v">{riskValue(riskMetrics.cvar_95_6m)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">12M</span>
							<span class="detail-v">{riskValue(riskMetrics.cvar_95_12m)}</span>
						</div>
					</div>
				</section>

				<!-- Returns -->
				<section class="detail-section">
					<h4 class="detail-section-title">Returns</h4>
					<div class="detail-grid">
						<div class="detail-kv">
							<span class="detail-k">1M</span>
							<span class="detail-v">{riskValue(riskMetrics.return_1m)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">3M</span>
							<span class="detail-v">{riskValue(riskMetrics.return_3m)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">1Y</span>
							<span class="detail-v">{riskValue(riskMetrics.return_1y)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">3Y Ann.</span>
							<span class="detail-v">{riskValue(riskMetrics.return_3y_ann)}</span>
						</div>
					</div>
				</section>

				<!-- Risk ratios -->
				<section class="detail-section">
					<h4 class="detail-section-title">Risk Ratios</h4>
					<div class="detail-grid">
						<div class="detail-kv">
							<span class="detail-k">Sharpe 1Y</span>
							<span class="detail-v">{ratioValue(riskMetrics.sharpe_1y)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">Sortino 1Y</span>
							<span class="detail-v">{ratioValue(riskMetrics.sortino_1y)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">Volatility 1Y</span>
							<span class="detail-v">{riskValue(riskMetrics.volatility_1y)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">Max DD 1Y</span>
							<span class="detail-v">{riskValue(riskMetrics.max_drawdown_1y)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">Alpha 1Y</span>
							<span class="detail-v">{ratioValue(riskMetrics.alpha_1y)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">Beta 1Y</span>
							<span class="detail-v">{ratioValue(riskMetrics.beta_1y)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">Info Ratio</span>
							<span class="detail-v">{ratioValue(riskMetrics.information_ratio_1y)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">Track Error</span>
							<span class="detail-v">{riskValue(riskMetrics.tracking_error_1y)}</span>
						</div>
					</div>
				</section>

				<!-- Momentum signals -->
				<section class="detail-section">
					<h4 class="detail-section-title">Momentum Signals</h4>
					<div class="detail-grid">
						<div class="detail-kv">
							<span class="detail-k">RSI-14</span>
							<span class="detail-v">{scoreValue(riskMetrics.rsi_14)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">Bollinger</span>
							<span class="detail-v">{ratioValue(riskMetrics.bb_position)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">NAV Momentum</span>
							<span class="detail-v">{scoreValue(riskMetrics.nav_momentum_score)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">Flow Momentum</span>
							<span class="detail-v">{scoreValue(riskMetrics.flow_momentum_score)}</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">Blended</span>
							<span class="detail-v" style:color={momentumColor(riskMetrics.blended_momentum_score)}>
								{scoreValue(riskMetrics.blended_momentum_score)}
								({momentumLabel(riskMetrics.blended_momentum_score)})
							</span>
						</div>
						<div class="detail-kv">
							<span class="detail-k">DTW Drift</span>
							<span class="detail-v">{ratioValue(riskMetrics.dtw_drift_score)}</span>
						</div>
					</div>
				</section>
			{:else}
				<section class="detail-section">
					<h4 class="detail-section-title">Risk Metrics</h4>
					<p class="detail-empty">No risk data available for this instrument.</p>
				</section>
			{/if}
		</div>
	{/if}
	{#snippet failed()}
		<div class="detail">
			<p class="detail-empty">Failed to load fund details. Try closing and re-opening the panel.</p>
		</div>
	{/snippet}
	</svelte:boundary>
</ContextPanel>

<style>
	/* ── Page layout ─────────────────────────────────────────────────────── */
	.universe-page {
		display: flex;
		flex-direction: column;
		height: calc(100vh - 64px);
		overflow: hidden;
	}

	/* Toolbar */
	.universe-toolbar {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 10px);
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		flex-shrink: 0;
	}

	.universe-search {
		flex: 1;
		max-width: 360px;
		height: var(--ii-space-control-height-sm, 32px);
		padding: 0 var(--ii-space-inline-sm, 10px);
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 8px);
		background: var(--ii-surface-elevated);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-family: var(--ii-font-sans);
	}

	.universe-search:focus {
		outline: none;
		border-color: var(--ii-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-brand-secondary) 20%, transparent);
	}

	.universe-search::placeholder {
		color: var(--ii-text-muted);
	}

	.universe-select {
		height: var(--ii-space-control-height-sm, 32px);
		padding: 0 var(--ii-space-inline-sm, 10px);
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 8px);
		background: var(--ii-surface-elevated);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-family: var(--ii-font-sans);
	}

	.universe-count {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
		margin-left: auto;
	}

	/* Table */
	.table-wrap {
		flex: 1;
		overflow-y: auto;
		overflow-x: auto;
	}

	.universe-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.universe-table thead {
		position: sticky;
		top: 0;
		z-index: 1;
	}

	.universe-table th {
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-sm, 12px);
		text-align: left;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		letter-spacing: 0.02em;
		text-transform: uppercase;
		color: var(--ii-text-muted);
		background: var(--ii-surface-alt);
		border-bottom: 1px solid var(--ii-border-subtle);
		white-space: nowrap;
	}

	.universe-table td {
		padding: var(--ii-space-stack-2xs, 8px) var(--ii-space-inline-sm, 12px);
		border-bottom: 1px solid var(--ii-border-subtle);
		vertical-align: middle;
	}

	.universe-row {
		cursor: pointer;
		transition: background-color 80ms ease;
	}

	.universe-row:hover {
		background: var(--ii-surface-highlight, color-mix(in srgb, var(--ii-brand-primary) 4%, transparent));
	}

	.universe-row.selected {
		background: color-mix(in srgb, var(--ii-brand-primary) 8%, transparent);
	}

	.th-name { min-width: 200px; }
	.th-type { min-width: 90px; }
	.th-block { min-width: 100px; }
	.th-geo { min-width: 100px; }
	.th-class { min-width: 100px; }
	.th-decision { min-width: 90px; }
	.th-date { min-width: 140px; }

	.td-name {
		font-weight: 500;
		color: var(--ii-text-primary);
	}

	.type-badge {
		display: inline-block;
		padding: 1px 8px;
		border-radius: var(--ii-radius-pill, 999px);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 500;
		white-space: nowrap;
	}

	.td-block, .td-geo, .td-class {
		color: var(--ii-text-secondary);
	}

	.td-date {
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
	}

	/* ── Detail panel ────────────────────────────────────────────────────── */
	.detail {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-sm, 12px);
	}

	.detail-section {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-sm, 8px);
		overflow: hidden;
	}

	.detail-section-title {
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-sm, 10px);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--ii-text-muted);
		background: var(--ii-surface-alt);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.detail-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0;
	}

	.detail-kv {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--ii-space-stack-2xs, 5px) var(--ii-space-inline-sm, 10px);
		border-bottom: 1px solid var(--ii-border-subtle);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.detail-kv:last-child {
		border-bottom: none;
	}

	.detail-k {
		color: var(--ii-text-muted);
		font-size: var(--ii-text-label, 0.75rem);
	}

	.detail-v {
		font-weight: 500;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.score-hero {
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-sm, 10px);
		font-size: var(--ii-text-h2, 1.75rem);
		font-weight: 800;
		font-variant-numeric: tabular-nums;
		text-align: center;
	}

	.detail-loading,
	.detail-empty {
		padding: var(--ii-space-stack-md, 16px);
		text-align: center;
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
	}
</style>
