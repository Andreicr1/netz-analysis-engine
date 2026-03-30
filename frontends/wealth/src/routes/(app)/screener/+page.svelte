<!--
  Unified Screener — Fund Catalog with sidebar facets + server-side pagination.
  Manager detail accessible via click on manager name in catalog table.
-->
<script lang="ts">
	import { untrack, getContext } from "svelte";
	import { goto } from "$app/navigation";
	import { PageHeader, ContextPanel, formatAUM } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";

	// Catalog types
	import type { UnifiedFundItem, UnifiedCatalogPage, CatalogFacets, CatalogCategory } from "$lib/types/catalog";
	import { EMPTY_CATALOG_PAGE, EMPTY_FACETS } from "$lib/types/catalog";

	// Manager types
	import type { SecManagerDetail, SecManagerFundBreakdown } from "$lib/types/sec-analysis";

	// Components
	import {
		CatalogFilterSidebar,
		CatalogTable,
		CatalogDetailPanel,
	} from "$lib/components/screener";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	let { data }: { data: PageData } = $props();

	const initParams = (untrack(() => data.currentParams) as Record<string, string>) ?? {};

	// ── Catalog state ──
	let catalog = $derived(((data as any).catalog ?? EMPTY_CATALOG_PAGE) as UnifiedCatalogPage);
	let catalogFacets = $derived(((data as any).catalogFacets ?? EMPTY_FACETS) as CatalogFacets);

	// Catalog filter state (from URL params)
	let selectedCategories = $state<CatalogCategory[]>(
		initParams.category ? (initParams.category.split(",") as CatalogCategory[]) : [],
	);
	let selectedFundTypes = $state<string[]>(initParams.fund_type ? initParams.fund_type.split(",") : []);
	let selectedStrategyLabels = $state<string[]>(initParams.strategy_label ? initParams.strategy_label.split(",") : []);
	let selectedGeographies = $state<string[]>(initParams.investment_geography ? initParams.investment_geography.split(",") : []);
	let selectedDomiciles = $state<string[]>(initParams.domicile ? initParams.domicile.split(",") : []);
	let catalogSearchQ = $state(initParams.q ?? "");
	let catalogAumMin = $state(initParams.aum_min ?? "");
	let catalogMaxER = $state(initParams.max_expense_ratio ?? "");
	let catalogMinReturn1y = $state(initParams.min_return_1y ?? "");
	let catalogMinReturn10y = $state(initParams.min_return_10y ?? "");
	let currentSort = $state(initParams.sort ?? "name_asc");

	function buildCatalogParams(): URLSearchParams {
		const params = new URLSearchParams();
		params.set("tab", "catalog");
		if (catalogSearchQ) params.set("q", catalogSearchQ);
		if (selectedCategories.length) params.set("category", selectedCategories.join(","));
		if (selectedFundTypes.length) params.set("fund_type", selectedFundTypes.join(","));
		if (selectedStrategyLabels.length) params.set("strategy_label", selectedStrategyLabels.join(","));
		if (selectedGeographies.length) params.set("investment_geography", selectedGeographies.join(","));
		for (const d of selectedDomiciles) params.append("domicile", d);
		if (catalogAumMin) params.set("aum_min", catalogAumMin);
		if (catalogMaxER) params.set("max_expense_ratio", catalogMaxER);
		if (catalogMinReturn1y) params.set("min_return_1y", catalogMinReturn1y);
		if (catalogMinReturn10y) params.set("min_return_10y", catalogMinReturn10y);
		if (currentSort && currentSort !== "name_asc") params.set("sort", currentSort);
		return params;
	}

	function applyCatalogFilters() {
		const params = buildCatalogParams();
		params.set("page", "1");
		params.set("page_size", "50");
		goto(`/screener?${params.toString()}`, { invalidateAll: true });
	}

	function catalogPageChange(page: number) {
		const params = buildCatalogParams();
		params.set("page", String(page));
		params.set("page_size", "50");
		goto(`/screener?${params.toString()}`, { invalidateAll: true });
	}

	function handleSortChange(sort: string) {
		currentSort = sort;
		const params = buildCatalogParams();
		params.set("sort", sort);
		params.set("page", "1");
		params.set("page_size", "50");
		goto(`/screener?${params.toString()}`, { invalidateAll: true });
	}

	// ── Catalog detail panel ──
	let panelOpen = $state(false);
	let selectedFund = $state<UnifiedFundItem | null>(null);
	let panelTitle = $derived(selectedFund?.name ?? "");

	function openFundDetail(item: UnifiedFundItem) {
		selectedFund = item;
		panelOpen = true;
	}

	function closePanel() {
		panelOpen = false;
		selectedFund = null;
	}

	// ── Send selected classes to DD Review ──
	const api = createClientApiClient(getToken);

	async function sendClassesToDDReview(items: UnifiedFundItem[]) {
		if (items.length === 0) return;
		if (items.length === 1) {
			const item = items[0]!;
			try {
				let instrumentId = item.instrument_id;
				if (!instrumentId) {
					const identifier = item.isin || item.ticker;
					if (!identifier) return;
					const imported = await api.post<{ instrument_id: string }>(`/screener/import/${identifier}`, {});
					instrumentId = imported.instrument_id;
				}
				if (!instrumentId) return;
				const ddReport = await api.post<{ id: string }>(`/dd-reports/funds/${instrumentId}`, {});
				goto(`/dd-reports/${instrumentId}/${ddReport.id}`);
			} catch {
				// Fail silently — user can retry via detail panel
			}
			return;
		}
		goto("/dd-reports");
	}

	// ── Manager detail panel ──
	let mgrDetailOpen = $state(false);
	let mgrDetail = $state<SecManagerDetail | null>(null);
	let mgrDetailLoading = $state(false);
	let mgrFundBreakdown = $state<SecManagerFundBreakdown | null>(null);

	async function openManagerDetail(managerId: string) {
		mgrDetailOpen = true;
		mgrDetailLoading = true;
		mgrFundBreakdown = null;
		try {
			mgrDetail = await api.get<SecManagerDetail>(`/sec/managers/${managerId}`);
			if (mgrDetail?.crd_number) {
				api.get<SecManagerFundBreakdown>(`/sec/managers/${mgrDetail.crd_number}/funds`)
					.then((bd) => (mgrFundBreakdown = bd))
					.catch(() => (mgrFundBreakdown = null));
			}
		} catch {
			mgrDetail = null;
		} finally {
			mgrDetailLoading = false;
		}
	}

	// ── CSV Export ──
	function exportCSV() {
		const items = catalog.items;
		if (items.length === 0) return;
		const headers = ["Manager", "Name", "Type", "Strategy", "AUM", "Currency"];
		const lines = [
			headers.join(","),
			...items.map(r => [
				`"${r.manager_name ?? ""}"`,
				`"${r.name}"`,
				r.fund_type,
				`"${r.strategy_label ?? ""}"`,
				r.aum ?? "",
				r.currency ?? "",
			].join(","))
		];
		const blob = new Blob([lines.join("\n")], { type: "text/csv" });
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = `screener-catalog-${new Date().toISOString().slice(0,10)}.csv`;
		a.click();
		URL.revokeObjectURL(url);
	}
