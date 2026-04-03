<!--
  Asset Universe — approved instruments + pending approvals.
  Master/Detail: results table + ContextPanel with risk/scoring data.
  Pending tab: IC approval workflow with block_id assignment.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { invalidateAll } from "$app/navigation";
	import {
		PageHeader, ContextPanel, StatusBadge, EmptyState, ConsequenceDialog,
		formatDateTime, formatNumber, formatPercent, formatCurrency,
	} from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { UniverseAsset, UniverseApproval, InstrumentRiskMetrics } from "$lib/types/universe";
	import { instrumentTypeLabel, instrumentTypeColor } from "$lib/types/universe";
	import type { ConsequenceDialogPayload } from "@investintell/ui";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let assets = $derived((data.assets ?? []) as UniverseAsset[]);
	let pending = $derived((data.pending ?? []) as UniverseApproval[]);
	let actorRole = $derived((data.actorRole ?? null) as string | null);

	const IC_ROLES = ["investment_team", "director", "admin", "super_admin"];
	let canApprove = $derived(actorRole !== null && IC_ROLES.includes(actorRole));

	// ── Tab state ─────────────────────────────────────────────────────
	type Tab = "approved" | "pending";
	let activeTab = $state<Tab>("approved");

	// ── Search filter ─────────────────────────────────────────────────

	let search = $state("");
	let blockFilter = $state<string | null>(null);
	let typeFilter = $state<string | null>(null);

	let distinctBlocks = $derived(
		[...new Set(assets.map((a) => a.block_id).filter(Boolean))] as string[]
	);
	let distinctClasses = $derived(
		[...new Set(assets.map((a) => a.asset_class).filter(Boolean))] as string[]
	);

	let filtered = $derived.by(() => {
		let rows = assets;
		if (blockFilter) {
			rows = rows.filter((a) => a.block_id === blockFilter);
		}
		if (typeFilter) {
			rows = rows.filter((a) => a.asset_class === typeFilter);
		}
		if (search) {
			const q = search.toLowerCase();
			rows = rows.filter((a) =>
				a.fund_name?.toLowerCase().includes(q) ||
				a.ticker?.toLowerCase().includes(q) ||
				a.block_id?.toLowerCase().includes(q) ||
				a.geography?.toLowerCase().includes(q) ||
				a.asset_class?.toLowerCase().includes(q)
			);
		}
		return rows;
	});

	// ── Detail panel ──────────────────────────────────────────────────

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

	// ── Helpers ───────────────────────────────────────────────────────
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

	function formatAssetClass(ac: string | null | undefined): string {
		if (!ac) return "\u2014";
		return ac.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}

	// ── Approval workflow ─────────────────────────────────────────────

	const DEFAULT_BLOCKS = [
		"na_equity_large", "na_equity_value", "na_equity_small",
		"fi_us_aggregate", "fi_us_treasury", "fi_us_high_yield",
		"alt_gold", "alt_real_estate", "alt_commodities",
		"em_equity", "dm_asia_equity", "dm_europe_equity", "cash",
	];
	let availableBlocks = $derived(
		[...new Set(assets.map((a) => a.block_id).filter(Boolean))] as string[]
	);
	let blocks = $derived(availableBlocks.length > 0 ? availableBlocks : DEFAULT_BLOCKS);

	let approvalDialogOpen = $state(false);
	let approvalTarget = $state<UniverseApproval | null>(null);
	let approvalBlockId = $state("");
	let approvalError = $state<string | null>(null);
	let approving = $state(false);

	function requestApprove(item: UniverseApproval) {
		approvalTarget = item;
		approvalBlockId = item.block_id ?? blocks[0] ?? "";
		approvalError = null;
		approvalDialogOpen = true;
	}

	async function handleApprove(_payload: ConsequenceDialogPayload) {
		if (!approvalTarget) return;
		approvalDialogOpen = false;
		approvalError = null;
		approving = true;
		try {
			const api = createClientApiClient(getToken);
			// 1. Assign block_id on InstrumentOrg
			await api.patch(`/instruments/${approvalTarget.instrument_id}/org`, {
				block_id: approvalBlockId,
			});
			// 2. Approve in universe
			await api.post(`/universe/funds/${approvalTarget.instrument_id}/approve`, {
				decision: "approved",
				rationale: "Approved via Assets Universe",
			});
			await invalidateAll();
		} catch (e) {
			approvalError = e instanceof Error ? e.message : "Approval failed";
		} finally {
			approving = false;
		}
	}
</script>

