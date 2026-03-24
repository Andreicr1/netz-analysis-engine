<!--
  Portfolio Workbench — tactical allocation management.
  Tabs: Strategic / Tactical / Effective / Rebalancing / Benchmark.
  Allocation Editor: $state weights + $derived totalWeight (must == 100% to save).
  ConsequenceDialog on every rebalance submission.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { invalidateAll } from "$app/navigation";
	import {
		PageHeader, PageTabs, StatusBadge, Button, ConsequenceDialog,
		formatPercent, formatDateTime, formatNumber,
	} from "@netz/ui";
	import type { ConsequenceDialogPayload } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { RiskStore } from "$lib/stores/risk-store.svelte";
	import type { PageData } from "./$types";
	import type {
		PortfolioSummary, PortfolioSnapshot,
		StrategicAllocation, EffectiveAllocation, EditableWeight,
	} from "$lib/types/portfolio";
	import RebalancingTab from "$lib/components/RebalancingTab.svelte";
	import BlendedBenchmarkEditor from "$lib/components/BlendedBenchmarkEditor.svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const riskStore = getContext<RiskStore>("netz:riskStore");

	let { data }: { data: PageData } = $props();

	let profile = $derived(data.profile as string);
	let portfolio = $derived(data.portfolio as PortfolioSummary | null);
	let snapshot = $derived(data.snapshot as PortfolioSnapshot | null);
	let strategic = $derived((data.strategic ?? []) as StrategicAllocation[]);
	let effective = $derived((data.effective ?? []) as EffectiveAllocation[]);

	// Live risk data
	let live = $derived(riskStore.cvarByProfile[profile]);

	// ── Tab state ─────────────────────────────────────────────────────────

	type TabKey = "strategic" | "tactical" | "effective" | "rebalancing" | "benchmark" | "history";
	let activeTab = $state<TabKey>("strategic");

	const tabs = [
		{ key: "strategic" as const, label: "Strategic" },
		{ key: "tactical" as const, label: "Tactical" },
		{ key: "effective" as const, label: "Effective" },
		{ key: "rebalancing" as const, label: "Rebalancing" },
		{ key: "benchmark" as const, label: "Benchmark" },
		{ key: "history" as const, label: "History" },
	];

	// ── Allocation Editor (editable weights) ──────────────────────────────

	let editableWeights = $state<EditableWeight[]>([]);
	let editing = $state(false);

	function startEditing() {
		editableWeights = strategic.map((s) => ({
			block_id: s.block_id,
			weight: Number(s.target_weight),
			min_weight: Number(s.min_weight),
			max_weight: Number(s.max_weight),
			strategic_weight: Number(s.target_weight),
		}));
		editing = true;
	}

	function cancelEditing() {
		editing = false;
		editableWeights = [];
	}

	// $derived totalWeight — the guardian
	let totalWeight = $derived(
		editableWeights.reduce((sum, w) => sum + w.weight, 0)
	);

	let isValidAllocation = $derived(
		Math.abs(totalWeight - 1.0) < 0.0001
	);

	let hasChanges = $derived(
		editableWeights.some((w) => Math.abs(w.weight - w.strategic_weight) > 0.0001)
	);

	// Per-row validation
	function isWeightInBounds(w: EditableWeight): boolean {
		return w.weight >= w.min_weight && w.weight <= w.max_weight;
	}

	// ── Rebalance dialog ──────────────────────────────────────────────────

	let rebalanceDialogOpen = $state(false);
	let submitting = $state(false);
	let error = $state<string | null>(null);

	function requestRebalance() {
		if (!isValidAllocation) return;
		rebalanceDialogOpen = true;
	}

	async function handleRebalance(payload: ConsequenceDialogPayload) {
		submitting = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/portfolios/${profile}/rebalance`, {
				trigger_reason: payload.rationale,
			});
			rebalanceDialogOpen = false;
			editing = false;
			editableWeights = [];
			await invalidateAll();
		} catch (e) {
			error = e instanceof Error ? e.message : "Rebalance failed";
		} finally {
			submitting = false;
		}
	}

	// ── History (lazy load) ──────────────────────────────────────────────

	interface HistorySnapshot {
		snapshot_date: string;
		nav: number | null;
		breach_status: string | null;
		regime: string | null;
	}

	let historySnapshots = $state<HistorySnapshot[]>([]);
	let historyLoading = $state(false);
	let historyLoaded = $state(false);
	let historyError = $state<string | null>(null);

	$effect(() => {
		if (activeTab !== "history" || historyLoaded) return;
		const controller = new AbortController();
		historyLoading = true;
		historyError = null;

		(async () => {
			try {
				const api = createClientApiClient(getToken);
				const result = await api.get<HistorySnapshot[]>(`/portfolios/${profile}/history`);
				if (!controller.signal.aborted) {
					historySnapshots = result;
					historyLoaded = true;
				}
			} catch (e) {
				if (!controller.signal.aborted) {
					historyError = e instanceof Error ? e.message : "Failed to load history";
				}
			} finally {
				if (!controller.signal.aborted) {
					historyLoading = false;
				}
			}
		})();

		return () => controller.abort();
	});

	// ── Helpers ───────────────────────────────────────────────────────────

	function cvarDisplay(v: unknown): string {
		if (v === null || v === undefined) return "—";
		const n = typeof v === "string" ? parseFloat(v) : Number(v);
		if (isNaN(n)) return "—";
		return formatPercent(n);
	}

	function weightDelta(w: EditableWeight): number {
		return w.weight - w.strategic_weight;
	}

	function deltaColor(d: number): string {
		if (Math.abs(d) < 0.0001) return "var(--netz-text-muted)";
		return d > 0 ? "var(--netz-success)" : "var(--netz-danger)";
	}
</script>

<PageHeader
	title="{profile} — Portfolio Workbench"
	subtitle="Strategic allocation, tactical tilts, rebalancing events, and benchmark configuration"
	breadcrumbs={[{ label: "Portfolios", href: "/portfolios" }, { label: profile }]}
>
	{#snippet actions()}
		<div class="pw-actions">
			{#if portfolio?.regime ?? live?.regime}
				<StatusBadge status={live?.regime ?? portfolio?.regime ?? "—"} />
			{/if}
			{#if portfolio?.trigger_status ?? live?.trigger_status}
				<StatusBadge status={live?.trigger_status ?? portfolio?.trigger_status ?? "ok"} />
			{/if}
		</div>
	{/snippet}
</PageHeader>

<!-- KPIs -->
<div class="pw-kpis">
	<div class="pw-kpi-card">
		<span class="pw-kpi-label">CVaR 95%</span>
		<span class="pw-kpi-value">{cvarDisplay(live?.cvar_current ?? portfolio?.cvar_current)}</span>
	</div>
	<div class="pw-kpi-card">
		<span class="pw-kpi-label">CVaR Limit</span>
		<span class="pw-kpi-value">{cvarDisplay(live?.cvar_limit ?? portfolio?.cvar_limit)}</span>
	</div>
	<div class="pw-kpi-card">
		<span class="pw-kpi-label">Utilized</span>
		<span class="pw-kpi-value">{cvarDisplay(live?.cvar_utilized_pct ?? portfolio?.cvar_utilized_pct)}</span>
	</div>
	<div class="pw-kpi-card">
		<span class="pw-kpi-label">Snapshot</span>
		<span class="pw-kpi-value pw-kpi-value--date">
			{snapshot?.snapshot_date ?? "—"}
		</span>
	</div>
</div>

<!-- Tabs -->
<div class="pw-tabs">
	{#each tabs as tab (tab.key)}
		<button
			class="pw-tab"
			class:pw-tab--active={activeTab === tab.key}
			onclick={() => activeTab = tab.key}
		>
			{tab.label}
		</button>
	{/each}

	{#if activeTab === "strategic" && !editing}
		<Button size="sm" variant="outline" onclick={startEditing} class="pw-edit-btn">
			Edit Allocation
		</Button>
	{/if}
</div>

{#if error}
	<div class="pw-error">{error}</div>
{/if}

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- TAB CONTENT                                                            -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
<div class="pw-content">
	{#if activeTab === "strategic"}
		{#if editing}
			<!-- ── ALLOCATION EDITOR ──────────────────────────────────────── -->
			<div class="editor">
				<div class="editor-header">
					<span class="editor-total" class:editor-total--valid={isValidAllocation} class:editor-total--invalid={!isValidAllocation}>
						Total: {(totalWeight * 100).toFixed(2)}%
						{#if !isValidAllocation}
							<span class="editor-hint">(must equal 100%)</span>
						{/if}
					</span>
					<div class="editor-actions">
						<Button size="sm" variant="ghost" onclick={cancelEditing}>Cancel</Button>
						<Button
							size="sm"
							onclick={requestRebalance}
							disabled={!isValidAllocation || !hasChanges}
						>
							Save & Rebalance
						</Button>
					</div>
				</div>

				<table class="alloc-table">
					<thead>
						<tr>
							<th class="ath-block">Block</th>
							<th class="ath-current">Current</th>
							<th class="ath-new">New Weight</th>
							<th class="ath-delta">Delta</th>
							<th class="ath-bounds">Bounds</th>
						</tr>
					</thead>
					<tbody>
						{#each editableWeights as row, i (row.block_id)}
							{@const delta = weightDelta(row)}
							{@const inBounds = isWeightInBounds(row)}
							<tr class="alloc-row" class:alloc-row--oob={!inBounds}>
								<td class="atd-block">{row.block_id}</td>
								<td class="atd-current">{formatPercent(row.strategic_weight)}</td>
								<td class="atd-input">
									<input
										type="number"
										class="weight-input"
										class:weight-input--oob={!inBounds}
										min={row.min_weight}
										max={row.max_weight}
										step="0.01"
										bind:value={editableWeights[i]!.weight}
									/>
								</td>
								<td class="atd-delta" style:color={deltaColor(delta)}>
									{delta >= 0 ? "+" : ""}{(delta * 100).toFixed(2)}pp
								</td>
								<td class="atd-bounds">
									{formatPercent(row.min_weight)} – {formatPercent(row.max_weight)}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{:else}
			<!-- ── STRATEGIC VIEW (read-only) ────────────────────────────── -->
			{#if strategic.length === 0}
				<div class="pw-empty">No strategic allocation defined.</div>
			{:else}
				<table class="alloc-table alloc-table--readonly">
					<thead>
						<tr>
							<th>Block</th>
							<th>Target</th>
							<th>Min</th>
							<th>Max</th>
							<th>Approved By</th>
							<th>Effective</th>
						</tr>
					</thead>
					<tbody>
						{#each strategic as row (row.allocation_id)}
							<tr>
								<td class="atd-block">{row.block_id}</td>
								<td class="atd-weight">{formatPercent(row.target_weight)}</td>
								<td class="atd-bound">{formatPercent(row.min_weight)}</td>
								<td class="atd-bound">{formatPercent(row.max_weight)}</td>
								<td class="atd-approver">{row.approved_by ?? "—"}</td>
								<td class="atd-date">{row.effective_from}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		{/if}
	{:else if activeTab === "tactical"}
		<!-- ── TACTICAL VIEW ──────────────────────────────────────────── -->
		{#if snapshot?.weights}
			{@const entries = Object.entries(snapshot.weights)}
			{#if entries.length === 0}
				<div class="pw-empty">No tactical positions active.</div>
			{:else}
				<table class="alloc-table alloc-table--readonly">
					<thead>
						<tr>
							<th>Block</th>
							<th>Current Weight</th>
							<th>Bar</th>
						</tr>
					</thead>
					<tbody>
						{#each entries as [blockId, weight] (blockId)}
							<tr>
								<td class="atd-block">{blockId}</td>
								<td class="atd-weight">{formatPercent(weight as number)}</td>
								<td class="atd-bar">
									<div class="weight-bar-track">
										<div class="weight-bar-fill" style:width="{(weight as number) * 100}%"></div>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		{:else}
			<div class="pw-empty">No snapshot available.</div>
		{/if}
	{:else if activeTab === "effective"}
		<!-- ── EFFECTIVE VIEW ─────────────────────────────────────────── -->
		{#if effective.length === 0}
			<div class="pw-empty">No effective allocation computed.</div>
		{:else}
			<table class="alloc-table alloc-table--readonly">
				<thead>
					<tr>
						<th>Block</th>
						<th>Strategic</th>
						<th>Tactical OW</th>
						<th>Effective</th>
						<th>Min</th>
						<th>Max</th>
					</tr>
				</thead>
				<tbody>
					{#each effective as row (row.block_id)}
						<tr>
							<td class="atd-block">{row.block_id}</td>
							<td class="atd-weight">{formatPercent(row.strategic_weight)}</td>
							<td class="atd-delta" style:color={deltaColor(Number(row.tactical_overweight ?? 0))}>
								{Number(row.tactical_overweight ?? 0) >= 0 ? "+" : ""}{formatPercent(row.tactical_overweight)}
							</td>
							<td class="atd-weight atd-weight--bold">{formatPercent(row.effective_weight)}</td>
							<td class="atd-bound">{formatPercent(row.min_weight)}</td>
							<td class="atd-bound">{formatPercent(row.max_weight)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	{:else if activeTab === "rebalancing"}
		<!-- ── REBALANCING VIEW ───────────────────────────────────────── -->
		<RebalancingTab
			{profile}
			currentWeights={snapshot?.weights ?? {}}
			cvarCurrent={Number(live?.cvar_current ?? portfolio?.cvar_current) || null}
			cvarLimit={Number(live?.cvar_limit ?? portfolio?.cvar_limit) || null}
		/>
	{:else if activeTab === "benchmark"}
		<!-- ── BENCHMARK VIEW ─────────────────────────────────────────── -->
		<BlendedBenchmarkEditor {profile} />
	{:else if activeTab === "history"}
		<!-- ── HISTORY VIEW ───────────────────────────────────────────── -->
		{#if historyLoading}
			<div class="pw-empty">Loading history…</div>
		{:else if historyError}
			<div class="pw-error">{historyError}</div>
		{:else if historySnapshots.length === 0}
			<div class="pw-empty">No snapshots available.</div>
		{:else}
			<table class="alloc-table alloc-table--readonly">
				<thead>
					<tr>
						<th>Date</th>
						<th>NAV</th>
						<th>Breach Status</th>
						<th>Regime</th>
					</tr>
				</thead>
				<tbody>
					{#each historySnapshots as snap (snap.snapshot_date)}
						<tr>
							<td class="atd-date">{snap.snapshot_date}</td>
							<td class="atd-weight">{snap.nav !== null ? formatNumber(snap.nav) : "—"}</td>
							<td>
								{#if snap.breach_status}
									<StatusBadge status={snap.breach_status} />
								{:else}
									<span class="atd-date">—</span>
								{/if}
							</td>
							<td>
								{#if snap.regime}
									<StatusBadge status={snap.regime} />
								{:else}
									<span class="atd-date">—</span>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	{/if}
</div>

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- REBALANCE CONSEQUENCE DIALOG                                           -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
<ConsequenceDialog
	bind:open={rebalanceDialogOpen}
	title="Submit Rebalance"
	impactSummary="This will create a pending rebalance event requiring IC approval before execution."
	requireRationale={true}
	rationaleLabel="Rebalance Rationale"
	rationalePlaceholder="Describe the investment rationale for this allocation change (min 10 chars)."
	rationaleMinLength={10}
	confirmLabel="Submit Rebalance"
	metadata={[
		{ label: "Profile", value: profile },
		{ label: "Total Weight", value: `${(totalWeight * 100).toFixed(2)}%`, emphasis: !isValidAllocation },
		{ label: "Blocks Changed", value: String(editableWeights.filter((w) => Math.abs(weightDelta(w)) > 0.0001).length) },
	]}
	onConfirm={handleRebalance}
/>

<style>
	/* ── KPIs ─────────────────────────────────────────────────────────────── */
	.pw-kpis {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 1px;
		margin: 0 var(--netz-space-inline-lg, 24px);
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
		overflow: hidden;
		background: var(--netz-border-subtle);
	}

	.pw-kpi-card {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px);
		background: var(--netz-surface-elevated);
	}

	.pw-kpi-label {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.pw-kpi-value {
		font-size: var(--netz-text-h4, 1.125rem);
		font-weight: 700;
		color: var(--netz-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.pw-kpi-value--date {
		font-size: var(--netz-text-body, 0.9375rem);
	}

	/* ── Tabs ─────────────────────────────────────────────────────────────── */
	.pw-tabs {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-2xs, 4px);
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-lg, 24px);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.pw-tab {
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-md, 16px);
		border: 1px solid transparent;
		border-radius: var(--netz-radius-sm, 8px);
		background: transparent;
		color: var(--netz-text-secondary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 500;
		font-family: var(--netz-font-sans);
		cursor: pointer;
		transition: background-color 120ms ease, color 120ms ease;
	}

	.pw-tab:hover {
		background: var(--netz-surface-alt);
		color: var(--netz-text-primary);
	}

	.pw-tab--active {
		background: color-mix(in srgb, var(--netz-brand-primary) 10%, transparent);
		color: var(--netz-brand-primary);
		font-weight: 600;
	}

	:global(.pw-edit-btn) {
		margin-left: auto;
	}

	/* ── Actions bar ─────────────────────────────────────────────────────── */
	.pw-actions {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-sm, 8px);
	}

	.pw-error {
		margin: 0 var(--netz-space-inline-lg, 24px);
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		border-radius: var(--netz-radius-sm, 8px);
		background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
		color: var(--netz-danger);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.pw-empty {
		padding: var(--netz-space-stack-xl, 48px);
		text-align: center;
		color: var(--netz-text-muted);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	/* ── Content ──────────────────────────────────────────────────────────── */
	.pw-content {
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
	}

	/* ── Allocation tables ────────────────────────────────────────────────── */
	.alloc-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--netz-text-small, 0.8125rem);
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-sm, 8px);
		overflow: hidden;
	}

	.alloc-table th {
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-sm, 12px);
		text-align: left;
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		color: var(--netz-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.02em;
		background: var(--netz-surface-alt);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.alloc-table td {
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-sm, 12px);
		border-bottom: 1px solid var(--netz-border-subtle);
		vertical-align: middle;
	}

	.atd-block { font-weight: 500; color: var(--netz-text-primary); }
	.atd-weight { font-variant-numeric: tabular-nums; color: var(--netz-text-primary); }
	.atd-weight--bold { font-weight: 700; }
	.atd-bound { font-variant-numeric: tabular-nums; color: var(--netz-text-muted); font-size: var(--netz-text-label, 0.75rem); }
	.atd-approver { color: var(--netz-text-secondary); }
	.atd-date { color: var(--netz-text-muted); font-variant-numeric: tabular-nums; }
	.atd-delta { font-variant-numeric: tabular-nums; font-weight: 600; }
	.atd-current { font-variant-numeric: tabular-nums; color: var(--netz-text-secondary); }

	.atd-bar { width: 120px; }

	.weight-bar-track {
		height: 6px;
		background: var(--netz-surface-alt);
		border-radius: 3px;
		overflow: hidden;
	}

	.weight-bar-fill {
		height: 100%;
		background: var(--netz-brand-primary);
		border-radius: 3px;
		transition: width 200ms ease;
	}

	/* ── Editor ───────────────────────────────────────────────────────────── */
	.editor {
		border: 1px solid var(--netz-border-accent);
		border-radius: var(--netz-radius-md, 12px);
		overflow: hidden;
	}

	.editor-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-alt);
	}

	.editor-total {
		font-size: var(--netz-text-body, 0.9375rem);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}

	.editor-total--valid { color: var(--netz-success); }
	.editor-total--invalid { color: var(--netz-danger); }

	.editor-hint {
		font-weight: 400;
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.editor-actions {
		display: flex;
		gap: var(--netz-space-inline-xs, 6px);
	}

	.ath-block { min-width: 180px; }
	.ath-current { width: 90px; text-align: right; }
	.ath-new { width: 120px; }
	.ath-delta { width: 80px; text-align: right; }
	.ath-bounds { width: 120px; }

	.atd-input {
		padding: 2px var(--netz-space-inline-sm, 12px);
	}

	.weight-input {
		width: 90px;
		height: var(--netz-space-control-height-sm, 32px);
		padding: 0 var(--netz-space-inline-xs, 8px);
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 6px);
		background: var(--netz-surface-elevated);
		color: var(--netz-text-primary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-mono);
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	.weight-input:focus {
		outline: none;
		border-color: var(--netz-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--netz-brand-secondary) 20%, transparent);
	}

	.weight-input--oob {
		border-color: var(--netz-danger);
	}

	.alloc-row--oob {
		background: color-mix(in srgb, var(--netz-danger) 4%, transparent);
	}

	/* ── Responsive ──────────────────────────────────────────────────────── */
	@media (max-width: 768px) {
		.pw-kpis {
			grid-template-columns: 1fr 1fr;
		}
	}
</style>
