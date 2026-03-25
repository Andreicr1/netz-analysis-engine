<!--
  US Fund Analysis — SEC-powered analysis of investment managers,
  holdings, style drift, reverse CUSIP lookup, and peer comparison.
  5 tabs: Overview | Holdings | Style Drift | Reverse Lookup | Peer Compare
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { goto } from "$app/navigation";
	import { PageHeader, PageTabs, ContextPanel, Button, formatAUM } from "@netz/ui";
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
	import TopAdvisersWidget from "./components/TopAdvisersWidget.svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);
	let { data }: { data: PageData } = $props();

	// ── Tab definitions ──
	const tabs = [
		{ value: "overview", label: "Overview" },
		{ value: "holdings", label: "Holdings" },
		{ value: "style-drift", label: "Style Drift" },
		{ value: "reverse", label: "Reverse Lookup" },
		{ value: "compare", label: "Peer Compare" },
	];
	let activeTab = $state("overview");

	// ── SSR data ──
	let searchResults = $derived(
		(data.searchResults ?? EMPTY_SEARCH_PAGE) as SecManagerSearchPage,
	);
	let sicCodes = $derived((data.sicCodes ?? []) as SecSicCodeItem[]);

	// ── Filter state ──
	let initParams = $derived((data.currentParams ?? {}) as Record<string, string>);
	let filters = $state({ q: "", entity_type: "", aum_min: "" });

	$effect(() => {
		filters.q = initParams.q ?? "";
		filters.entity_type = initParams.entity_type ?? "";
		filters.aum_min = initParams.aum_min ?? "";
	});

	function applyFilters() {
		const params = new URLSearchParams();
		if (filters.q) params.set("q", filters.q);
		if (filters.entity_type) params.set("entity_type", filters.entity_type);
		if (filters.aum_min) params.set("aum_min", filters.aum_min);
		goto(`/us-fund-analysis?${params.toString()}`, { invalidateAll: true });
	}

	function clearFilters() {
		filters = { q: "", entity_type: "", aum_min: "" };
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

	// ── Page navigation ──
	function goToPage(p: number) {
		const params = new URLSearchParams();
		if (filters.q) params.set("q", filters.q);
		if (filters.entity_type) params.set("entity_type", filters.entity_type);
		if (filters.aum_min) params.set("aum_min", filters.aum_min);
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

<PageHeader title="US Fund Analysis" subtitle="Screen and analyze US-based fund managers, their holdings, and historical drift.">
	{#snippet actions()}
		<Button size="sm" variant="outline">Export Data</Button>
	{/snippet}
</PageHeader>

<div class="ufa-page">
	<div class="ufa-card">
		<PageTabs {tabs} active={activeTab} onChange={(t) => (activeTab = t)}>
			{#snippet children(current)}
				{#if current === "overview"}
					<div class="ufa-filters-section">
						<div class="ufa-filters-header">
							<span class="ufa-filters-label">Filter Parameters</span>
						</div>
						<form class="ufa-filters-row" onsubmit={(e) => { e.preventDefault(); applyFilters(); }}>
							<div class="ufa-filter-field ufa-filter-field--search">
								<label class="ufa-field-label" for="ufa-q">Search</label>
								<div class="ufa-search-wrap">
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
								<label class="ufa-field-label" for="ufa-entity">Entity Type</label>
								<select id="ufa-entity" class="ufa-select" bind:value={filters.entity_type}>
									<option value="">All Entities</option>
									<option value="Registered">Registered</option>
									<option value="Exempt Reporting Adviser">Exempt Reporting</option>
									<option value="Not Registered">Not Registered</option>
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

					{#if !filters.q && !filters.entity_type && !filters.aum_min}
						<div class="ufa-widget-section">
							<TopAdvisersWidget
								{api}
								onSelect={(cik, name) => {
									selectManager(cik, name);
									activeTab = "holdings";
								}}
							/>
						</div>
					{/if}

					<ManagerTable
						data={searchResults}
						onSelect={(cik, name) => {
							selectManager(cik, name);
							activeTab = "holdings";
						}}
						onDetail={openDetail}
						onPageChange={goToPage}
					/>
				{:else if current === "holdings"}
					<HoldingsTable {api} cik={selectedCik} managerName={selectedName} />
				{:else if current === "style-drift"}
					<StyleDriftChart {api} cik={selectedCik} managerName={selectedName} />
				{:else if current === "reverse"}
					<ReverseLookup {api} />
				{:else if current === "compare"}
					<PeerCompare {api} ciks={[...compareCiks]} />
				{/if}
			{/snippet}
		</PageTabs>
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
	.ufa-page {
		padding: 0 var(--netz-space-inline-lg, 24px) var(--netz-space-stack-xl, 48px);
	}

	.ufa-card {
		background: var(--netz-surface-elevated);
		border: 1px solid var(--netz-border-subtle);
		border-radius: 16px;
		overflow: hidden;
		box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
	}

	/* Filters */
	.ufa-filters-section {
		padding: 24px;
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-elevated);
	}

	.ufa-filters-header {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 16px;
	}

	.ufa-filters-label {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--netz-text-muted);
	}

	.ufa-filters-row {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
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
		color: var(--netz-text-secondary);
	}

	.ufa-input,
	.ufa-select {
		padding: 8px 12px;
		font-size: 14px;
		border: 1px solid var(--netz-border-subtle);
		border-radius: 10px;
		background: var(--netz-surface-alt);
		color: var(--netz-text-primary);
		font-family: var(--netz-font-sans);
	}

	.ufa-input::placeholder {
		color: var(--netz-text-muted);
	}

	.ufa-input:focus,
	.ufa-select:focus {
		outline: none;
		border-color: var(--netz-brand-primary);
	}

	.ufa-input--search {
		padding-left: 36px;
	}

	.ufa-search-wrap {
		position: relative;
	}

	.ufa-search-wrap::before {
		content: "\2315";
		position: absolute;
		left: 12px;
		top: 50%;
		transform: translateY(-50%);
		font-size: 14px;
		color: var(--netz-text-muted);
		pointer-events: none;
	}

	.ufa-filters-actions {
		display: flex;
		justify-content: flex-end;
		gap: 12px;
		margin-top: 16px;
		padding-top: 16px;
		border-top: 1px solid var(--netz-border-subtle);
	}

	.ufa-btn-clear {
		padding: 8px 16px;
		font-size: 14px;
		font-weight: 700;
		color: var(--netz-text-secondary);
		background: none;
		border: none;
		border-radius: 10px;
		cursor: pointer;
	}

	.ufa-btn-clear:hover {
		color: var(--netz-text-primary);
	}

	.ufa-btn-apply {
		padding: 8px 20px;
		font-size: 14px;
		font-weight: 700;
		color: white;
		background: var(--netz-brand-primary);
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

	.ufa-widget-section {
		padding: 20px 24px;
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	@media (max-width: 1024px) {
		.ufa-filters-row {
			grid-template-columns: repeat(3, 1fr);
		}
	}

	@media (max-width: 600px) {
		.ufa-filters-row {
			grid-template-columns: 1fr;
		}
	}
</style>
