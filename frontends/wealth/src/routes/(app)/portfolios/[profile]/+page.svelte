<!--
  Portfolio Workbench — tactical allocation management + reports.
  Tabs: Strategic / Tactical / Effective / Rebalancing / Benchmark / Reports / History.
  Allocation Editor: $state weights + $derived totalWeight (must == 100% to save).
  ConsequenceDialog on every rebalance submission.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { invalidateAll } from "$app/navigation";
	import {
		PageHeader, PageTabs, StatusBadge, Button, ConsequenceDialog,
		formatPercent, formatDateTime, formatNumber, formatDate,
	} from "@investintell/ui";
	import type { ConsequenceDialogPayload } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { RiskStore } from "$lib/stores/risk-store.svelte";
	import type { PageData } from "./$types";
	import type {
		PortfolioSummary, PortfolioSnapshot,
		StrategicAllocation, EffectiveAllocation, EditableWeight,
	} from "$lib/types/portfolio";
	import type { ModelPortfolio, InstrumentWeight, OverlapResult } from "$lib/types/model-portfolio";
	import RebalancingTab from "$lib/components/RebalancingTab.svelte";
	import BlendedBenchmarkEditor from "$lib/components/BlendedBenchmarkEditor.svelte";
	import LongFormReportPanel from "$lib/components/LongFormReportPanel.svelte";
	import MonthlyReportPanel from "$lib/components/MonthlyReportPanel.svelte";
	import CVaRHistoryChart from "$lib/components/charts/CVaRHistoryChart.svelte";
	import RegimeTimeline from "$lib/components/charts/RegimeTimeline.svelte";
	import { regimeMultiplierLabel } from "$lib/constants/regime";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const riskStore = getContext<RiskStore>("netz:riskStore");

	let { data }: { data: PageData } = $props();

	let profile = $derived(data.profile as string);
	let portfolio = $derived(data.portfolio as PortfolioSummary | null);
	let snapshot = $derived(data.snapshot as PortfolioSnapshot | null);
	let strategic = $derived((data.strategic ?? []) as StrategicAllocation[]);
	let effective = $derived((data.effective ?? []) as EffectiveAllocation[]);
	let blockLabels = $derived((data.blockLabels ?? {}) as Record<string, string>);

	let modelPortfolio = $derived(data.modelPortfolio as ModelPortfolio | null);
	let fundsByBlock = $derived.by(() => {
		const map = new Map<string, InstrumentWeight[]>();
		const funds = modelPortfolio?.fund_selection_schema?.funds ?? [];
		for (const f of funds) {
			const list = map.get(f.block_id) ?? [];
			list.push(f);
			map.set(f.block_id, list);
		}
		return map;
	});

	// ── Fact Sheets ──────────────────────────────────────────────────────

	interface FactSheetEntry {
		path: string;
		as_of: string;
		language: string;
		format: string;
	}

	let factSheets = $derived((data.factSheets ?? []) as FactSheetEntry[]);
	let overlapData = $derived((data.overlapData ?? null) as OverlapResult | null);

	let fsGenerating = $state(false);
	let fsLang = $state<"pt" | "en">("pt");
	let fsDownloading = $state<string | null>(null);
	let fsError = $state<string | null>(null);

	async function generateFactSheet() {
		if (!modelPortfolio) return;
		fsGenerating = true;
		fsError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/fact-sheets/model-portfolios/${modelPortfolio.id}?language=${fsLang}`, {});
			await invalidateAll();
		} catch (e) {
			fsError = e instanceof Error ? e.message : "Failed to generate fact sheet";
		} finally {
			fsGenerating = false;
		}
	}

	async function downloadFactSheet(path: string) {
		fsDownloading = path;
		fsError = null;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(`/fact-sheets/${encodeURIComponent(path)}/download`);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `fact-sheet-${profile}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			fsError = e instanceof Error ? e.message : "Download failed";
		} finally {
			fsDownloading = null;
		}
	}

	let expandedBlocks = $state<Set<string>>(new Set());

	function toggleBlockExpand(blockId: string) {
		const next = new Set(expandedBlocks);
		next.has(blockId) ? next.delete(blockId) : next.add(blockId);
		expandedBlocks = next;
	}

	function blockName(block_id: string): string {
		return blockLabels[block_id] ?? block_id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}

	// Live risk data
	let live = $derived(riskStore.cvarByProfile[profile]);

	// ── Tab state ─────────────────────────────────────────────────────────

	type TabKey = "strategic" | "tactical" | "effective" | "overlap" | "rebalancing" | "benchmark" | "reports" | "history";
	let activeTab = $state<TabKey>("strategic");

	const tabs = [
		{ key: "strategic" as const, label: "Strategic" },
		{ key: "tactical" as const, label: "Tactical" },
		{ key: "effective" as const, label: "Effective" },
		{ key: "overlap" as const, label: "Overlap" },
		{ key: "rebalancing" as const, label: "Rebalancing" },
		{ key: "benchmark" as const, label: "Benchmark" },
		{ key: "reports" as const, label: "Reports" },
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
		if (Math.abs(d) < 0.0001) return "var(--ii-text-muted)";
		return d > 0 ? "var(--ii-success)" : "var(--ii-danger)";
	}

	// ── KPI color coding ─────────────────────────────────────────────────
	// CVaR utilization: green < 80%, yellow 80-99%, red ≥ 100%

	let utilizationPct = $derived.by((): number | null => {
		const raw = live?.cvar_utilized_pct ?? portfolio?.cvar_utilized_pct;
		if (raw === null || raw === undefined) return null;
		const n = typeof raw === "string" ? parseFloat(raw) : Number(raw);
		return isNaN(n) ? null : n;
	});

	function utilizationColor(pct: number | null): string {
		if (pct === null) return "var(--ii-text-primary)";
		if (pct >= 100) return "var(--ii-danger)";
		if (pct >= 80) return "var(--ii-warning)";
		return "var(--ii-success)";
	}

	// Breach context for trigger status tooltip
	let breachDays = $derived(
		(live?.consecutive_breach_days ?? snapshot?.consecutive_breach_days) || 0
	);

	let triggerStatus = $derived(live?.trigger_status ?? portfolio?.trigger_status ?? "ok");

	let triggerTooltip = $derived.by((): string => {
		const s = triggerStatus;
		if (s === "breach" || s === "critical") {
			return `CVaR utilization exceeded limit for ${breachDays} consecutive day${breachDays !== 1 ? "s" : ""}`;
		}
		if (s === "rebalance_triggered") return "Automatic rebalance triggered due to drift";
		if (s === "rebalance_executed") return "Rebalance recently executed";
		return "Portfolio operating within risk limits";
	});
