<!--
  US Fund Analysis — SEC-powered analysis of investment managers,
  holdings, style drift, reverse CUSIP lookup, and peer comparison.
  5 tabs: Overview | Holdings | Style Drift | Reverse Lookup | Peer Compare
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { goto } from "$app/navigation";
	import { ContextPanel, formatAUM } from "@netz/ui";
	import { ChartContainer } from "@netz/ui/charts";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type {
		SecManagerSearchPage,
		SecManagerDetail,
		SecManagerFundBreakdown,
		SecSicCodeItem,
	} from "$lib/types/sec-analysis";
	import { EMPTY_SEARCH_PAGE } from "$lib/types/sec-analysis";
	import ManagerTable from "./components/ManagerTable.svelte";
	import HoldingsTable from "./components/HoldingsTable.svelte";
	import StyleDriftChart from "./components/StyleDriftChart.svelte";
	import ReverseLookup from "./components/ReverseLookup.svelte";
	import PeerCompare from "./components/PeerCompare.svelte";
	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);
	let { data }: { data: PageData } = $props();

	let activeTab = $state("overview");

	// ── SSR data ──
	let searchResults = $derived(
		(data.searchResults ?? EMPTY_SEARCH_PAGE) as SecManagerSearchPage,
	);
	let sicCodes = $derived((data.sicCodes ?? []) as SecSicCodeItem[]);

	// ── Filter state ──
	let initParams = $derived((data.currentParams ?? {}) as Record<string, string>);
	let filters = $state({ q: "", entity_type: "", state: "", has_13f: "", aum_min: "", fund_type: "" });

	$effect(() => {
		filters.q = initParams.q ?? "";
		filters.entity_type = initParams.entity_type ?? "";
		filters.state = initParams.state ?? "";
		filters.has_13f = initParams.has_13f ?? "";
		filters.aum_min = initParams.aum_min ?? "";
		filters.fund_type = initParams.fund_type ?? "";
	});

	function applyFilters() {
		const params = new URLSearchParams();
		if (filters.q) params.set("q", filters.q);
		if (filters.entity_type) params.set("entity_type", filters.entity_type);
		if (filters.state) params.set("state", filters.state);
		if (filters.has_13f) params.set("has_13f", filters.has_13f);
		if (filters.aum_min) params.set("aum_min", filters.aum_min);
		if (filters.fund_type) params.set("fund_type", filters.fund_type);
		goto(`/us-fund-analysis?${params.toString()}`, { invalidateAll: true });
	}

	function clearFilters() {
		filters = { q: "", entity_type: "", state: "", has_13f: "", aum_min: "", fund_type: "" };
		goto("/us-fund-analysis", { invalidateAll: true });
	}

	// ── Selected manager for Holdings / Style Drift tabs ──
	let selectedCik = $state<string | null>(null);
	let selectedName = $state<string>("");

	function selectManager(cik: string, name: string) {
		selectedCik = cik;
		selectedName = name;
	}

	// ── Detail panel ──
	let detailManager = $state<SecManagerDetail | null>(null);
	let detailOpen = $state(false);
	let detailLoading = $state(false);

	async function openDetail(cik: string) {
		detailOpen = true;
		detailLoading = true;
		fundBreakdown = null;
		try {
			detailManager = await api.get<SecManagerDetail>(`/sec/managers/${cik}`);
			if (detailManager?.crd_number) {
				loadFundBreakdown(detailManager.crd_number);
			}
		} catch {
			detailManager = null;
		} finally {
			detailLoading = false;
		}
	}

	// ── Peer compare state ──
	let compareCiks = $state<Set<string>>(new Set());

	function toggleCompare(cik: string) {
		const next = new Set(compareCiks);
		if (next.has(cik)) next.delete(cik);
		else if (next.size < 5) next.add(cik);
		compareCiks = next;
	}

	// ── Tab definitions (after compareCiks for derived count) ──
	let tabs = $derived([
		{ value: "overview", label: "Overview" },
		{ value: "holdings", label: "Holdings" },
		{ value: "style-drift", label: "Style Drift" },
		{ value: "reverse", label: "Reverse Lookup" },
		{ value: "compare", label: `Peer Compare${compareCiks.size > 0 ? ` (${compareCiks.size})` : ""}` },
	]);

	// ── Page navigation ──
	function goToPage(p: number) {
		const params = new URLSearchParams();
		if (filters.q) params.set("q", filters.q);
		if (filters.entity_type) params.set("entity_type", filters.entity_type);
		if (filters.state) params.set("state", filters.state);
		if (filters.has_13f) params.set("has_13f", filters.has_13f);
		if (filters.aum_min) params.set("aum_min", filters.aum_min);
		if (filters.fund_type) params.set("fund_type", filters.fund_type);
		params.set("page", String(p));
		goto(`/us-fund-analysis?${params.toString()}`, { invalidateAll: true });
	}

	// ── Fund structure for detail panel (A-06) ──
	let fundBreakdown = $state<SecManagerFundBreakdown | null>(null);
	let fundLoading = $state(false);

	async function loadFundBreakdown(crd: string) {
		fundLoading = true;
		try {
			fundBreakdown = await api.get<SecManagerFundBreakdown>(`/sec/managers/${crd}/funds`);
		} catch {
			fundBreakdown = null;
		} finally {
			fundLoading = false;
		}
	}
