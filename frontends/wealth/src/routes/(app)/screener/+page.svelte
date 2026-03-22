<!--
  Unified Screener — Hierarchical Manager → Fund table.
  Left sidebar: manager filters + fund screening funnel.
  Right surface: L1 manager rows → L2 fund sub-rows (expandable).
  Peer comparison mode + 4-tab manager detail + fund detail panel.
-->
<script lang="ts">
	import { getContext, untrack } from "svelte";
	import { goto, invalidateAll } from "$app/navigation";
	import { page } from "$app/stores";
	import {
		PageHeader, Button, ContextPanel, StatusBadge, ConsequenceDialog,
		formatAUM, formatNumber, formatPercent, formatDate, formatDateTime,
	} from "@netz/ui";
	import type { ConsequenceDialogPayload } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type {
		ScreeningResult, ScreeningRun, CriterionResult,
		ScreenerFilterConfig, OverallStatus,
	} from "$lib/types/screening";
	import { EMPTY_FILTERS } from "$lib/types/screening";
	import type {
		ManagerRow, ScreenerPage, ManagerProfile, HoldingsData,
		InstitutionalData, UniverseStatus, CompareResult, DetailTab,
	} from "$lib/types/manager-screener";
	import { EMPTY_SCREENER } from "$lib/types/manager-screener";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	// ── SSR data ──────────────────────────────────────────────────────────
	let screener = $derived((data.screener ?? EMPTY_SCREENER) as ScreenerPage);
	let results = $derived((data.results ?? []) as ScreeningResult[]);
	let lastRun = $derived(data.lastRun as ScreeningRun | null);

	// ── Manager filter state ──────────────────────────────────────────────
	const initParams = (untrack(() => data.currentParams) as Record<string, string>) ?? {};
	let textSearch = $state(initParams.text_search ?? "");
	let aumMin = $state(initParams.aum_min ?? "");
	let aumMax = $state(initParams.aum_max ?? "");
	let complianceClean = $state(initParams.compliance_clean === "true");
	let hasInstitutional = $state(initParams.has_institutional_holders === "true");

	function applyManagerFilters() {
		const params = new URLSearchParams();
		if (textSearch) params.set("text_search", textSearch);
		if (aumMin) params.set("aum_min", aumMin);
		if (aumMax) params.set("aum_max", aumMax);
		if (complianceClean) params.set("compliance_clean", "true");
		if (hasInstitutional) params.set("has_institutional_holders", "true");
		params.set("page", "1");
		params.set("page_size", "25");
		goto(`/screener?${params.toString()}`, { invalidateAll: true });
	}

	function clearManagerFilters() {
		textSearch = "";
		aumMin = "";
		aumMax = "";
		complianceClean = false;
		hasInstitutional = false;
		goto("/screener", { invalidateAll: true });
	}

	function goToPage(p: number) {
		const params = new URLSearchParams($page.url.searchParams);
		params.set("page", String(p));
		goto(`/screener?${params.toString()}`, { invalidateAll: true });
	}

	function handleFilterKeydown(e: KeyboardEvent) {
		if (e.key === "Enter") applyManagerFilters();
	}

	// ── Fund filter state ─────────────────────────────────────────────────
	let fundFilters = $state<ScreenerFilterConfig>({ ...EMPTY_FILTERS });

	let distinctTypes = $derived(
		[...new Set(results.map((r) => r.instrument_type).filter(Boolean))] as string[]
	);
	let distinctBlocks = $derived(
		[...new Set(results.map((r) => r.block_id).filter(Boolean))] as string[]
	);

	let filteredResults = $derived.by(() => {
		let rows = results;
		if (fundFilters.status) rows = rows.filter((r) => r.overall_status === fundFilters.status);
		if (fundFilters.instrument_type) rows = rows.filter((r) => r.instrument_type === fundFilters.instrument_type);
		if (fundFilters.block_id) rows = rows.filter((r) => r.block_id === fundFilters.block_id);
		if (fundFilters.search) {
			const q = fundFilters.search.toLowerCase();
			rows = rows.filter((r) =>
				(r.name?.toLowerCase().includes(q)) ||
				(r.isin?.toLowerCase().includes(q)) ||
				(r.ticker?.toLowerCase().includes(q)) ||
				(r.manager?.toLowerCase().includes(q))
			);
		}
		return rows;
	});

	// Funnel counts
	let universeCount = $derived(results.length);
	let l1PassCount = $derived(results.filter((r) => r.failed_at_layer !== 1).length);
	let l2EligibleCount = $derived(
		results.filter((r) => r.failed_at_layer !== 1 && r.failed_at_layer !== 2).length
	);
	let passCount = $derived(results.filter((r) => r.overall_status === "PASS").length);
	let watchlistCount = $derived(results.filter((r) => r.overall_status === "WATCHLIST").length);
	let failCount = $derived(results.filter((r) => r.overall_status === "FAIL").length);

	function setStatusFilter(status: OverallStatus | null) {
		fundFilters.status = status;
	}

	function clearFundFilters() {
		fundFilters = { ...EMPTY_FILTERS };
	}

	const hasFundFilters = $derived(
		fundFilters.status !== null ||
		fundFilters.instrument_type !== null ||
		fundFilters.block_id !== null ||
		fundFilters.search !== ""
	);

	// ── Expand / collapse managers ────────────────────────────────────────
	let expandedManagers = $state<Set<string>>(new Set());

	function toggleExpand(crd: string) {
		const next = new Set(expandedManagers);
		if (next.has(crd)) {
			next.delete(crd);
		} else {
			next.add(crd);
		}
		expandedManagers = next;
	}

	// ── Selection (peer comparison) ───────────────────────────────────────
	let selectedManagers = $state<Set<string>>(new Set());

	function toggleSelection(crd: string) {
		const next = new Set(selectedManagers);
		if (next.has(crd)) {
			next.delete(crd);
		} else if (next.size < 5) {
			next.add(crd);
		}
		selectedManagers = next;
	}

	let selectionCount = $derived(selectedManagers.size);
	let canCompare = $derived(selectionCount >= 2 && selectionCount <= 5);

	// ── Peer comparison ───────────────────────────────────────────────────
	let compareResult = $state<CompareResult | null>(null);
	let comparing = $state(false);
	let compareError = $state<string | null>(null);

	async function runCompare() {
		if (!canCompare) return;
		comparing = true;
		compareError = null;
		try {
			const api = createClientApiClient(getToken);
			compareResult = await api.post<CompareResult>("/manager-screener/managers/compare", {
				crd_numbers: Array.from(selectedManagers),
			});
		} catch (e) {
			compareError = e instanceof Error ? e.message : "Compare failed";
		} finally {
			comparing = false;
		}
	}

	function clearCompare() {
		selectedManagers = new Set();
		compareResult = null;
	}

	let compareSectors = $derived.by(() => {
		if (!compareResult?.sector_allocations) return [];
		const all = new Set<string>();
		for (const alloc of Object.values(compareResult.sector_allocations)) {
			for (const s of Object.keys(alloc)) all.add(s);
		}
		return [...all].sort();
	});

	// ── Panel state (manager detail OR fund detail) ───────────────────────
	let panelMode = $state<"manager" | "fund" | null>(null);
	let panelOpen = $state(false);

	// Manager detail
	let panelCrd = $state<string | null>(null);
	let panelFirm = $state("");
	let activeTab = $state<DetailTab>("profile");
	let detailLoading = $state(false);
	let profileData = $state<ManagerProfile | null>(null);
	let holdingsData = $state<HoldingsData | null>(null);
	let institutionalData = $state<InstitutionalData | null>(null);
	let universeData = $state<UniverseStatus | null>(null);

	// Fund detail
	let selectedFund = $state<ScreeningResult | null>(null);

	async function openManagerDetail(manager: ManagerRow) {
		panelMode = "manager";
		panelCrd = manager.crd_number;
		panelFirm = manager.firm_name;
		panelOpen = true;
		activeTab = "profile";
		profileData = null;
		holdingsData = null;
		institutionalData = null;
		universeData = null;
		await fetchTab("profile");
	}

	function openFundDetail(fund: ScreeningResult) {
		panelMode = "fund";
		selectedFund = fund;
		panelOpen = true;
	}

	function closePanel() {
		panelOpen = false;
		panelMode = null;
		panelCrd = null;
		selectedFund = null;
	}

	async function fetchTab(tab: DetailTab) {
		if (!panelCrd) return;
		activeTab = tab;
		detailLoading = true;
		try {
			const api = createClientApiClient(getToken);
			switch (tab) {
				case "profile":
					if (!profileData) profileData = await api.get<ManagerProfile>(`/manager-screener/managers/${panelCrd}/profile`);
					break;
				case "holdings":
					if (!holdingsData) holdingsData = await api.get<HoldingsData>(`/manager-screener/managers/${panelCrd}/holdings`);
					break;
				case "institutional":
					if (!institutionalData) institutionalData = await api.get<InstitutionalData>(`/manager-screener/managers/${panelCrd}/institutional`);
					break;
				case "universe":
					if (!universeData) universeData = await api.get<UniverseStatus>(`/manager-screener/managers/${panelCrd}/universe-status`);
					break;
			}
		} catch {
			// silent — panel shows "no data"
		} finally {
			detailLoading = false;
		}
	}

	// ── Add to Universe ───────────────────────────────────────────────────
	let addDialogOpen = $state(false);
	let addAssetClass = $state("hedge_fund");
	let addGeography = $state("Global");
	let addCurrency = $state("USD");
	let adding = $state(false);
	let addError = $state<string | null>(null);

	async function handleAddToUniverse(payload: ConsequenceDialogPayload) {
		if (!panelCrd) return;
		adding = true;
		addError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/manager-screener/managers/${panelCrd}/add-to-universe`, {
				asset_class: addAssetClass,
				geography: addGeography,
				currency: addCurrency,
			});
			addDialogOpen = false;
			universeData = await api.get<UniverseStatus>(`/manager-screener/managers/${panelCrd}/universe-status`);
			await invalidateAll();
		} catch (e) {
			addError = e instanceof Error ? e.message : "Failed to add";
		} finally {
			adding = false;
		}
	}

	// ── Batch screening execution ─────────────────────────────────────────
	let isRunning = $state(false);
	let runError = $state<string | null>(null);

	async function executeBatch() {
		isRunning = true;
		runError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post("/screener/run", {});
			await invalidateAll();
		} catch (e) {
			runError = e instanceof Error ? e.message : "Failed to execute screening";
		} finally {
			isRunning = false;
		}
	}

	// ── Helpers ───────────────────────────────────────────────────────────
	function instrumentLabel(r: ScreeningResult): string {
		return r.name ?? r.instrument_id.slice(0, 8).toUpperCase();
	}

	function typeLabel(type: string | undefined): string {
		switch (type) {
			case "fund":   return "Fund";
			case "bond":   return "Fixed Income";
			case "equity": return "Equity";
			default:       return type ?? "—";
		}
	}

	function layerDotStatus(r: ScreeningResult, layer: number): "pass" | "fail" | "none" {
		if (r.failed_at_layer === layer) return "fail";
		if (r.failed_at_layer !== null && r.failed_at_layer < layer) return "none";
		return "pass";
	}

	function scoreColor(score: number | null): string {
		if (score === null) return "var(--netz-text-muted)";
		if (score >= 0.7) return "var(--netz-success)";
		if (score >= 0.4) return "var(--netz-warning)";
		return "var(--netz-danger)";
	}

	function ddLabel(type: string): string {
		switch (type) {
			case "dd_report":  return "DD Report";
			case "bond_brief": return "Bond Brief";
			case "none":       return "—";
			default:           return type;
		}
	}

	function layerCriteria(r: ScreeningResult, layer: number): CriterionResult[] {
		return r.layer_results.filter((c) => c.layer === layer);
	}

	function fundSubRows(crd: string): ScreeningResult[] {
		return filteredResults.filter((r) => r.manager_crd === crd);
	}

	function isLastFund(crd: string, idx: number): boolean {
		const funds = fundSubRows(crd);
		return idx === funds.length - 1;
	}

	let panelTitle = $derived.by(() => {
		if (panelMode === "manager") return panelFirm;
		if (panelMode === "fund" && selectedFund) return instrumentLabel(selectedFund);
		return "";
	});
</script>

<PageHeader title="Screener">
	{#snippet actions()}
		<div class="scr-actions">
			{#if canCompare}
				<Button size="sm" onclick={runCompare} disabled={comparing}>
					{comparing ? "Comparing…" : `Compare ${selectionCount}`}
				</Button>
			{/if}
			{#if selectionCount > 0}
				<Button size="sm" variant="ghost" onclick={clearCompare}>Clear</Button>
			{/if}
			<Button size="sm" onclick={executeBatch} disabled={isRunning}>
				{isRunning ? "Running…" : "Run Screening"}
			</Button>
		</div>
	{/snippet}
</PageHeader>

<div class="scr-grid">
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- LEFT: FILTER PANEL                                                 -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<aside class="scr-filters">
		<!-- Manager filters -->
		<div class="scr-filter-section">
			<h3 class="scr-filter-title">Manager</h3>
			<div class="scr-field">
				<input class="scr-input" type="text" placeholder="Firm name…" bind:value={textSearch} onkeydown={handleFilterKeydown} />
			</div>
			<div class="scr-field-row">
				<input class="scr-input scr-input--half" type="number" placeholder="AUM min" bind:value={aumMin} onkeydown={handleFilterKeydown} />
				<input class="scr-input scr-input--half" type="number" placeholder="AUM max" bind:value={aumMax} onkeydown={handleFilterKeydown} />
			</div>
			<label class="scr-checkbox">
				<input type="checkbox" bind:checked={complianceClean} />
				<span>Compliance clean</span>
			</label>
			<label class="scr-checkbox">
				<input type="checkbox" bind:checked={hasInstitutional} />
				<span>Has institutional holders</span>
			</label>
			<div class="scr-filter-btns">
				<Button size="sm" onclick={applyManagerFilters}>Apply</Button>
				<Button size="sm" variant="ghost" onclick={clearManagerFilters}>Clear</Button>
			</div>
		</div>

		<!-- Fund screening funnel -->
		<div class="scr-filter-section">
			<h3 class="scr-filter-title">Screening Funnel</h3>
			<div class="funnel">
				<div class="funnel-row">
					<span class="funnel-label">Universe</span>
					<span class="funnel-value">{universeCount}</span>
				</div>
				<div class="funnel-bar" style:--fill="100%"></div>

				<div class="funnel-row">
					<span class="funnel-label">L1 Passed</span>
					<span class="funnel-value">{l1PassCount}</span>
				</div>
				<div class="funnel-bar" style:--fill="{universeCount ? (l1PassCount / universeCount) * 100 : 0}%"></div>

				<div class="funnel-row">
					<span class="funnel-label">L2 Eligible</span>
					<span class="funnel-value">{l2EligibleCount}</span>
				</div>
				<div class="funnel-bar" style:--fill="{universeCount ? (l2EligibleCount / universeCount) * 100 : 0}%"></div>

				<div class="funnel-row funnel-row--outcomes">
					<button
						class="funnel-outcome"
						class:funnel-outcome--active={fundFilters.status === "PASS"}
						onclick={() => setStatusFilter(fundFilters.status === "PASS" ? null : "PASS")}
					>
						<span class="funnel-dot funnel-dot--pass"></span>
						<span>Pass</span>
						<span class="funnel-count">{passCount}</span>
					</button>
					<button
						class="funnel-outcome"
						class:funnel-outcome--active={fundFilters.status === "WATCHLIST"}
						onclick={() => setStatusFilter(fundFilters.status === "WATCHLIST" ? null : "WATCHLIST")}
					>
						<span class="funnel-dot funnel-dot--watchlist"></span>
						<span>Watch</span>
						<span class="funnel-count">{watchlistCount}</span>
					</button>
					<button
						class="funnel-outcome"
						class:funnel-outcome--active={fundFilters.status === "FAIL"}
						onclick={() => setStatusFilter(fundFilters.status === "FAIL" ? null : "FAIL")}
					>
						<span class="funnel-dot funnel-dot--fail"></span>
						<span>Fail</span>
						<span class="funnel-count">{failCount}</span>
					</button>
				</div>
			</div>
		</div>

		<!-- Fund filters -->
		<div class="scr-filter-section">
			<h3 class="scr-filter-title">Fund Filters</h3>
			<div class="scr-field">
				<label class="scr-label" for="scr-fund-search">Search</label>
				<input
					id="scr-fund-search"
					type="text"
					class="scr-input"
					placeholder="Name, ISIN, ticker…"
					bind:value={fundFilters.search}
				/>
			</div>
			<div class="scr-field">
				<label class="scr-label" for="scr-fund-type">Instrument Type</label>
				<select id="scr-fund-type" class="scr-select" bind:value={fundFilters.instrument_type}>
					<option value={null}>All types</option>
					{#each distinctTypes as t (t)}
						<option value={t}>{typeLabel(t)}</option>
					{/each}
				</select>
			</div>
			<div class="scr-field">
				<label class="scr-label" for="scr-fund-block">Allocation Block</label>
				<select id="scr-fund-block" class="scr-select" bind:value={fundFilters.block_id}>
					<option value={null}>All blocks</option>
					{#each distinctBlocks as b (b)}
						<option value={b}>{b}</option>
					{/each}
				</select>
			</div>
			{#if hasFundFilters}
				<button class="scr-clear-btn" onclick={clearFundFilters}>Clear fund filters</button>
			{/if}
		</div>

		<!-- Last run -->
		{#if lastRun}
			<div class="scr-filter-section scr-filter-section--meta">
				<h3 class="scr-filter-title">Last Run</h3>
				<div class="scr-meta-row">
					<span class="scr-meta-k">Status</span>
					<StatusBadge status={lastRun.status} />
				</div>
				<div class="scr-meta-row">
					<span class="scr-meta-k">Instruments</span>
					<span class="scr-meta-v">{formatNumber(lastRun.instrument_count)}</span>
				</div>
				<div class="scr-meta-row">
					<span class="scr-meta-k">Started</span>
					<span class="scr-meta-v">{formatDateTime(lastRun.started_at)}</span>
				</div>
				{#if lastRun.completed_at}
					<div class="scr-meta-row">
						<span class="scr-meta-k">Completed</span>
						<span class="scr-meta-v">{formatDateTime(lastRun.completed_at)}</span>
					</div>
				{/if}
			</div>
		{/if}

		{#if runError}
			<div class="scr-filter-error">{runError}</div>
		{/if}
	</aside>

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- RIGHT: DATA SURFACE                                                -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<section class="scr-main">
		{#if compareResult}
			<!-- ── PEER COMPARISON VIEW ──────────────────────────── -->
			<div class="cmp-view">
				<div class="cmp-header">
					<h3 class="cmp-title">Peer Comparison</h3>
					<span class="cmp-overlap">
						Portfolio Overlap (Jaccard): <strong>{(compareResult.jaccard_overlap * 100).toFixed(1)}%</strong>
					</span>
					<Button size="sm" variant="ghost" onclick={clearCompare}>Back to list</Button>
				</div>

				<div class="cmp-cards">
					{#each compareResult.managers as mgr (mgr.crd_number)}
						<div class="cmp-card">
							<span class="cmp-card-name">{mgr.firm_name}</span>
							<span class="cmp-card-aum">{mgr.aum_total ? formatAUM(mgr.aum_total) : "—"}</span>
							<span class="cmp-card-crd">CRD {mgr.crd_number}</span>
						</div>
					{/each}
				</div>

				{#if compareSectors.length > 0}
					<div class="cmp-sectors">
						<h4 class="cmp-subtitle">Sector Allocation</h4>
						<div class="cmp-sg">
							<div class="cmp-sg-header">
								<span class="cmp-sg-label">Sector</span>
								{#each compareResult.managers as mgr (mgr.crd_number)}
									<span class="cmp-sg-mgr">{mgr.firm_name.slice(0, 12)}</span>
								{/each}
							</div>
							{#each compareSectors as sector (sector)}
								<div class="cmp-sg-row">
									<span class="cmp-sg-label">{sector}</span>
									{#each compareResult.managers as mgr (mgr.crd_number)}
										{@const alloc = compareResult.sector_allocations[mgr.crd_number] ?? {}}
										{@const pct = alloc[sector] ?? 0}
										<div class="cmp-sg-cell">
											<div class="cmp-sg-bar-track">
												<div class="cmp-sg-bar-fill" style:width="{pct * 100}%"></div>
											</div>
											<span class="cmp-sg-pct">{(pct * 100).toFixed(1)}%</span>
										</div>
									{/each}
								</div>
							{/each}
						</div>
					</div>
				{/if}
			</div>
		{:else}
			<!-- ── HIERARCHICAL TABLE ────────────────────────────── -->
			<div class="scr-data-header">
				<span class="scr-data-count">
					{screener.total_count} manager{screener.total_count !== 1 ? "s" : ""}
					{#if hasFundFilters}
						<span class="scr-data-count-muted">· {filteredResults.length} fund{filteredResults.length !== 1 ? "s" : ""}</span>
					{/if}
				</span>
			</div>

			{#if screener.managers.length === 0}
				<div class="scr-empty">No managers found. Adjust filters or search.</div>
			{:else}
				<div class="scr-table-wrap">
					<table class="scr-table">
						<thead>
							<tr>
								<th class="sth-check"></th>
								<th class="sth-expand"></th>
								<th class="sth-name">Firm / Fund</th>
								<th class="sth-aum">AUM</th>
								<th class="sth-loc">Location</th>
								<th class="sth-layers">L1</th>
								<th class="sth-layers">L2</th>
								<th class="sth-layers">L3</th>
								<th class="sth-score">Score</th>
								<th class="sth-status">Status</th>
								<th class="sth-univ">Universe</th>
							</tr>
						</thead>
						<tbody>
							{#each screener.managers as manager (manager.crd_number)}
								<!-- Level 1: Manager row -->
								<tr
									class="scr-mgr-row"
									class:scr-mgr-row--selected={selectedManagers.has(manager.crd_number)}
									class:scr-mgr-row--expanded={expandedManagers.has(manager.crd_number)}
									onclick={() => openManagerDetail(manager)}
								>
									<td class="std-check" onclick={(e) => e.stopPropagation()}>
										<input
											type="checkbox"
											checked={selectedManagers.has(manager.crd_number)}
											onchange={() => toggleSelection(manager.crd_number)}
										/>
									</td>
									<td class="std-expand" onclick={(e) => { e.stopPropagation(); toggleExpand(manager.crd_number); }}>
										<span class="expand-chevron" class:expand-chevron--open={expandedManagers.has(manager.crd_number)}>&#9654;</span>
									</td>
									<td class="std-name">
										<span class="mgr-name">{manager.firm_name}</span>
										<span class="mgr-crd">CRD {manager.crd_number}</span>
									</td>
									<td class="std-aum">{manager.aum_total ? formatAUM(manager.aum_total) : "—"}</td>
									<td class="std-loc">{manager.state ?? ""}{manager.state && manager.country ? ", " : ""}{manager.country ?? ""}</td>
									<td class="std-layer"></td>
									<td class="std-layer"></td>
									<td class="std-layer"></td>
									<td class="std-score"></td>
									<td class="std-status">
										{#if manager.compliance_disclosures !== null && manager.compliance_disclosures > 0}
											<span class="mgr-disclosures">{manager.compliance_disclosures} disc.</span>
										{/if}
									</td>
									<td class="std-univ">
										{#if manager.universe_status}
											<StatusBadge status={manager.universe_status} />
										{:else}
											<span class="mgr-not-added">—</span>
										{/if}
									</td>
								</tr>

								<!-- Level 2: Fund sub-rows -->
								{#if expandedManagers.has(manager.crd_number)}
									{#each fundSubRows(manager.crd_number) as fund, idx (fund.instrument_id)}
										<tr class="scr-fund-row" onclick={() => openFundDetail(fund)}>
											<td></td>
											<td></td>
											<td class="std-name std-name--nested">
												<span class="nest-char">{isLastFund(manager.crd_number, idx) ? "└─" : "├─"}</span>
												<span class="fund-name">{instrumentLabel(fund)}</span>
											</td>
											<td class="std-aum">{fund.aum ? formatAUM(fund.aum) : "—"}</td>
											<td class="std-loc">
												<span class="fund-type-badge fund-type-badge--{fund.instrument_type ?? 'other'}">
													{typeLabel(fund.instrument_type)}
												</span>
											</td>
											<td class="std-layer">
												<span class="layer-dot layer-dot--{layerDotStatus(fund, 1)}"></span>
											</td>
											<td class="std-layer">
												<span class="layer-dot layer-dot--{layerDotStatus(fund, 2)}"></span>
											</td>
											<td class="std-layer">
												<span class="layer-dot layer-dot--{layerDotStatus(fund, 3)}"></span>
											</td>
											<td class="std-score">
												{#if fund.score !== null}
													<span style:color={scoreColor(fund.score)}>{formatPercent(fund.score)}</span>
												{:else}
													<span class="score-na">—</span>
												{/if}
											</td>
											<td class="std-status">
												<StatusBadge status={fund.overall_status} />
											</td>
											<td class="std-univ">
												{ddLabel(fund.required_analysis_type)}
											</td>
										</tr>
									{:else}
										<tr class="scr-fund-row scr-fund-row--empty">
											<td></td>
											<td></td>
											<td class="std-name std-name--nested" colspan="9">
												<span class="nest-char">└─</span>
												<span class="fund-empty-text">No screened funds for this manager</span>
											</td>
										</tr>
									{/each}
								{/if}
							{/each}
						</tbody>
					</table>
				</div>

				<!-- Pagination -->
				<div class="scr-pagination">
					<button class="scr-page-btn" disabled={screener.page <= 1} onclick={() => goToPage(screener.page - 1)}>Previous</button>
					<span class="scr-page-info">Page {screener.page} · {screener.total_count} total</span>
					<button class="scr-page-btn" disabled={!screener.has_next} onclick={() => goToPage(screener.page + 1)}>Next</button>
				</div>
			{/if}
		{/if}

		{#if compareError}
			<div class="scr-error">{compareError}</div>
		{/if}
	</section>
</div>

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- CONTEXT PANEL — Manager detail (4 tabs) OR Fund detail                 -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
<ContextPanel open={panelOpen} onClose={closePanel} title={panelTitle} width={panelMode === "manager" ? "480px" : "420px"}>
	{#if panelMode === "manager" && panelCrd}
		<!-- Tab bar -->
		<div class="dt-tabs">
			{#each (["profile", "holdings", "institutional", "universe"] as DetailTab[]) as tab (tab)}
				<button
					class="dt-tab"
					class:dt-tab--active={activeTab === tab}
					onclick={() => fetchTab(tab)}
				>
					{tab.charAt(0).toUpperCase() + tab.slice(1)}
				</button>
			{/each}
		</div>

		<div class="dt-content">
			{#if detailLoading}
				<div class="dt-loading">Loading…</div>
			{:else}
				{#if activeTab === "profile"}
					{@render profileTab()}
				{:else if activeTab === "holdings"}
					{@render holdingsTab()}
				{:else if activeTab === "institutional"}
					{@render institutionalTab()}
				{:else if activeTab === "universe"}
					{@render universeTab()}
				{/if}
			{/if}
		</div>
	{:else if panelMode === "fund" && selectedFund}
		{@render fundDetailPanel()}
	{/if}
</ContextPanel>

<!-- ── Manager tab snippets ────────────────────────────────────────────── -->

{#snippet profileTab()}
	{#if profileData}
		<div class="dt-section">
			<div class="dt-kv"><span class="dt-k">CRD</span><span class="dt-v">{profileData.crd_number}</span></div>
			{#if profileData.cik}<div class="dt-kv"><span class="dt-k">CIK</span><span class="dt-v">{profileData.cik}</span></div>{/if}
			<div class="dt-kv"><span class="dt-k">Status</span><StatusBadge status={profileData.registration_status ?? "—"} /></div>
			<div class="dt-kv"><span class="dt-k">AUM Total</span><span class="dt-v">{profileData.aum_total ? formatAUM(profileData.aum_total) : "—"}</span></div>
			<div class="dt-kv"><span class="dt-k">Discretionary</span><span class="dt-v">{profileData.aum_discretionary ? formatAUM(profileData.aum_discretionary) : "—"}</span></div>
			<div class="dt-kv"><span class="dt-k">Accounts</span><span class="dt-v">{profileData.total_accounts ?? "—"}</span></div>
			<div class="dt-kv"><span class="dt-k">Location</span><span class="dt-v">{profileData.state ?? ""}{profileData.state && profileData.country ? ", " : ""}{profileData.country ?? ""}</span></div>
			{#if profileData.website}<div class="dt-kv"><span class="dt-k">Website</span><span class="dt-v">{profileData.website}</span></div>{/if}
			<div class="dt-kv"><span class="dt-k">Disclosures</span><span class="dt-v">{profileData.compliance_disclosures ?? 0}</span></div>
			{#if profileData.last_adv_filed_at}<div class="dt-kv"><span class="dt-k">Last ADV</span><span class="dt-v">{formatDate(profileData.last_adv_filed_at)}</span></div>{/if}
		</div>
		{#if profileData.funds.length > 0}
			<div class="dt-section">
				<h4 class="dt-section-title">Funds ({profileData.funds.length})</h4>
				{#each profileData.funds as fund (fund.fund_name)}
					<div class="dt-list-row">
						<span class="dt-list-name">{fund.fund_name}</span>
						<span class="dt-list-meta">{fund.fund_type ?? ""} · {fund.gross_asset_value ? formatAUM(fund.gross_asset_value) : "—"}</span>
					</div>
				{/each}
			</div>
		{/if}
		{#if profileData.team.length > 0}
			<div class="dt-section">
				<h4 class="dt-section-title">Team ({profileData.team.length})</h4>
				{#each profileData.team as member (member.person_name)}
					<div class="dt-list-row">
						<span class="dt-list-name">{member.person_name}</span>
						<span class="dt-list-meta">{member.title ?? member.role ?? ""}</span>
					</div>
				{/each}
			</div>
		{/if}
	{:else}
		<div class="dt-empty">No profile data.</div>
	{/if}
{/snippet}

{#snippet holdingsTab()}
	{#if holdingsData}
		<div class="dt-section">
			<div class="dt-kv"><span class="dt-k">HHI</span><span class="dt-v">{holdingsData.hhi?.toFixed(3) ?? "—"}</span></div>
		</div>
		{#if Object.keys(holdingsData.sector_allocation).length > 0}
			<div class="dt-section">
				<h4 class="dt-section-title">Sector Allocation</h4>
				{#each Object.entries(holdingsData.sector_allocation).sort((a, b) => b[1] - a[1]) as [sector, weight] (sector)}
					<div class="dt-alloc-row">
						<span class="dt-alloc-name">{sector}</span>
						<div class="dt-alloc-bar-track">
							<div class="dt-alloc-bar-fill" style:width="{weight * 100}%"></div>
						</div>
						<span class="dt-alloc-pct">{(weight * 100).toFixed(1)}%</span>
					</div>
				{/each}
			</div>
		{/if}
		{#if holdingsData.top_holdings.length > 0}
			<div class="dt-section">
				<h4 class="dt-section-title">Top Holdings</h4>
				{#each holdingsData.top_holdings as h (h.cusip)}
					<div class="dt-list-row">
						<span class="dt-list-name">{h.issuer_name}</span>
						<span class="dt-list-meta">{h.sector ?? ""} · {h.weight ? formatPercent(h.weight) : "—"}</span>
					</div>
				{/each}
			</div>
		{/if}
	{:else}
		<div class="dt-empty">No holdings data.</div>
	{/if}
{/snippet}

{#snippet institutionalTab()}
	{#if institutionalData}
		<div class="dt-section">
			<div class="dt-kv"><span class="dt-k">Coverage</span><StatusBadge status={institutionalData.coverage_type} /></div>
		</div>
		{#if institutionalData.holders.length > 0}
			<div class="dt-section">
				<h4 class="dt-section-title">Institutional Holders ({institutionalData.holders.length})</h4>
				{#each institutionalData.holders as holder (holder.filer_cik)}
					<div class="dt-list-row">
						<span class="dt-list-name">{holder.filer_name}</span>
						<span class="dt-list-meta">{holder.filer_type ?? ""} · {holder.market_value ? formatAUM(holder.market_value) : "—"}</span>
					</div>
				{/each}
			</div>
		{:else}
			<div class="dt-empty">No institutional holders found.</div>
		{/if}
	{:else}
		<div class="dt-empty">No institutional data.</div>
	{/if}
{/snippet}

{#snippet universeTab()}
	{#if universeData?.instrument_id}
		<div class="dt-section">
			<div class="dt-kv"><span class="dt-k">Status</span><StatusBadge status={universeData.approval_status ?? "—"} /></div>
			<div class="dt-kv"><span class="dt-k">Asset Class</span><span class="dt-v">{universeData.asset_class ?? "—"}</span></div>
			<div class="dt-kv"><span class="dt-k">Geography</span><span class="dt-v">{universeData.geography ?? "—"}</span></div>
			<div class="dt-kv"><span class="dt-k">Currency</span><span class="dt-v">{universeData.currency ?? "—"}</span></div>
			{#if universeData.added_at}<div class="dt-kv"><span class="dt-k">Added</span><span class="dt-v">{formatDate(universeData.added_at)}</span></div>{/if}
		</div>
	{:else}
		<div class="dt-section">
			<p class="dt-empty-text">Not yet added to universe.</p>
			<div class="dt-add-form">
				<div class="dt-add-field">
					<label class="dt-add-label" for="add-asset-class">Asset Class</label>
					<select id="add-asset-class" class="dt-add-select" bind:value={addAssetClass}>
						<option value="hedge_fund">Hedge Fund</option>
						<option value="equity">Equity</option>
						<option value="fixed_income">Fixed Income</option>
					</select>
				</div>
				<div class="dt-add-field">
					<label class="dt-add-label" for="add-geography">Geography</label>
					<select id="add-geography" class="dt-add-select" bind:value={addGeography}>
						<option value="Global">Global</option>
						<option value="US">US</option>
						<option value="EU">EU</option>
						<option value="APAC">APAC</option>
						<option value="LATAM">LATAM</option>
					</select>
				</div>
				<div class="dt-add-field">
					<label class="dt-add-label" for="add-currency">Currency</label>
					<select id="add-currency" class="dt-add-select" bind:value={addCurrency}>
						<option value="USD">USD</option>
						<option value="EUR">EUR</option>
						<option value="GBP">GBP</option>
						<option value="BRL">BRL</option>
					</select>
				</div>
				<Button size="sm" onclick={() => addDialogOpen = true}>Add to Universe</Button>
				{#if addError}
					<span class="dt-add-error">{addError}</span>
				{/if}
			</div>
		</div>
	{/if}
{/snippet}

<!-- ── Fund detail snippet ─────────────────────────────────────────────── -->

{#snippet fundDetailPanel()}
	{#if selectedFund}
		<div class="dt-section">
			<div class="dt-header-row">
				<StatusBadge status={selectedFund.overall_status} />
				{#if selectedFund.score !== null}
					<span class="dt-score" style:color={scoreColor(selectedFund.score)}>
						Score: {formatPercent(selectedFund.score)}
					</span>
				{/if}
			</div>
			<div class="dt-fund-meta">
				{#if selectedFund.isin}<span>ISIN: {selectedFund.isin}</span>{/if}
				{#if selectedFund.ticker}<span>Ticker: {selectedFund.ticker}</span>{/if}
				{#if selectedFund.instrument_type}<span>Type: {typeLabel(selectedFund.instrument_type)}</span>{/if}
				{#if selectedFund.manager}<span>Manager: {selectedFund.manager}</span>{/if}
				<span>Screened: {formatDateTime(selectedFund.screened_at)}</span>
				<span>Next: {ddLabel(selectedFund.required_analysis_type)}</span>
			</div>
		</div>

		{#each [1, 2, 3] as layer (layer)}
			{@const criteria = layerCriteria(selectedFund, layer)}
			{#if criteria.length > 0}
				<div class="dt-layer">
					<h4 class="dt-layer-title">
						<span class="layer-dot layer-dot--{layerDotStatus(selectedFund, layer)}"></span>
						Layer {layer}
						{#if layer === 1}— Eliminatory{:else if layer === 2}— Mandate Fit{:else}— Quant{/if}
					</h4>
					<table class="criteria-table">
						<thead>
							<tr>
								<th>Criterion</th>
								<th>Expected</th>
								<th>Actual</th>
								<th></th>
							</tr>
						</thead>
						<tbody>
							{#each criteria as c (c.criterion)}
								<tr class:criteria-fail={!c.passed}>
									<td class="criteria-name">{c.criterion}</td>
									<td class="criteria-val">{c.expected}</td>
									<td class="criteria-val">{c.actual}</td>
									<td class="criteria-icon">{c.passed ? "✓" : "✗"}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		{/each}
	{/if}
{/snippet}

<!-- Add to Universe dialog -->
<ConsequenceDialog
	bind:open={addDialogOpen}
	title="Add Manager to Universe"
	impactSummary="This manager will enter the approval pipeline as a pending instrument."
	requireRationale={true}
	rationaleLabel="Justification"
	rationalePlaceholder="Why should this manager enter the universe? (min 10 chars)"
	rationaleMinLength={10}
	confirmLabel="Add to Universe"
	metadata={[
		{ label: "Firm", value: panelFirm },
		{ label: "Asset Class", value: addAssetClass },
		{ label: "Geography", value: addGeography },
	]}
	onConfirm={handleAddToUniverse}
/>

<style>
	/* ── Grid layout ─────────────────────────────────────────────────────── */
	.scr-grid {
		display: grid;
		grid-template-columns: 260px 1fr;
		gap: 0;
		height: calc(100vh - 64px);
		overflow: hidden;
	}

	.scr-actions {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-xs, 6px);
	}

	/* ── Filter panel ────────────────────────────────────────────────────── */
	.scr-filters {
		overflow-y: auto;
		border-right: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-elevated);
		padding: 0;
	}

	.scr-filter-section {
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 14px);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.scr-filter-section--meta {
		border-bottom: none;
	}

	.scr-filter-title {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--netz-text-muted);
		margin-bottom: var(--netz-space-stack-2xs, 6px);
	}

	.scr-field {
		margin-bottom: var(--netz-space-stack-xs, 8px);
	}

	.scr-field-row {
		display: flex;
		gap: var(--netz-space-inline-xs, 6px);
		margin-bottom: var(--netz-space-stack-xs, 8px);
	}

	.scr-label {
		display: block;
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 500;
		color: var(--netz-text-muted);
		margin-bottom: 2px;
	}

	.scr-input,
	.scr-select {
		width: 100%;
		height: var(--netz-space-control-height-sm, 30px);
		padding: 0 var(--netz-space-inline-xs, 8px);
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 6px);
		background: var(--netz-surface);
		color: var(--netz-text-primary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-sans);
		transition: border-color 120ms ease;
	}

	.scr-input--half { width: 50%; }

	.scr-input:focus,
	.scr-select:focus {
		outline: none;
		border-color: var(--netz-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--netz-brand-secondary) 20%, transparent);
	}

	.scr-input::placeholder { color: var(--netz-text-muted); }

	.scr-checkbox {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-xs, 6px);
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-secondary);
		cursor: pointer;
		margin-bottom: var(--netz-space-stack-2xs, 4px);
	}

	.scr-filter-btns {
		display: flex;
		gap: var(--netz-space-inline-xs, 6px);
		margin-top: var(--netz-space-stack-xs, 8px);
	}

	.scr-clear-btn {
		width: 100%;
		padding: var(--netz-space-stack-2xs, 6px);
		border: none;
		border-radius: var(--netz-radius-sm, 6px);
		background: transparent;
		color: var(--netz-brand-secondary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-sans);
		cursor: pointer;
		transition: background-color 120ms ease;
	}

	.scr-clear-btn:hover { background: var(--netz-surface-alt); }

	/* Funnel */
	.funnel {
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-2xs, 4px);
	}

	.funnel-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-secondary);
	}

	.funnel-value {
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--netz-text-primary);
	}

	.funnel-bar {
		height: 4px;
		border-radius: 2px;
		background: var(--netz-border-subtle);
		margin-bottom: var(--netz-space-stack-2xs, 4px);
		position: relative;
		overflow: hidden;
	}

	.funnel-bar::after {
		content: "";
		position: absolute;
		left: 0; top: 0; bottom: 0;
		width: var(--fill, 100%);
		background: var(--netz-brand-primary);
		border-radius: 2px;
		transition: width 300ms ease;
	}

	.funnel-row--outcomes {
		display: flex;
		gap: var(--netz-space-inline-xs, 8px);
		margin-top: var(--netz-space-stack-xs, 8px);
	}

	.funnel-outcome {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
		padding: var(--netz-space-stack-2xs, 4px);
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-sm, 8px);
		background: transparent;
		color: var(--netz-text-secondary);
		font-size: var(--netz-text-label, 0.75rem);
		cursor: pointer;
		transition: border-color 120ms ease, background-color 120ms ease;
	}

	.funnel-outcome:hover {
		border-color: var(--netz-border);
		background: var(--netz-surface-alt);
	}

	.funnel-outcome--active {
		border-color: var(--netz-brand-primary);
		background: color-mix(in srgb, var(--netz-brand-primary) 8%, transparent);
	}

	.funnel-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
	}

	.funnel-dot--pass { background: var(--netz-success); }
	.funnel-dot--watchlist { background: var(--netz-warning); }
	.funnel-dot--fail { background: var(--netz-danger); }

	.funnel-count {
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--netz-text-primary);
	}

	/* Meta */
	.scr-meta-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: var(--netz-text-small, 0.8125rem);
		padding: 2px 0;
	}

	.scr-meta-k { color: var(--netz-text-muted); }
	.scr-meta-v { color: var(--netz-text-primary); font-variant-numeric: tabular-nums; }

	.scr-filter-error {
		color: var(--netz-danger);
		font-size: var(--netz-text-small, 0.8125rem);
		background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
		border-radius: var(--netz-radius-sm, 8px);
		padding: var(--netz-space-inline-sm, 10px);
		margin: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 14px);
	}

	/* ── Main area ───────────────────────────────────────────────────────── */
	.scr-main {
		display: flex;
		flex-direction: column;
		overflow: hidden;
		background: var(--netz-surface);
	}

	.scr-data-header {
		display: flex;
		align-items: center;
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
		flex-shrink: 0;
	}

	.scr-data-count {
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--netz-text-secondary);
		font-variant-numeric: tabular-nums;
	}

	.scr-data-count-muted { color: var(--netz-text-muted); }

	.scr-empty {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--netz-text-muted);
		font-size: var(--netz-text-body, 0.9375rem);
	}

	.scr-error {
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
		color: var(--netz-danger);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	/* ── Hierarchical table ──────────────────────────────────────────────── */
	.scr-table-wrap {
		flex: 1;
		overflow: auto;
	}

	.scr-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.scr-table thead {
		position: sticky;
		top: 0;
		z-index: 1;
	}

	.scr-table th {
		padding: var(--netz-space-stack-2xs, 5px) var(--netz-space-inline-sm, 10px);
		text-align: left;
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.02em;
		color: var(--netz-text-muted);
		background: var(--netz-surface-alt);
		border-bottom: 1px solid var(--netz-border-subtle);
		white-space: nowrap;
	}

	.scr-table td {
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-sm, 10px);
		border-bottom: 1px solid var(--netz-border-subtle);
		vertical-align: middle;
	}

	.sth-check { width: 32px; }
	.sth-expand { width: 28px; }
	.sth-name { min-width: 200px; }
	.sth-aum { width: 90px; text-align: right; }
	.sth-loc { width: 90px; }
	.sth-layers { width: 32px; text-align: center; }
	.sth-score { width: 65px; text-align: right; }
	.sth-status { width: 80px; }
	.sth-univ { width: 80px; }

	/* ── Manager rows (L1) ───────────────────────────────────────────────── */
	.scr-mgr-row {
		cursor: pointer;
		transition: background-color 80ms ease;
	}

	.scr-mgr-row:hover {
		background: var(--netz-surface-highlight, color-mix(in srgb, var(--netz-brand-primary) 4%, transparent));
	}

	.scr-mgr-row--selected {
		background: color-mix(in srgb, var(--netz-brand-primary) 8%, transparent);
	}

	.scr-mgr-row--expanded {
		border-left: 2px solid var(--netz-brand-primary);
	}

	.std-name {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.mgr-name {
		font-weight: 500;
		color: var(--netz-text-primary);
	}

	.mgr-crd {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.std-aum {
		text-align: right;
		font-variant-numeric: tabular-nums;
		color: var(--netz-text-primary);
	}

	.std-loc { color: var(--netz-text-secondary); }

	.std-layer { text-align: center; }

	.std-score {
		text-align: right;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.mgr-disclosures {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.mgr-not-added { color: var(--netz-text-muted); }

	/* Expand chevron */
	.std-expand {
		text-align: center;
		cursor: pointer;
	}

	.expand-chevron {
		display: inline-block;
		font-size: 10px;
		color: var(--netz-text-muted);
		transition: transform 150ms ease;
	}

	.expand-chevron--open {
		transform: rotate(90deg);
	}

	/* ── Fund rows (L2) ──────────────────────────────────────────────────── */
	.scr-fund-row {
		background: var(--netz-surface-alt);
		cursor: pointer;
		transition: background-color 80ms ease;
	}

	.scr-fund-row:hover {
		background: var(--netz-surface-highlight, color-mix(in srgb, var(--netz-brand-primary) 4%, transparent));
	}

	.scr-fund-row--empty {
		cursor: default;
	}

	.scr-fund-row--empty:hover {
		background: var(--netz-surface-alt);
	}

	.std-name--nested {
		flex-direction: row;
		align-items: center;
		gap: var(--netz-space-inline-xs, 6px);
		padding-left: var(--netz-space-inline-md, 16px);
	}

	.nest-char {
		font-family: var(--netz-font-mono);
		color: var(--netz-text-muted);
		font-size: var(--netz-text-label, 0.75rem);
		flex-shrink: 0;
	}

	.fund-name {
		font-weight: 500;
		color: var(--netz-text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.fund-empty-text {
		color: var(--netz-text-muted);
		font-style: italic;
		font-size: var(--netz-text-label, 0.75rem);
	}

	.fund-type-badge {
		display: inline-block;
		padding: 1px 6px;
		border-radius: var(--netz-radius-pill, 999px);
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 500;
		white-space: nowrap;
	}

	.fund-type-badge--fund {
		background: color-mix(in srgb, var(--netz-brand-primary) 12%, transparent);
		color: var(--netz-brand-primary);
	}
	.fund-type-badge--bond {
		background: color-mix(in srgb, var(--netz-brand-highlight) 12%, transparent);
		color: var(--netz-brand-highlight);
	}
	.fund-type-badge--equity {
		background: color-mix(in srgb, var(--netz-success) 12%, transparent);
		color: var(--netz-success);
	}
	.fund-type-badge--other {
		background: var(--netz-surface-alt);
		color: var(--netz-text-muted);
	}

	/* Layer dots */
	.layer-dot {
		display: inline-block;
		width: 10px;
		height: 10px;
		border-radius: 50%;
	}

	.layer-dot--pass { background: var(--netz-success); }
	.layer-dot--fail { background: var(--netz-danger); }
	.layer-dot--none { background: var(--netz-border-subtle); }

	.score-na { color: var(--netz-text-muted); }

	/* ── Pagination ──────────────────────────────────────────────────────── */
	.scr-pagination {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--netz-space-inline-md, 16px);
		padding: var(--netz-space-stack-xs, 10px);
		border-top: 1px solid var(--netz-border-subtle);
		flex-shrink: 0;
	}

	.scr-page-btn {
		padding: 4px 12px;
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 6px);
		background: transparent;
		color: var(--netz-text-secondary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-sans);
		cursor: pointer;
	}

	.scr-page-btn:disabled { opacity: 0.4; cursor: default; }
	.scr-page-btn:not(:disabled):hover { background: var(--netz-surface-alt); }

	.scr-page-info {
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-muted);
		font-variant-numeric: tabular-nums;
	}

	/* ── Compare view ────────────────────────────────────────────────────── */
	.cmp-view {
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
		overflow-y: auto;
		flex: 1;
	}

	.cmp-header {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-md, 16px);
		margin-bottom: var(--netz-space-stack-md, 16px);
	}

	.cmp-title {
		font-size: var(--netz-text-h4, 1.125rem);
		font-weight: 700;
		color: var(--netz-text-primary);
	}

	.cmp-overlap {
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-secondary);
		margin-left: auto;
	}

	.cmp-cards {
		display: flex;
		gap: var(--netz-space-inline-sm, 10px);
		margin-bottom: var(--netz-space-stack-md, 16px);
		overflow-x: auto;
	}

	.cmp-card {
		flex: 1;
		min-width: 140px;
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-sm, 12px);
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-sm, 8px);
		background: var(--netz-surface-elevated);
	}

	.cmp-card-name { font-weight: 600; font-size: var(--netz-text-small, 0.8125rem); color: var(--netz-text-primary); }
	.cmp-card-aum { font-size: var(--netz-text-label, 0.75rem); color: var(--netz-text-secondary); font-variant-numeric: tabular-nums; }
	.cmp-card-crd { font-size: 10px; color: var(--netz-text-muted); }

	.cmp-subtitle {
		font-size: var(--netz-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--netz-text-primary);
		margin-bottom: var(--netz-space-stack-xs, 8px);
	}

	.cmp-sg {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.cmp-sg-header, .cmp-sg-row {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-xs, 6px);
	}

	.cmp-sg-header {
		padding-bottom: var(--netz-space-stack-2xs, 4px);
		border-bottom: 1px solid var(--netz-border-subtle);
		margin-bottom: var(--netz-space-stack-2xs, 4px);
	}

	.cmp-sg-label {
		width: 100px;
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
		flex-shrink: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.cmp-sg-row .cmp-sg-label {
		color: var(--netz-text-secondary);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.cmp-sg-mgr {
		flex: 1;
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		color: var(--netz-text-muted);
		text-align: center;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.cmp-sg-cell {
		flex: 1;
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.cmp-sg-bar-track {
		flex: 1;
		height: 8px;
		background: var(--netz-surface-alt);
		border-radius: 4px;
		overflow: hidden;
	}

	.cmp-sg-bar-fill {
		height: 100%;
		background: var(--netz-brand-primary);
		border-radius: 4px;
		transition: width 300ms ease;
	}

	.cmp-sg-pct {
		font-size: 10px;
		color: var(--netz-text-muted);
		font-variant-numeric: tabular-nums;
		width: 36px;
		text-align: right;
	}

	/* ── Detail panel ────────────────────────────────────────────────────── */
	.dt-tabs {
		display: flex;
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.dt-tab {
		flex: 1;
		padding: var(--netz-space-stack-xs, 8px);
		border: none;
		border-bottom: 2px solid transparent;
		background: transparent;
		color: var(--netz-text-secondary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 500;
		font-family: var(--netz-font-sans);
		cursor: pointer;
		transition: color 120ms ease, border-color 120ms ease;
	}

	.dt-tab:hover { color: var(--netz-text-primary); }

	.dt-tab--active {
		color: var(--netz-brand-primary);
		border-bottom-color: var(--netz-brand-primary);
		font-weight: 600;
	}

	.dt-content {
		overflow-y: auto;
		flex: 1;
	}

	.dt-loading, .dt-empty {
		padding: var(--netz-space-stack-lg, 32px);
		text-align: center;
		color: var(--netz-text-muted);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.dt-section {
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.dt-section-title {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--netz-text-muted);
		margin-bottom: var(--netz-space-stack-xs, 8px);
	}

	.dt-kv {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 3px 0;
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.dt-k { color: var(--netz-text-muted); }
	.dt-v { color: var(--netz-text-primary); font-weight: 500; font-variant-numeric: tabular-nums; }

	.dt-list-row {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: 4px 0;
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.dt-list-name {
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--netz-text-primary);
	}

	.dt-list-meta {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	/* Sector allocation bars */
	.dt-alloc-row {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-xs, 6px);
		padding: 3px 0;
	}

	.dt-alloc-name {
		width: 90px;
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-secondary);
		flex-shrink: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.dt-alloc-bar-track {
		flex: 1;
		height: 6px;
		background: var(--netz-surface-alt);
		border-radius: 3px;
		overflow: hidden;
	}

	.dt-alloc-bar-fill {
		height: 100%;
		background: var(--netz-brand-primary);
		border-radius: 3px;
	}

	.dt-alloc-pct {
		width: 40px;
		text-align: right;
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-primary);
		font-variant-numeric: tabular-nums;
	}

	/* Add to Universe form */
	.dt-empty-text {
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-muted);
		margin-bottom: var(--netz-space-stack-sm, 12px);
	}

	.dt-add-form {
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-xs, 8px);
	}

	.dt-add-field {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.dt-add-label {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.dt-add-select {
		height: var(--netz-space-control-height-sm, 30px);
		padding: 0 var(--netz-space-inline-xs, 8px);
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 6px);
		background: var(--netz-surface);
		color: var(--netz-text-primary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-sans);
	}

	.dt-add-error {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-danger);
	}

	/* Fund detail panel */
	.dt-header-row {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-sm, 10px);
	}

	.dt-score {
		font-weight: 700;
		font-size: var(--netz-text-body-lg, 1rem);
		font-variant-numeric: tabular-nums;
	}

	.dt-fund-meta {
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-secondary);
		margin-top: var(--netz-space-stack-xs, 8px);
	}

	/* Layer breakdown */
	.dt-layer {
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-sm, 8px);
		overflow: hidden;
		margin: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
	}

	.dt-layer-title {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-xs, 6px);
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-sm, 10px);
		background: var(--netz-surface-alt);
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--netz-text-primary);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.criteria-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--netz-text-label, 0.75rem);
	}

	.criteria-table th {
		padding: 4px 8px;
		text-align: left;
		font-weight: 600;
		color: var(--netz-text-muted);
		background: var(--netz-surface);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.criteria-table td {
		padding: 4px 8px;
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.criteria-name {
		color: var(--netz-text-primary);
		font-weight: 500;
	}

	.criteria-val {
		font-variant-numeric: tabular-nums;
		color: var(--netz-text-secondary);
	}

	.criteria-icon {
		text-align: center;
		width: 24px;
	}

	.criteria-fail .criteria-name { color: var(--netz-danger); }
	.criteria-fail .criteria-icon { color: var(--netz-danger); }

	/* ── Responsive ──────────────────────────────────────────────────────── */
	@media (max-width: 768px) {
		.scr-grid {
			grid-template-columns: 1fr;
			grid-template-rows: auto 1fr;
			height: auto;
		}

		.scr-filters {
			border-right: none;
			border-bottom: 1px solid var(--netz-border-subtle);
			max-height: 300px;
		}

		.scr-main {
			min-height: 400px;
		}
	}
</style>