</script>

<PageHeader
	title="{profile} — Portfolio Workbench"
	subtitle="Strategic allocation, tactical tilts, rebalancing events, and benchmark configuration"
	breadcrumbs={[{ label: "Portfolios", href: "/portfolios" }, { label: profile }]}
>
	{#snippet actions()}
		<div class="pw-actions">
			{#if portfolio?.regime ?? live?.regime}
				{@const currentRegime = live?.regime ?? portfolio?.regime ?? ""}
				<StatusBadge status={currentRegime || "—"} />
				{#if regimeMultiplierLabel(currentRegime)}
					<span class="pw-regime-multiplier">{regimeMultiplierLabel(currentRegime)}</span>
				{/if}
			{/if}
			{#if triggerStatus !== "ok"}
				<span class="pw-trigger-badge" class:pw-trigger-badge--critical={triggerStatus === "breach" || triggerStatus === "critical"} title={triggerTooltip}>
					<StatusBadge status={triggerStatus} />
				</span>
			{/if}
			{#if modelPortfolio}
				<a href="/model-portfolios/{modelPortfolio.id}" class="pw-cross-link" data-sveltekit-preload-data>Model Portfolio</a>
			{/if}
		</div>
	{/snippet}
</PageHeader>

{#if !modelPortfolio || modelPortfolio.status === "draft"}
	<div class="pw-guidance-banner">
		<p class="pw-guidance-text">
			{#if !modelPortfolio}
				No model portfolio exists for the <strong>{profile}</strong> profile.
				<a href="/model-portfolios/create" class="pw-guidance-link">Create a Model Portfolio</a> to enable monitoring.
			{:else}
				The <strong>{profile}</strong> model portfolio is in <strong>draft</strong> status.
				<a href="/model-portfolios/{modelPortfolio.id}" class="pw-guidance-link">Open it</a> to construct, backtest, and activate.
			{/if}
		</p>
	</div>
{/if}

<!-- KPIs -->
<div class="pw-kpis">
	<div class="pw-kpi-card">
		<span class="pw-kpi-label">CVaR 95%</span>
		<span class="pw-kpi-value" style:color={utilizationColor(utilizationPct)}>
			{cvarDisplay(live?.cvar_current ?? portfolio?.cvar_current)}
		</span>
	</div>
	<div class="pw-kpi-card">
		<span class="pw-kpi-label">CVaR Limit</span>
		<span class="pw-kpi-value">{cvarDisplay(live?.cvar_limit ?? portfolio?.cvar_limit)}</span>
	</div>
	<div class="pw-kpi-card">
		<span class="pw-kpi-label">Utilized</span>
		<span class="pw-kpi-value" style:color={utilizationColor(utilizationPct)}>
			{cvarDisplay(live?.cvar_utilized_pct ?? portfolio?.cvar_utilized_pct)}
		</span>
	</div>
	<div class="pw-kpi-card">
		<span class="pw-kpi-label">Snapshot</span>
		<span class="pw-kpi-value pw-kpi-value--date">
			{snapshot?.snapshot_date ? formatDate(snapshot.snapshot_date, "long", "en-US") : "—"}
		</span>
	</div>
</div>

<!-- CVaR History -->
{#if riskStore.cvarHistoryByProfile[profile]?.length}
	<section class="pw-cvar-history">
		<h3 class="pw-section-title">CVaR History</h3>
		<CVaRHistoryChart
			data={riskStore.cvarHistoryByProfile[profile]}
			{profile}
			height={280}
			loading={riskStore.status === "loading"}
		/>
	</section>
{/if}

<!-- Regime Timeline -->
{#if riskStore.regimeHistory.length > 0}
	<section class="pw-regime-timeline">
		<h3 class="pw-section-title">Regime History</h3>
		<RegimeTimeline history={riskStore.regimeHistory} {profile} />
	</section>
{/if}

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
								<td class="atd-block">{blockName(row.block_id)}</td>
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
			<!-- ── STRATEGIC VIEW (read-only, expandable fund breakdown) ── -->
			{#if strategic.length === 0}
				<div class="pw-empty">No strategic allocation defined.</div>
			{:else}
				<table class="alloc-table alloc-table--readonly">
					<thead>
						<tr>
							<th></th>
							<th>Block</th>
							<th>Target</th>
							<th>Min</th>
							<th>Max</th>
							<th>Funds</th>
						</tr>
					</thead>
					<tbody>
						{#each strategic as row (row.allocation_id)}
							{@const blockFunds = fundsByBlock.get(row.block_id) ?? []}
							{@const isExpanded = expandedBlocks.has(row.block_id)}
							<tr
								class="alloc-row-expandable"
								class:alloc-row-expandable--has-funds={blockFunds.length > 0}
								onclick={() => { if (blockFunds.length > 0) toggleBlockExpand(row.block_id); }}
							>
								<td class="atd-chevron">
									{#if blockFunds.length > 0}
										<span class="row-chevron" class:row-chevron--open={isExpanded}>&#9654;</span>
									{/if}
								</td>
								<td class="atd-block">{blockName(row.block_id)}</td>
								<td class="atd-weight">{formatPercent(row.target_weight)}</td>
								<td class="atd-bound">{formatPercent(row.min_weight)}</td>
								<td class="atd-bound">{formatPercent(row.max_weight)}</td>
								<td class="atd-count">{blockFunds.length > 0 ? `${blockFunds.length} fund${blockFunds.length !== 1 ? "s" : ""}` : "—"}</td>
							</tr>
							{#if isExpanded}
								{#each blockFunds as fund (fund.instrument_id)}
									<tr class="alloc-row-fund">
										<td></td>
										<td class="atd-fund-name" colspan="1">{fund.fund_name}</td>
										<td class="atd-fund-weight">{formatPercent(fund.weight)}</td>
										<td class="atd-bound atd-fund-meta">—</td>
										<td class="atd-bound atd-fund-meta">—</td>
										<td class="atd-fund-score">
											{#if fund.score != null}
												<span class="atd-score-badge">Score {formatNumber(fund.score, 2)}</span>
											{/if}
										</td>
									</tr>
								{/each}
							{/if}
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
							<td class="atd-block">{blockName(row.block_id)}</td>
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
	{:else if activeTab === "overlap"}
		<!-- ── OVERLAP VIEW ──────────────────────────────────────────── -->
		{#if !overlapData}
			<div class="pw-empty">No overlap data available. Ensure the portfolio has a fund selection with N-PORT data.</div>
		{:else if !overlapData.has_sufficient_data}
			<div class="overlap-empty">
				<p class="overlap-empty-title">Holdings overlap analysis requires N-PORT data for at least 2 funds.</p>
				{#if overlapData.data_warning}
					<p class="overlap-empty-detail">{overlapData.data_warning}</p>
				{/if}
			</div>
		{:else}
			{#if overlapData.data_warning}
				<div class="overlap-warning">{overlapData.data_warning}</div>
			{/if}

			<!-- Breaches -->
			{#if overlapData.breaches.length > 0}
				<div class="overlap-section">
					<h3 class="overlap-section-title overlap-section-title--danger">
						{overlapData.breaches.length} {overlapData.breaches.length === 1 ? "security exceeds" : "securities exceed"} the {formatPercent(overlapData.limit_pct)} concentration threshold
					</h3>
					<table class="alloc-table">
						<thead>
							<tr>
								<th>CUSIP</th>
								<th>Issuer</th>
								<th>Exposure</th>
								<th>Funds Holding</th>
							</tr>
						</thead>
						<tbody>
							{#each overlapData.breaches as b (b.cusip)}
								<tr class="overlap-breach-row">
									<td class="atd-block"><code>{b.cusip}</code></td>
									<td>{b.issuer_name ?? "—"}</td>
									<td class="atd-weight overlap-breach-pct">{formatPercent(b.total_exposure_pct / 100)}</td>
									<td class="overlap-funds-cell">{b.funds_holding.join(", ")}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}

			<!-- Sector Concentration -->
			{#if overlapData.sector_exposures.length > 0}
				<div class="overlap-section">
					<h3 class="overlap-section-title">Sector Concentration</h3>
					<div class="overlap-sectors">
						{#each overlapData.sector_exposures as sec (sec.sector)}
							{@const barWidth = Math.min(sec.total_exposure_pct, 100)}
							<div class="overlap-sector-row">
								<span class="overlap-sector-name">{sec.sector}</span>
								<span class="overlap-sector-pct">{formatPercent(sec.total_exposure_pct / 100)}</span>
								<div class="overlap-sector-bar-track">
									<div class="overlap-sector-bar-fill" style:width="{barWidth}%"></div>
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Top Cross-Fund Exposures -->
			{#if overlapData.top_cusip_exposures.length > 0}
				<div class="overlap-section">
					<h3 class="overlap-section-title">Top Cross-Fund Exposures</h3>
					<table class="alloc-table alloc-table--readonly">
						<thead>
							<tr>
								<th>CUSIP</th>
								<th>Issuer</th>
								<th>Exposure</th>
								<th>Funds Holding</th>
							</tr>
						</thead>
						<tbody>
							{#each overlapData.top_cusip_exposures as exp (exp.cusip)}
								{@const nearBreach = !exp.is_breach && exp.total_exposure_pct >= overlapData.limit_pct * 100 * 0.8}
								<tr>
									<td class="atd-block"><code>{exp.cusip}</code></td>
									<td>{exp.issuer_name ?? "—"}</td>
									<td class="atd-weight">
										<span
											class:overlap-breach-pct={exp.is_breach}
											class:overlap-near-breach-pct={nearBreach}
										>{formatPercent(exp.total_exposure_pct / 100)}</span>
										{#if exp.is_breach}
											<span class="overlap-breach-badge">BREACH</span>
										{:else if nearBreach}
											<span class="overlap-near-badge">NEAR</span>
										{/if}
									</td>
									<td class="overlap-funds-cell">{exp.funds_holding.join(", ")}</td>
								</tr>
							{/each}
						</tbody>
					</table>
					<p class="overlap-meta">
						{overlapData.funds_analyzed} funds analyzed &middot; {formatNumber(overlapData.total_holdings, 0)} total holdings
					</p>
				</div>
			{/if}
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
	{:else if activeTab === "reports"}
		<!-- ── REPORTS VIEW ───────────────────────────────────────────── -->
		{#if !modelPortfolio}
			<div class="pw-empty">No model portfolio found for this profile. Create one to generate reports.</div>
		{:else}
			<div class="reports-section">
				<!-- Fact Sheets -->
				<div class="reports-block">
					<h3 class="reports-block-title">Fact Sheets</h3>

					{#if fsError}
						<div class="reports-error">
							{fsError}
							<button class="reports-error-dismiss" onclick={() => fsError = null}>dismiss</button>
						</div>
					{/if}

					<div class="fs-generate-row">
						<select class="fs-lang-select" bind:value={fsLang}>
							<option value="pt">Portugu&ecirc;s</option>
							<option value="en">English</option>
						</select>
						<Button size="sm" onclick={generateFactSheet} disabled={fsGenerating}>
							{fsGenerating ? "Generating\u2026" : "Generate Fact Sheet"}
						</Button>
					</div>

					{#if factSheets.length === 0}
						<p class="reports-empty">No fact sheets generated yet.</p>
					{:else}
						<div class="fs-list">
							{#each factSheets as fs (fs.path)}
								<div class="fs-row">
									<div class="fs-info">
										<span class="fs-format">{fs.format}</span>
										<span class="fs-lang-badge">{fs.language.toUpperCase()}</span>
										<span class="fs-date">{fs.as_of}</span>
									</div>
									<Button
										size="sm"
										variant="outline"
										onclick={() => downloadFactSheet(fs.path)}
										disabled={fsDownloading === fs.path}
									>
										{fsDownloading === fs.path ? "\u2026" : "Download"}
									</Button>
								</div>
							{/each}
						</div>
					{/if}
				</div>

				<!-- Long-Form Report -->
				<div class="reports-block">
					<h3 class="reports-block-title">Long-Form DD Report</h3>
					<LongFormReportPanel
						portfolioId={modelPortfolio.id}
						portfolioName={modelPortfolio.display_name}
					/>
				</div>

				<!-- Monthly Report -->
				<div class="reports-block">
					<h3 class="reports-block-title">Monthly Client Report</h3>
					<MonthlyReportPanel
						portfolioId={modelPortfolio.id}
						portfolioName={modelPortfolio.display_name}
					/>
				</div>
			</div>
		{/if}
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
	/* ── CVaR History ────────────────────────────────────────────────────── */
	.pw-cvar-history,
	.pw-regime-timeline {
		margin: 0 var(--ii-space-inline-lg, 24px);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		overflow: hidden;
	}

	.pw-section-title {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	/* ── KPIs ─────────────────────────────────────────────────────────────── */
	.pw-kpis {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 1px;
		margin: 0 var(--ii-space-inline-lg, 24px);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		overflow: hidden;
		background: var(--ii-border-subtle);
	}

	.pw-kpi-card {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		background: var(--ii-surface-elevated);
	}

	.pw-kpi-label {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.pw-kpi-value {
		font-size: var(--ii-text-h4, 1.125rem);
		font-weight: 700;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.pw-kpi-value--date {
		font-size: var(--ii-text-body, 0.9375rem);
	}

	/* ── Tabs ─────────────────────────────────────────────────────────────── */
	.pw-tabs {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-2xs, 4px);
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-lg, 24px);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.pw-tab {
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-md, 16px);
		border: 1px solid transparent;
		border-radius: var(--ii-radius-sm, 8px);
		background: transparent;
		color: var(--ii-text-secondary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		transition: background-color 120ms ease, color 120ms ease;
	}

	.pw-tab:hover {
		background: var(--ii-surface-alt);
		color: var(--ii-text-primary);
	}

	.pw-tab--active {
		background: color-mix(in srgb, var(--ii-brand-primary) 10%, transparent);
		color: var(--ii-brand-primary);
		font-weight: 600;
	}

	:global(.pw-edit-btn) {
		margin-left: auto;
	}

	/* ── Actions bar ─────────────────────────────────────────────────────── */
	.pw-actions {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 8px);
	}

	.pw-regime-multiplier {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-warning);
		font-weight: 500;
	}

	.pw-cross-link {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--ii-brand-primary);
		text-decoration: none;
		padding: 4px 10px;
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-md, 6px);
		transition: background 120ms ease, border-color 120ms ease;
	}
	.pw-cross-link:hover {
		background: var(--ii-surface-alt);
		border-color: var(--ii-brand-primary);
	}

	.pw-trigger-badge {
		cursor: help;
	}

	.pw-trigger-badge--critical {
		animation: pw-pulse 2s ease-in-out infinite;
	}

	@keyframes pw-pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.7; }
	}

	.pw-error {
		margin: 0 var(--ii-space-inline-lg, 24px);
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 16px);
		border-radius: var(--ii-radius-sm, 8px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.pw-guidance-banner {
		margin: 0 var(--ii-space-inline-lg, 24px);
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-md, 8px);
		background: var(--ii-surface-alt);
	}

	.pw-guidance-text {
		margin: 0;
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-secondary);
	}

	.pw-guidance-link {
		color: var(--ii-brand-primary);
		font-weight: 600;
		text-decoration: none;
	}
	.pw-guidance-link:hover {
		text-decoration: underline;
	}

	.pw-empty {
		padding: var(--ii-space-stack-xl, 48px);
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	/* ── Content ──────────────────────────────────────────────────────────── */
	.pw-content {
		padding: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px);
	}

	/* ── Allocation tables ────────────────────────────────────────────────── */
	.alloc-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--ii-text-small, 0.8125rem);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-sm, 8px);
		overflow: hidden;
	}

	.alloc-table th {
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-sm, 12px);
		text-align: left;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.02em;
		background: var(--ii-surface-alt);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.alloc-table td {
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-sm, 12px);
		border-bottom: 1px solid var(--ii-border-subtle);
		vertical-align: middle;
	}

	.atd-block { font-weight: 500; color: var(--ii-text-primary); }
	.atd-weight { font-variant-numeric: tabular-nums; color: var(--ii-text-primary); }
	.atd-weight--bold { font-weight: 700; }
	.atd-bound { font-variant-numeric: tabular-nums; color: var(--ii-text-muted); font-size: var(--ii-text-label, 0.75rem); }
	.atd-date { color: var(--ii-text-muted); font-variant-numeric: tabular-nums; }
	.atd-delta { font-variant-numeric: tabular-nums; font-weight: 600; }
	.atd-current { font-variant-numeric: tabular-nums; color: var(--ii-text-secondary); }

	.atd-bar { width: 120px; }

	.weight-bar-track {
		height: 6px;
		background: var(--ii-surface-alt);
		border-radius: 3px;
		overflow: hidden;
	}

	.weight-bar-fill {
		height: 100%;
		background: var(--ii-brand-primary);
		border-radius: 3px;
		transition: width 200ms ease;
	}

	/* ── Editor ───────────────────────────────────────────────────────────── */
	.editor {
		border: 1px solid var(--ii-border-accent);
		border-radius: var(--ii-radius-md, 12px);
		overflow: hidden;
	}

	.editor-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.editor-total {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}

	.editor-total--valid { color: var(--ii-success); }
	.editor-total--invalid { color: var(--ii-danger); }

	.editor-hint {
		font-weight: 400;
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.editor-actions {
		display: flex;
		gap: var(--ii-space-inline-xs, 6px);
	}

	.ath-block { min-width: 180px; }
	.ath-current { width: 90px; text-align: right; }
	.ath-new { width: 120px; }
	.ath-delta { width: 80px; text-align: right; }
	.ath-bounds { width: 120px; }

	.atd-input {
		padding: 2px var(--ii-space-inline-sm, 12px);
	}

	.weight-input {
		width: 90px;
		height: var(--ii-space-control-height-sm, 32px);
		padding: 0 var(--ii-space-inline-xs, 8px);
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 6px);
		background: var(--ii-surface-elevated);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-family: var(--ii-font-mono);
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	.weight-input:focus {
		outline: none;
		border-color: var(--ii-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-brand-secondary) 20%, transparent);
	}

	.weight-input--oob {
		border-color: var(--ii-danger);
	}

	.alloc-row--oob {
		background: color-mix(in srgb, var(--ii-danger) 4%, transparent);
	}

	/* ── Expandable block rows ───────────────────────────────────────────── */
	.alloc-row-expandable--has-funds { cursor: pointer; }
	.alloc-row-expandable--has-funds:hover { background: var(--ii-surface-alt); }

	.atd-chevron {
		width: 28px;
		text-align: center;
		padding: 0 4px;
	}

	.row-chevron {
		display: inline-block;
		font-size: 9px;
		color: var(--ii-text-muted);
		transition: transform 150ms ease;
	}

	.row-chevron--open { transform: rotate(90deg); }

	.atd-count {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.alloc-row-fund td {
		background: var(--ii-surface-alt);
		padding: var(--ii-space-stack-2xs, 4px) var(--ii-space-inline-sm, 12px);
	}

	.atd-fund-name {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-secondary);
		padding-left: var(--ii-space-inline-md, 16px) !important;
	}

	.atd-fund-weight {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
	}

	.atd-fund-score {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.atd-score-badge {
		font-size: 11px;
		font-weight: 600;
		color: var(--ii-text-muted);
		background: var(--ii-surface-alt);
		padding: 2px 6px;
		border-radius: 4px;
	}

	.atd-fund-meta {
		color: var(--ii-text-muted);
	}

	/* ── Reports tab ─────────────────────────────────────────────────────── */
	.reports-section {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-lg, 24px);
	}

	.reports-block-title {
		margin: 0 0 var(--ii-space-stack-sm, 12px);
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.reports-error {
		margin-bottom: var(--ii-space-stack-sm, 12px);
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 16px);
		border-radius: var(--ii-radius-sm, 8px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.reports-error-dismiss {
		background: none;
		border: none;
		color: inherit;
		cursor: pointer;
		text-decoration: underline;
		font-size: var(--ii-text-label, 0.75rem);
		font-family: var(--ii-font-sans);
	}

	.reports-empty {
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
		margin: 0;
	}

	.fs-generate-row {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 8px);
		margin-bottom: var(--ii-space-stack-sm, 12px);
	}

	.fs-lang-select {
		height: var(--ii-space-control-height-sm, 32px);
		padding: 0 var(--ii-space-inline-sm, 8px);
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 6px);
		background: var(--ii-surface-elevated);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-family: var(--ii-font-sans);
	}

	.fs-list {
		display: flex;
		flex-direction: column;
		gap: 1px;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-sm, 8px);
		overflow: hidden;
		background: var(--ii-border-subtle);
	}

	.fs-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-md, 16px);
		background: var(--ii-surface-elevated);
	}

	.fs-info {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 8px);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.fs-format {
		font-weight: 500;
		color: var(--ii-text-primary);
		text-transform: capitalize;
	}

	.fs-lang-badge {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		background: var(--ii-surface-alt);
		padding: 1px 6px;
		border-radius: 4px;
	}

	.fs-date {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
	}

	/* ── Overlap tab ─────────────────────────────────────────────────────── */
	.overlap-empty {
		padding: var(--ii-space-stack-xl, 48px) var(--ii-space-inline-lg, 24px);
		text-align: center;
	}

	.overlap-empty-title {
		margin: 0 0 var(--ii-space-stack-xs, 8px);
		font-size: var(--ii-text-body, 0.9375rem);
		color: var(--ii-text-secondary);
		font-weight: 500;
	}

	.overlap-empty-detail {
		margin: 0;
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
	}

	.overlap-warning {
		margin-bottom: var(--ii-space-stack-md, 16px);
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 16px);
		border-radius: var(--ii-radius-sm, 8px);
		background: color-mix(in srgb, var(--ii-warning) 8%, transparent);
		color: var(--ii-warning);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.overlap-section {
		margin-bottom: var(--ii-space-stack-lg, 24px);
	}

	.overlap-section-title {
		margin: 0 0 var(--ii-space-stack-sm, 12px);
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.overlap-section-title--danger {
		color: var(--ii-danger);
	}

	.overlap-breach-row td {
		background: color-mix(in srgb, var(--ii-danger) 4%, transparent);
	}

	.overlap-breach-pct {
		color: var(--ii-danger);
		font-weight: 700;
	}

	.overlap-near-breach-pct {
		color: var(--ii-warning);
		font-weight: 600;
	}

	.overlap-breach-badge {
		display: inline-block;
		margin-left: 4px;
		padding: 0 4px;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 700;
		color: #fff;
		background: var(--ii-danger);
		border-radius: 3px;
		vertical-align: middle;
	}

	.overlap-near-badge {
		display: inline-block;
		margin-left: 4px;
		padding: 0 4px;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-warning);
		background: color-mix(in srgb, var(--ii-warning) 15%, transparent);
		border-radius: 3px;
		vertical-align: middle;
	}

	.overlap-funds-cell {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-secondary);
		max-width: 280px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.overlap-sectors {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-xs, 8px);
	}

	.overlap-sector-row {
		display: grid;
		grid-template-columns: 160px 60px 1fr;
		align-items: center;
		gap: var(--ii-space-inline-sm, 8px);
	}

	.overlap-sector-name {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--ii-text-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.overlap-sector-pct {
		font-size: var(--ii-text-small, 0.8125rem);
		font-variant-numeric: tabular-nums;
		text-align: right;
		color: var(--ii-text-primary);
		font-weight: 600;
	}

	.overlap-sector-bar-track {
		height: 8px;
		background: var(--ii-surface-alt);
		border-radius: 4px;
		overflow: hidden;
	}

	.overlap-sector-bar-fill {
		height: 100%;
		background: var(--ii-brand-primary);
		border-radius: 4px;
		transition: width 200ms ease;
	}

	.overlap-meta {
		margin: var(--ii-space-stack-sm, 12px) 0 0;
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	/* ── Responsive ──────────────────────────────────────────────────────── */
	@media (max-width: 768px) {
		.pw-kpis {
			grid-template-columns: 1fr 1fr;
		}
	}
</style>