</script>

<div class="ufa-header">
	<div class="ufa-header-text">
		<h1 class="ufa-title">US Fund Analysis</h1>
		<p class="ufa-subtitle">Screen and analyze US-based fund managers, their holdings, and historical drift.</p>
	</div>
	<button class="ufa-export-btn" type="button">
		<svg width="16" height="16" viewBox="0 0 16 16" fill="none">
			<path d="M8 2v8m0 0l-3-3m3 3l3-3M3 12h10" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
		</svg>
		Export Data
	</button>
</div>

<div class="ufa-page">
	<div class="ufa-card">
		<!-- Lifted tab header -->
		<div class="ufa-tab-header">
			{#each tabs as tab (tab.value)}
				<button
					class="ufa-tab"
					class:ufa-tab--active={activeTab === tab.value}
					onclick={() => (activeTab = tab.value)}
					role="tab"
					aria-selected={activeTab === tab.value}
				>
					{tab.label}
					{#if activeTab === tab.value}
						<span class="ufa-tab-accent"></span>
					{/if}
				</button>
			{/each}
		</div>

		<!-- Tab content -->
		{#if activeTab === "overview"}
			<div class="ufa-filters-section">
				<div class="ufa-filters-header">
					<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 3h12l-4.5 5.3V13l-3-1.5V8.3L2 3z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>
					<span class="ufa-filters-label">Filter Parameters</span>
				</div>
				<form class="ufa-filters-row" onsubmit={(e) => { e.preventDefault(); applyFilters(); }}>
					<div class="ufa-filter-field ufa-filter-field--search">
						<label class="ufa-field-label" for="ufa-q">Search</label>
						<div class="ufa-search-wrap">
							<svg class="ufa-search-icon" width="16" height="16" viewBox="0 0 16 16" fill="none">
								<circle cx="7" cy="7" r="4.5" stroke="#90a1b9" stroke-width="1.3"/>
								<path d="M10.5 10.5L13.5 13.5" stroke="#90a1b9" stroke-width="1.3" stroke-linecap="round"/>
							</svg>
							<input
								id="ufa-q"
								class="ufa-input ufa-input--search"
								type="text"
								placeholder="Name, CIK, or CRD..."
								bind:value={filters.q}
							/>
						</div>
					</div>
					<div class="ufa-filter-field">
						<label class="ufa-field-label" for="ufa-entity">Manager Type</label>
						<select id="ufa-entity" class="ufa-select" bind:value={filters.entity_type}>
							<option value="">Investment Advisers</option>
							<option value="all">All SEC Entities</option>
						</select>
					</div>
					<div class="ufa-filter-field">
						<label class="ufa-field-label" for="ufa-fund-type">Fund Type</label>
						<select id="ufa-fund-type" class="ufa-select" bind:value={filters.fund_type}>
							<option value="">All Types</option>
							<option value="hedge">Hedge Funds</option>
							<option value="pe">Private Equity</option>
							<option value="vc">Venture Capital</option>
							<option value="real_estate">Real Estate</option>
						</select>
					</div>
					<div class="ufa-filter-field">
						<label class="ufa-field-label" for="ufa-state">State</label>
						<input
							id="ufa-state"
							class="ufa-input"
							type="text"
							placeholder="e.g. NY, CA..."
							bind:value={filters.state}
						/>
					</div>
					<div class="ufa-filter-field">
						<label class="ufa-field-label" for="ufa-13f">Has 13F Filings</label>
						<select id="ufa-13f" class="ufa-select" bind:value={filters.has_13f}>
							<option value="">All</option>
							<option value="true">Yes</option>
							<option value="false">No</option>
						</select>
					</div>
					<div class="ufa-filter-field">
						<label class="ufa-field-label" for="ufa-aum">Min AUM ($)</label>
						<input
							id="ufa-aum"
							class="ufa-input"
							type="number"
							placeholder="e.g. 1000000000"
							bind:value={filters.aum_min}
						/>
					</div>
				</form>
				<div class="ufa-filters-actions">
					<button class="ufa-btn-clear" type="button" onclick={clearFilters}>Clear</button>
					<button class="ufa-btn-apply" type="button" onclick={applyFilters}>Apply Filters</button>
				</div>
			</div>

			<ManagerTable
				data={searchResults}
				onSelect={(cik, name) => {
					selectManager(cik, name);
					activeTab = "holdings";
				}}
				onDetail={openDetail}
				onPageChange={goToPage}
				{compareCiks}
				onToggleCompare={toggleCompare}
			/>
		{:else if activeTab === "holdings"}
			<div class="ufa-tab-content">
				<HoldingsTable {api} cik={selectedCik} managerName={selectedName} />
			</div>
		{:else if activeTab === "style-drift"}
			<div class="ufa-tab-content">
				<StyleDriftChart {api} cik={selectedCik} managerName={selectedName} />
			</div>
		{:else if activeTab === "reverse"}
			<div class="ufa-tab-content">
				<ReverseLookup {api} />
			</div>
		{:else if activeTab === "compare"}
			<div class="ufa-tab-content">
				<PeerCompare {api} ciks={[...compareCiks]} />
			</div>
		{/if}
	</div>
</div>

<ContextPanel
	open={detailOpen}
	title={detailManager?.firm_name ?? "Manager Detail"}
	onClose={() => (detailOpen = false)}
	width="480px"
>
	{#if detailLoading}
		<p class="ufa-loading">Loading...</p>
	{:else if detailManager}
		<div class="ufa-detail">
			<div class="ufa-detail__row">
				<span class="ufa-detail__label">CIK</span>
				<span>{detailManager.cik ?? "\u2014"}</span>
			</div>
			<div class="ufa-detail__row">
				<span class="ufa-detail__label">CRD</span>
				<span>{detailManager.crd_number}</span>
			</div>
			<div class="ufa-detail__row">
				<span class="ufa-detail__label">Status</span>
				<span>{detailManager.registration_status ?? "\u2014"}</span>
			</div>
			<div class="ufa-detail__row">
				<span class="ufa-detail__label">State</span>
				<span>{detailManager.state ?? "\u2014"}</span>
			</div>
			<div class="ufa-detail__row">
				<span class="ufa-detail__label">AUM</span>
				<span>{detailManager.aum_total != null ? formatAUM(detailManager.aum_total) : "\u2014"}</span>
			</div>
			<div class="ufa-detail__row">
				<span class="ufa-detail__label">Latest Quarter</span>
				<span>{detailManager.latest_quarter ?? "\u2014"}</span>
			</div>
			<div class="ufa-detail__row">
				<span class="ufa-detail__label">Holdings</span>
				<span>{detailManager.holdings_count}</span>
			</div>
			{#if detailManager.website}
				<div class="ufa-detail__row">
					<span class="ufa-detail__label">Website</span>
					<span>{detailManager.website}</span>
				</div>
			{/if}
		</div>

		<!-- Private Fund Breakdown -->
		{#if detailManager.private_fund_count && detailManager.private_fund_count > 0}
			<div class="ufa-fund-section">
				<span class="ufa-fund-title">Private Fund Breakdown</span>
				<div class="ufa-fund-grid">
					{#if detailManager.hedge_fund_count}
						<div class="ufa-fund-stat">
							<span class="ufa-fund-stat__value">{detailManager.hedge_fund_count}</span>
							<span class="ufa-fund-stat__label">Hedge Funds</span>
						</div>
					{/if}
					{#if detailManager.pe_fund_count}
						<div class="ufa-fund-stat">
							<span class="ufa-fund-stat__value">{detailManager.pe_fund_count}</span>
							<span class="ufa-fund-stat__label">PE Funds</span>
						</div>
					{/if}
					{#if detailManager.vc_fund_count}
						<div class="ufa-fund-stat">
							<span class="ufa-fund-stat__value">{detailManager.vc_fund_count}</span>
							<span class="ufa-fund-stat__label">VC Funds</span>
						</div>
					{/if}
					{#if detailManager.total_private_fund_assets}
						<div class="ufa-fund-stat">
							<span class="ufa-fund-stat__value">{formatAUM(detailManager.total_private_fund_assets)}</span>
							<span class="ufa-fund-stat__label">Total GAV</span>
						</div>
					{/if}
				</div>
			</div>
		{/if}

		<!-- ADV Brochure Highlights -->
		{#if detailManager.brochure_sections && detailManager.brochure_sections.length > 0}
			<div class="ufa-brochure-section">
				<span class="ufa-fund-title">ADV Brochure Highlights</span>
				{#each detailManager.brochure_sections as section}
					<details class="ufa-brochure-item">
						<summary class="ufa-brochure-summary">
							{section.section.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase())}
						</summary>
						<p class="ufa-brochure-content">{section.content}</p>
					</details>
				{/each}
			</div>
		{/if}

		<!-- Fund Structure Donut (A-06) -->
		{#if fundLoading}
			<div class="ufa-fund-section">
				<span class="ufa-fund-title">Fund Structure</span>
				<p class="ufa-loading">Loading...</p>
			</div>
		{:else if fundBreakdown && fundBreakdown.total_funds > 0}
			<div class="ufa-fund-section">
				<span class="ufa-fund-title">Fund Structure ({fundBreakdown.total_funds} funds)</span>
				<ChartContainer
					height={220}
					option={{
						tooltip: {
							trigger: "item",
							formatter: "{b}: {c} ({d}%)",
						},
						series: [
							{
								type: "pie",
								radius: ["40%", "70%"],
								avoidLabelOverlap: true,
								itemStyle: { borderRadius: 6, borderColor: "#1a1a2e", borderWidth: 2 },
								label: { show: true, fontSize: 11 },
								data: fundBreakdown.breakdown.map((b) => ({
									name: b.fund_type,
									value: b.fund_count,
								})),
							},
						],
					}}
				/>
			</div>
		{:else if fundBreakdown && fundBreakdown.total_funds === 0}
			<div class="ufa-fund-section">
				<span class="ufa-fund-title">Fund Structure</span>
				<p class="ufa-fund-empty">No fund data available</p>
			</div>
		{/if}
	{:else}
		<p class="ufa-loading">Manager not found.</p>
	{/if}
</ContextPanel>

<style>
	/* ── Header ── */
	.ufa-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 40px var(--netz-space-inline-lg, 24px) 24px;
	}

	.ufa-title {
		font-size: 28px;
		font-weight: 800;
		color: #1d293d;
		letter-spacing: -0.7px;
		line-height: 42px;
		margin: 0;
	}

	.ufa-subtitle {
		font-size: 14px;
		font-weight: 500;
		color: #62748e;
		margin: 4px 0 0;
		line-height: 20px;
	}

	.ufa-export-btn {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 20px;
		background: white;
		border: 1px solid #e2e8f0;
		border-radius: 10px;
		box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1), 0 1px 2px rgba(0, 0, 0, 0.1);
		font-size: 14px;
		font-weight: 700;
		color: #45556c;
		cursor: pointer;
		font-family: var(--netz-font-sans);
		white-space: nowrap;
	}

	.ufa-export-btn:hover {
		background: #f8fafc;
	}

	/* ── Page ── */
	.ufa-page {
		padding: 0 var(--netz-space-inline-lg, 24px) var(--netz-space-stack-xl, 48px);
	}

	.ufa-card {
		background: #ffffff;
		border: 1px solid #e2e8f0;
		border-radius: 16px;
		overflow: hidden;
		box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
	}

	/* ── Lifted tab header ── */
	.ufa-tab-header {
		display: flex;
		align-items: flex-end;
		gap: 0;
		padding: 16px 16px 0;
		background: rgba(248, 250, 252, 0.8);
		border-bottom: 1px solid #e2e8f0;
		height: 61px;
	}

	.ufa-tab {
		position: relative;
		padding: 12px 24px;
		border: 1px solid transparent;
		border-bottom: none;
		border-radius: 14px 14px 0 0;
		background: none;
		font-size: 14px;
		font-weight: 700;
		color: #62748e;
		cursor: pointer;
		font-family: var(--netz-font-sans);
		transition: color 120ms, background 120ms;
		margin-bottom: -1px;
		white-space: nowrap;
	}

	.ufa-tab:hover {
		color: #1d293d;
	}

	.ufa-tab--active {
		background: #ffffff;
		border-color: #e2e8f0;
		color: #1447e6;
		box-shadow: 0 -4px 10px rgba(0, 0, 0, 0.02);
	}

	.ufa-tab-accent {
		position: absolute;
		bottom: 0;
		left: 0;
		right: 0;
		height: 2px;
		background: #155dfc;
	}

	/* ── Tab content padding for non-overview tabs ── */
	.ufa-tab-content {
		padding: 24px;
	}

	/* ── Filters ── */
	.ufa-filters-section {
		padding: 24px;
		border-bottom: 1px solid #f1f5f9;
		background: #ffffff;
	}

	.ufa-filters-header {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 16px;
		color: #62748e;
	}

	.ufa-filters-label {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 1.1px;
		color: #62748e;
	}

	.ufa-filters-row {
		display: grid;
		grid-template-columns: repeat(6, 1fr);
		gap: 16px;
	}

	.ufa-filter-field {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.ufa-field-label {
		font-size: 12px;
		font-weight: 700;
		color: #45556c;
	}

	.ufa-input,
	.ufa-select {
		padding: 8px 12px;
		font-size: 14px;
		height: 37px;
		border: 1px solid #e2e8f0;
		border-radius: 10px;
		background: #f8fafc;
		color: #1d293d;
		font-family: var(--netz-font-sans);
	}

	.ufa-input::placeholder {
		color: #90a1b9;
		font-weight: 500;
	}

	.ufa-input:focus,
	.ufa-select:focus {
		outline: none;
		border-color: #155dfc;
	}

	.ufa-input--search {
		padding-left: 36px;
	}

	.ufa-search-wrap {
		position: relative;
	}

	.ufa-search-icon {
		position: absolute;
		left: 12px;
		top: 50%;
		transform: translateY(-50%);
		pointer-events: none;
	}

	.ufa-filters-actions {
		display: flex;
		justify-content: flex-end;
		gap: 12px;
		margin-top: 16px;
		padding-top: 16px;
		border-top: 1px solid #f1f5f9;
	}

	.ufa-btn-clear {
		height: 36px;
		padding: 0 16px;
		font-size: 14px;
		font-weight: 700;
		color: #62748e;
		background: none;
		border: none;
		border-radius: 10px;
		cursor: pointer;
	}

	.ufa-btn-clear:hover {
		color: #1d293d;
	}

	.ufa-btn-apply {
		height: 36px;
		padding: 0 20px;
		font-size: 14px;
		font-weight: 700;
		color: white;
		background: #155dfc;
		border: none;
		border-radius: 10px;
		cursor: pointer;
		box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
	}

	.ufa-btn-apply:hover {
		filter: brightness(1.1);
	}

	/* Detail panel */
	.ufa-loading {
		padding: 24px;
		color: var(--netz-text-muted);
		font-size: 13px;
	}

	.ufa-detail {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 16px;
	}

	.ufa-detail__row {
		display: flex;
		justify-content: space-between;
		font-size: 13px;
	}

	.ufa-detail__label {
		color: var(--netz-text-muted);
		font-weight: 500;
	}

	/* Fund Structure section in detail panel */
	.ufa-fund-section {
		padding: 16px;
		border-top: 1px solid var(--netz-border-subtle);
	}

	.ufa-fund-title {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--netz-text-muted);
	}

	.ufa-fund-empty {
		font-size: 13px;
		color: var(--netz-text-muted);
		margin-top: 8px;
	}

	.ufa-fund-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 12px;
		margin-top: 12px;
	}

	.ufa-fund-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.ufa-fund-stat__value {
		font-size: 20px;
		font-weight: 800;
		color: var(--netz-text-primary, #1d293d);
	}

	.ufa-fund-stat__label {
		font-size: 11px;
		font-weight: 600;
		color: var(--netz-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.ufa-brochure-section {
		padding: 16px;
		border-top: 1px solid var(--netz-border-subtle);
	}

	.ufa-brochure-item {
		margin-top: 8px;
		border: 1px solid var(--netz-border-subtle);
		border-radius: 8px;
		overflow: hidden;
	}

	.ufa-brochure-summary {
		padding: 10px 12px;
		font-size: 12px;
		font-weight: 700;
		color: var(--netz-text-secondary);
		cursor: pointer;
		background: rgba(248, 250, 252, 0.5);
	}

	.ufa-brochure-summary:hover {
		background: rgba(248, 250, 252, 0.8);
	}

	.ufa-brochure-content {
		padding: 12px;
		font-size: 13px;
		line-height: 1.6;
		color: var(--netz-text-secondary);
		max-height: 200px;
		overflow-y: auto;
		white-space: pre-wrap;
		margin: 0;
	}

	@media (max-width: 1200px) {
		.ufa-filters-row {
			grid-template-columns: repeat(3, 1fr);
		}
	}

	@media (max-width: 768px) {
		.ufa-filters-row {
			grid-template-columns: repeat(2, 1fr);
		}
	}

	@media (max-width: 480px) {
		.ufa-filters-row {
			grid-template-columns: 1fr;
		}
	}
</style>