<PageHeader title="Asset Universe">
	{#snippet actions()}
		<div class="tab-group">
			<button class="tab-btn" class:tab-btn--active={activeTab === "approved"}
				onclick={() => activeTab = "approved"} type="button">
				Approved ({assets.length})
			</button>
			<button class="tab-btn" class:tab-btn--active={activeTab === "pending"}
				onclick={() => activeTab = "pending"} type="button">
				Pending ({pending.length})
			</button>
		</div>
	{/snippet}
</PageHeader>

{#if approvalError}
	<div class="approval-error">
		{approvalError}
		<button onclick={() => approvalError = null} type="button">&times;</button>
	</div>
{/if}

{#if activeTab === "approved"}
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
				<option value={null}>All classes</option>
				{#each distinctClasses as c (c)}
					<option value={c}>{formatAssetClass(c)}</option>
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
							<th class="th-ticker">Ticker</th>
							<th class="th-type">Asset Class</th>
							<th class="th-block">Block</th>
							<th class="th-geo">Geography</th>
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
								<td class="td-ticker"><code class="mini-ticker">{asset.ticker ?? "—"}</code></td>
								<td class="td-type">
									<span class="type-badge">
										{formatAssetClass(asset.asset_class)}
									</span>
								</td>
								<td class="td-block">{asset.block_id ?? "—"}</td>
								<td class="td-geo">{asset.geography ?? "—"}</td>
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
{:else}
	<!-- Pending approvals tab -->
	<div class="universe-page">
		{#if pending.length === 0}
			<EmptyState title="No pending approvals"
				message="Instruments added via Screener appear here for review." />
		{:else}
			<div class="table-wrap">
				<table class="universe-table">
					<thead>
						<tr>
							<th class="th-name">Instrument</th>
							<th>Ticker</th>
							<th>Submitted</th>
							<th>Block</th>
							<th>Action</th>
						</tr>
					</thead>
					<tbody>
						{#each pending as item (item.instrument_id)}
							<tr class="universe-row">
								<td class="td-name">{item.fund_name ?? item.instrument_id}</td>
								<td>{item.ticker ?? "—"}</td>
								<td class="td-date">{formatDateTime(item.created_at)}</td>
								<td>{item.block_id ?? "—"}</td>
								<td>
									{#if canApprove}
										<Button size="sm" onclick={() => requestApprove(item)}>
											Approve
										</Button>
									{:else}
										<span class="role-hint">IC role required</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
{/if}

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
						<span class="detail-v">{formatAssetClass(selectedAsset.asset_class)}</span>
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

<!-- Approval dialog -->
<ConsequenceDialog
	bind:open={approvalDialogOpen}
	title="Approve Instrument"
	impactSummary="This instrument will be added to the approved universe and become available in Portfolio Builder."
	requireRationale={false}
	confirmLabel="Approve"
	metadata={[{ label: "Instrument", value: approvalTarget?.fund_name ?? approvalTarget?.instrument_id ?? "" }]}
	onConfirm={handleApprove}
>
	<div class="approval-block-select">
		<label class="approval-label">Allocation Block</label>
		<select class="universe-select" style="width:100%;" bind:value={approvalBlockId}>
			{#each blocks as b (b)}
				<option value={b}>{b}</option>
			{/each}
		</select>
	</div>
</ConsequenceDialog>

<style>
	/* ── Page layout ─────────────────────────────────────────────────────── */
	.universe-page {
		display: flex;
		flex-direction: column;
		height: calc(100vh - 64px);
		overflow: hidden;
	}

	/* Tab group */
	.tab-group {
		display: flex;
		gap: 6px;
	}

	.tab-btn {
		padding: 6px 14px;
		border: 1px solid var(--ii-border);
		border-radius: 8px;
		background: transparent;
		color: var(--ii-text-secondary);
		font-size: 13px;
		font-weight: 500;
		cursor: pointer;
		font-family: var(--ii-font-sans);
		transition: all 120ms ease;
	}

	.tab-btn--active {
		background: color-mix(in srgb, var(--ii-brand-primary) 10%, transparent);
		color: var(--ii-brand-primary);
		border-color: var(--ii-brand-primary);
		font-weight: 600;
	}

	/* Approval error banner */
	.approval-error {
		padding: 8px 24px;
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: 13px;
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.approval-error button {
		background: none;
		border: none;
		color: var(--ii-danger);
		cursor: pointer;
		font-size: 16px;
		padding: 0 4px;
	}

	.role-hint {
		font-size: 12px;
		color: var(--ii-text-muted);
	}

	.approval-block-select {
		padding: 8px 0;
	}

	.approval-label {
		font-size: 13px;
		font-weight: 500;
		color: var(--ii-text-secondary);
		display: block;
		margin-bottom: 6px;
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
	.th-ticker { min-width: 80px; }
	.th-type { min-width: 100px; }
	.th-block { min-width: 100px; }
	.th-geo { min-width: 100px; }
	.th-decision { min-width: 90px; }
	.th-date { min-width: 140px; }

	.td-name {
		font-weight: 500;
		color: var(--ii-text-primary);
	}

	.td-ticker {
		font-family: var(--ii-font-mono, monospace);
	}

	.mini-ticker {
		font-size: 11px;
		background: var(--ii-surface-alt);
		padding: 2px 4px;
		border-radius: 3px;
		color: var(--ii-brand-primary);
	}

	.type-badge {
		display: inline-block;
		padding: 1px 8px;
		border-radius: var(--ii-radius-pill, 999px);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 500;
		white-space: nowrap;
		background: var(--ii-surface-alt);
		color: var(--ii-text-secondary);
		border: 1px solid var(--ii-border-subtle);
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