</script>

<PageHeader title="Screener">
	{#snippet actions()}
		<div class="scr-actions">
			<button class="scr-btn scr-btn--outline" onclick={exportCSV}>
				<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
				Export
			</button>
		</div>
	{/snippet}
</PageHeader>

<!-- ════════════════ CATALOG ════════════════ -->
<div class="scr-master-detail">
	<CatalogFilterSidebar
		facets={catalogFacets}
		bind:selectedCategories
		bind:selectedFundTypes
		bind:selectedStrategyLabels
		bind:selectedGeographies
		bind:selectedDomiciles
		bind:searchQ={catalogSearchQ}
		bind:aumMin={catalogAumMin}
		bind:maxExpenseRatio={catalogMaxER}
		bind:minReturn1y={catalogMinReturn1y}
		bind:minReturn10y={catalogMinReturn10y}
		onFilterChange={applyCatalogFilters}
	/>

	<div class="scr-main">
		<div class="scr-results">
			<CatalogTable
				{catalog}
				searchQ={catalogSearchQ}
				{currentSort}
				onSelectFund={openFundDetail}
				onSendToDDReview={sendClassesToDDReview}
				onPageChange={catalogPageChange}
				onSortChange={handleSortChange}
				onOpenManager={openManagerDetail}
			/>
		</div>
	</div>
</div>

<!-- ════════════════ FUND DETAIL PANEL ════════════════ -->
<ContextPanel open={panelOpen} onClose={closePanel} title={panelTitle} width="min(50vw, 720px)">
	{#if selectedFund}
		<CatalogDetailPanel fund={selectedFund} />
	{/if}
</ContextPanel>

<!-- ════════════════ MANAGER DETAIL PANEL ════════════════ -->
<ContextPanel open={mgrDetailOpen} onClose={() => (mgrDetailOpen = false)} title={mgrDetail?.firm_name ?? "Manager Detail"} width="480px">
	{#if mgrDetailLoading}
		<p class="mgr-loading">Loading...</p>
	{:else if mgrDetail}
		{@const mgr = mgrDetail}
		<div class="mgr-detail">
			<div class="mgr-detail__row"><span class="mgr-detail__label">CIK</span><span>{mgr.cik ?? "\u2014"}</span></div>
			<div class="mgr-detail__row"><span class="mgr-detail__label">CRD</span><span>{mgr.crd_number}</span></div>
			<div class="mgr-detail__row"><span class="mgr-detail__label">Status</span><span>{mgr.registration_status ?? "\u2014"}</span></div>
			<div class="mgr-detail__row"><span class="mgr-detail__label">State</span><span>{mgr.state ?? "\u2014"}</span></div>
			<div class="mgr-detail__row"><span class="mgr-detail__label">AUM</span><span>{mgr.aum_total != null ? formatAUM(mgr.aum_total) : "\u2014"}</span></div>
			<div class="mgr-detail__row"><span class="mgr-detail__label">Holdings</span><span>{mgr.holdings_count}</span></div>
			{#if mgr.website}<div class="mgr-detail__row"><span class="mgr-detail__label">Website</span><span>{mgr.website}</span></div>{/if}
		</div>
		{#if mgr.private_fund_count && mgr.private_fund_count > 0}
			<div class="mgr-fund-section">
				<span class="mgr-fund-title">Private Fund Breakdown</span>
				<div class="mgr-fund-grid">
					{#if mgr.hedge_fund_count}<div class="mgr-fund-stat"><span class="mgr-fund-val">{mgr.hedge_fund_count}</span><span class="mgr-fund-lbl">Hedge</span></div>{/if}
					{#if mgr.pe_fund_count}<div class="mgr-fund-stat"><span class="mgr-fund-val">{mgr.pe_fund_count}</span><span class="mgr-fund-lbl">PE</span></div>{/if}
					{#if mgr.vc_fund_count}<div class="mgr-fund-stat"><span class="mgr-fund-val">{mgr.vc_fund_count}</span><span class="mgr-fund-lbl">VC</span></div>{/if}
					{#if mgr.total_private_fund_assets}<div class="mgr-fund-stat"><span class="mgr-fund-val">{formatAUM(mgr.total_private_fund_assets)}</span><span class="mgr-fund-lbl">GAV</span></div>{/if}
				</div>
			</div>
		{/if}
	{/if}
</ContextPanel>

<style>
	/* Master-detail layout for catalog */
	.scr-master-detail {
		display: flex;
		gap: 24px;
		padding-bottom: 48px;
		align-items: flex-start;
	}

	.scr-main {
		flex: 1;
		min-width: 0;
	}

	.scr-results {
		background: var(--ii-surface);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-lg);
		overflow: hidden;
		box-shadow: none;
	}

	.scr-actions {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.scr-btn {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 10px 20px;
		border-radius: 14px;
		font-size: 14px;
		font-weight: 600;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		transition: all 120ms ease;
		border: none;
	}

	.scr-btn--outline {
		background: transparent;
		border: 1px solid var(--ii-border);
		color: var(--ii-text-secondary);
	}

	.scr-btn--outline:hover {
		background: var(--ii-surface-alt);
		border-color: var(--ii-border-strong);
		color: var(--ii-text-primary);
	}

	/* ── Manager detail panel ── */
	.mgr-loading {
		padding: 24px;
		color: var(--ii-text-muted);
		font-size: 13px;
	}

	.mgr-detail {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 16px;
	}

	.mgr-detail__row {
		display: flex;
		justify-content: space-between;
		font-size: 13px;
	}

	.mgr-detail__label {
		color: var(--ii-text-muted);
		font-weight: 500;
	}

	.mgr-fund-section {
		padding: 16px;
		border-top: 1px solid var(--ii-border-subtle);
	}

	.mgr-fund-title {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted);
	}

	.mgr-fund-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 12px;
		margin-top: 12px;
	}

	.mgr-fund-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.mgr-fund-val {
		font-size: 20px;
		font-weight: 800;
		color: var(--ii-text-primary, #1d293d);
	}

	.mgr-fund-lbl {
		font-size: 11px;
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	@media (max-width: 900px) {
		.scr-master-detail {
			flex-direction: column;
		}
	}
</style>
