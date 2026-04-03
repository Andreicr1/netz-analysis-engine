<!--
  Unified Screener — Fund Catalog with horizontal filter bar + full-width table.
  Manager detail accessible via click on manager name in catalog table.
-->
<script lang="ts">
	import { untrack, getContext } from "svelte";
	import { goto } from "$app/navigation";
	import { Checkbox } from "@investintell/ui/components/ui/checkbox";
	import { Label } from "@investintell/ui/components/ui/label";
	import * as Tabs from "@investintell/ui/components/ui/tabs";
	import * as Select from "@investintell/ui/components/ui/select";
	import { ContextPanel, formatAUM } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";

	// Catalog types
	import type { UnifiedFundItem, UnifiedCatalogPage, CatalogFacets, CatalogCategory } from "$lib/types/catalog";
	import { EMPTY_FACETS, CATALOG_CATEGORIES } from "$lib/types/catalog";

	// Manager types
	import type { SecManagerDetail, SecManagerFundBreakdown } from "$lib/types/sec-analysis";

	// Components
	import {
		CatalogTable,
		CatalogDetailPanel,
		ScreeningRunPanel,
	} from "$lib/components/screener";

	// Screening types
	import type { ScreeningRun, ScreeningResult } from "$lib/types/screening";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	let { data }: { data: PageData } = $props();

	const initParams = (untrack(() => data.currentParams) as Record<string, string>) ?? {};

	// ── Tab state ──
	let activeTab = $state<"catalog" | "screening">(
		(untrack(() => data.tab) as string) === "screening" ? "screening" : "catalog",
	);

	function switchTab(tab: "catalog" | "screening") {
		activeTab = tab;
		if (tab === "catalog") {
			const params = buildCatalogParams();
			params.set("page", "1");
			params.set("page_size", "50");
			goto(`/screener?${params.toString()}`, { invalidateAll: true });
		} else {
			goto("?tab=screening", { invalidateAll: true });
		}
	}

	// ── Catalog state ──
	let catalogFacets = $derived(((data as any).catalogFacets ?? EMPTY_FACETS) as CatalogFacets);

	// ── Screening state ──
	let screeningRuns = $derived(((data as any).screeningRuns ?? []) as ScreeningRun[]);
	let screeningResults = $derived(((data as any).screeningResults ?? []) as ScreeningResult[]);

	// Catalog filter state (from URL params)
	let selectedCategories = $state<CatalogCategory[]>(
		initParams.category ? (initParams.category.split(",") as CatalogCategory[]) : ["mutual_fund" as CatalogCategory],
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
	let showAllFunds = $state(initParams.has_aum === "false");

	// ── Infinite scroll state ──
	let allCatalogItems = $state<UnifiedFundItem[]>([]);
	let totalCatalogCount = $state(0);
	let isLoadingMore = $state(false);
	let hasMore = $state(true);
	let clientPage = $state(2);
	let fetchAbortCtrl: AbortController | null = null;
	let sentinelEl = $state<HTMLElement | null>(null);

	// Initialize from SSR data
	$effect.pre(() => {
		const serverCatalog = (data as any).catalog as UnifiedCatalogPage | undefined;
		if (serverCatalog && allCatalogItems.length === 0) {
			allCatalogItems = serverCatalog.items ?? [];
			totalCatalogCount = serverCatalog.total ?? 0;
			hasMore = serverCatalog.has_next ?? false;
			clientPage = 2;
		}
	});

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
		if (showAllFunds) params.set("has_aum", "false");
		return params;
	}

	// ── Client-side fetch for infinite scroll ──
	async function fetchCatalogPage(page: number, reset: boolean): Promise<void> {
		if (fetchAbortCtrl) fetchAbortCtrl.abort();
		fetchAbortCtrl = new AbortController();

		isLoadingMore = true;
		try {
			const params = buildCatalogParams();
			params.set("page", String(page));
			params.set("page_size", "50");

			history.replaceState(null, "", `/screener?${params.toString()}`);

			const result = await api.get<UnifiedCatalogPage>(
				"/screener/catalog",
				Object.fromEntries(params.entries()),
				{ signal: fetchAbortCtrl.signal },
			);

			if (reset) {
				allCatalogItems = result.items ?? [];
			} else {
				allCatalogItems = [...allCatalogItems, ...(result.items ?? [])];
			}
			totalCatalogCount = result.total ?? 0;
			hasMore = result.has_next ?? false;
			clientPage = page + 1;
		} catch (err: unknown) {
			if (err instanceof Error && err.name === "AbortError") return;
			console.error("catalog fetch failed", err);
		} finally {
			isLoadingMore = false;
		}
	}

	async function loadMore(): Promise<void> {
		if (isLoadingMore || !hasMore) return;
		await fetchCatalogPage(clientPage, false);
	}

	async function resetAndFetch(): Promise<void> {
		allCatalogItems = [];
		clientPage = 1;
		hasMore = true;
		await fetchCatalogPage(1, true);
	}

	function applyCatalogFilters() {
		resetAndFetch();
	}

	function handleSortChange(sort: string) {
		currentSort = sort;
		resetAndFetch();
	}

	// ── IntersectionObserver for sentinel ──
	$effect(() => {
		if (!sentinelEl) return;
		const observer = new IntersectionObserver(
			(entries) => {
				if (entries[0]?.isIntersecting && !isLoadingMore && hasMore) {
					loadMore();
				}
			},
			{ rootMargin: "200px" },
		);
		observer.observe(sentinelEl);
		return () => observer.disconnect();
	});

	// ── Synthetic catalog for CatalogTable ──
	let syntheticCatalog = $derived<UnifiedCatalogPage>({
		items: allCatalogItems,
		total: totalCatalogCount,
		page: clientPage - 1,
		page_size: 50,
		has_next: hasMore,
		facets: null,
	});

	function clearAllFilters() {
		selectedCategories = [];
		selectedFundTypes = [];
		selectedStrategyLabels = [];
		selectedGeographies = [];
		selectedDomiciles = [];
		catalogSearchQ = "";
		catalogAumMin = "";
		catalogMaxER = "";
		catalogMinReturn1y = "";
		catalogMinReturn10y = "";
		showAllFunds = false;
		applyCatalogFilters();
	}

	let hasActiveFilters = $derived(
		selectedCategories.length > 0 ||
		selectedStrategyLabels.length > 0 ||
		selectedGeographies.length > 0 ||
		catalogAumMin.length > 0 ||
		catalogMaxER.length > 0 ||
		catalogSearchQ.length > 0 ||
		showAllFunds
	);

	// Debounce for search input
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;
	function debouncedSearch() {
		if (debounceTimer) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => applyCatalogFilters(), 400);
	}

	function handleSearchKeydown(e: KeyboardEvent) {
		if (e.key === "Enter") {
			if (debounceTimer) clearTimeout(debounceTimer);
			applyCatalogFilters();
		}
	}

	// ── Catalog detail panel ──
	let panelOpen = $state(false);
	let selectedFund = $state<UnifiedFundItem | null>(null);
	let panelTitle = $derived(selectedFund?.name ?? "");

	let enrichingDetail = $state(false);

	function openFundDetail(item: UnifiedFundItem) {
		goto(`/screener/fund/${item.external_id}`);
	}

	async function enrichDetail(externalId: string) {
		enrichingDetail = true;
		try {
			const enriched = await api.get<UnifiedFundItem>(`/screener/catalog/${encodeURIComponent(externalId)}/detail`);
			if (selectedFund && selectedFund.external_id === externalId) {
				selectedFund = { ...selectedFund, ...enriched };
			}
		} catch {
			// Fallback to catalog data — already displayed
		} finally {
			enrichingDetail = false;
		}
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
		const items = allCatalogItems;
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

<div class="scr-page">
	<!-- ════════════════ HEADER BAR ════════════════ -->
	<div class="scr-topbar">
		<div class="scr-topbar-left">
			<h1 class="scr-title">Screener</h1>
		</div>
		<div class="scr-topbar-right">
			{#if activeTab === "catalog"}
				<button class="scr-btn scr-btn--outline" onclick={exportCSV}>
					<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
					Export
				</button>
			{/if}
		</div>
	</div>

	<!-- ════════════════ TABS ════════════════ -->
	<Tabs.Root bind:value={activeTab} onValueChange={(v) => switchTab(v)}>
		<Tabs.List class="scr-tabs">
			<Tabs.Trigger value="catalog">Catalog</Tabs.Trigger>
			<Tabs.Trigger value="screening">Screening</Tabs.Trigger>
		</Tabs.List>
	</Tabs.Root>

	{#if activeTab === "catalog"}
	<!-- ════════════════ FILTER BAR ════════════════ -->
	<div class="scr-filterbar">
		<input
			class="scr-search"
			type="text"
			placeholder="Search funds, managers..."
			bind:value={catalogSearchQ}
			oninput={debouncedSearch}
			onkeydown={handleSearchKeydown}
		/>

		<Select.Root type="single" value={selectedCategories[0] ?? ""} onValueChange={(v) => { selectedCategories = v ? [v as CatalogCategory] : []; selectedFundTypes = []; selectedStrategyLabels = []; applyCatalogFilters(); }}>
			<Select.Trigger class="h-[34px] w-auto min-w-[140px] text-[13px]">
				{selectedCategories[0] ? CATALOG_CATEGORIES.find(c => c.key === selectedCategories[0])?.label ?? "All Universes" : "All Universes"}
			</Select.Trigger>
			<Select.Content>
				<Select.Item value="">All Universes</Select.Item>
				{#each CATALOG_CATEGORIES as cat (cat.key)}
					<Select.Item value={cat.key}>{cat.label}</Select.Item>
				{/each}
			</Select.Content>
		</Select.Root>

		{#if catalogFacets.strategy_labels.length > 0}
			<Select.Root type="single" value={selectedStrategyLabels[0] ?? ""} onValueChange={(v) => { selectedStrategyLabels = v ? [v] : []; applyCatalogFilters(); }}>
				<Select.Trigger class="h-[34px] w-auto min-w-[140px] text-[13px]">
					{selectedStrategyLabels[0] ? catalogFacets.strategy_labels.find(s => s.value === selectedStrategyLabels[0])?.label ?? "All Strategies" : "All Strategies"}
				</Select.Trigger>
				<Select.Content>
					<Select.Item value="">All Strategies</Select.Item>
					{#each catalogFacets.strategy_labels as item (item.value)}
						<Select.Item value={item.value}>{item.label} ({item.count?.toLocaleString() ?? "\u2014"})</Select.Item>
					{/each}
				</Select.Content>
			</Select.Root>
		{/if}

		{#if catalogFacets.geographies.length > 0}
			<Select.Root type="single" value={selectedGeographies[0] ?? ""} onValueChange={(v) => { selectedGeographies = v ? [v] : []; applyCatalogFilters(); }}>
				<Select.Trigger class="h-[34px] w-auto min-w-[140px] text-[13px]">
					{selectedGeographies[0] ? catalogFacets.geographies.find(g => g.value === selectedGeographies[0])?.label ?? "All Geographies" : "All Geographies"}
				</Select.Trigger>
				<Select.Content>
					<Select.Item value="">All Geographies</Select.Item>
					{#each catalogFacets.geographies as item (item.value)}
						<Select.Item value={item.value}>{item.label} ({item.count?.toLocaleString() ?? "\u2014"})</Select.Item>
					{/each}
				</Select.Content>
			</Select.Root>
		{/if}

		<Select.Root type="single" value={catalogAumMin} onValueChange={(v) => { catalogAumMin = v; applyCatalogFilters(); }}>
			<Select.Trigger class="h-[34px] w-auto min-w-[140px] text-[13px]">
				{catalogAumMin === "100000000" ? "AUM $100M+" : catalogAumMin === "500000000" ? "AUM $500M+" : catalogAumMin === "1000000000" ? "AUM $1B+" : catalogAumMin === "5000000000" ? "AUM $5B+" : catalogAumMin === "10000000000" ? "AUM $10B+" : catalogAumMin === "50000000000" ? "AUM $50B+" : "AUM: Any"}
			</Select.Trigger>
			<Select.Content>
				<Select.Item value="">AUM: Any</Select.Item>
				<Select.Item value="100000000">AUM $100M+</Select.Item>
				<Select.Item value="500000000">AUM $500M+</Select.Item>
				<Select.Item value="1000000000">AUM $1B+</Select.Item>
				<Select.Item value="5000000000">AUM $5B+</Select.Item>
				<Select.Item value="10000000000">AUM $10B+</Select.Item>
				<Select.Item value="50000000000">AUM $50B+</Select.Item>
			</Select.Content>
		</Select.Root>

		<Select.Root type="single" value={catalogMaxER} onValueChange={(v) => { catalogMaxER = v; applyCatalogFilters(); }}>
			<Select.Trigger class="h-[34px] w-auto min-w-[140px] text-[13px]">
				{catalogMaxER === "0.10" ? "ER \u2264 0.10%" : catalogMaxER === "0.25" ? "ER \u2264 0.25%" : catalogMaxER === "0.50" ? "ER \u2264 0.50%" : catalogMaxER === "0.75" ? "ER \u2264 0.75%" : catalogMaxER === "1.00" ? "ER \u2264 1.00%" : catalogMaxER === "1.50" ? "ER \u2264 1.50%" : "ER: Any"}
			</Select.Trigger>
			<Select.Content>
				<Select.Item value="">ER: Any</Select.Item>
				<Select.Item value="0.10">ER \u2264 0.10%</Select.Item>
				<Select.Item value="0.25">ER \u2264 0.25%</Select.Item>
				<Select.Item value="0.50">ER \u2264 0.50%</Select.Item>
				<Select.Item value="0.75">ER \u2264 0.75%</Select.Item>
				<Select.Item value="1.00">ER \u2264 1.00%</Select.Item>
				<Select.Item value="1.50">ER \u2264 1.50%</Select.Item>
			</Select.Content>
		</Select.Root>

		<div class="scr-toggle">
			<Checkbox id="scr-show-all" checked={showAllFunds} onCheckedChange={() => { showAllFunds = !showAllFunds; applyCatalogFilters(); }} />
			<Label for="scr-show-all">Include all</Label>
		</div>

		{#if hasActiveFilters}
			<button class="scr-clear-btn" onclick={clearAllFilters}>Clear</button>
		{/if}
	</div>

	<!-- ════════════════ CATALOG TABLE ════════════════ -->
	{#if totalCatalogCount === 0 && !catalogSearchQ && selectedCategories.length <= 1}
		<div class="scr-error-banner">
			Unable to load fund catalog. The backend may be unavailable.
		</div>
	{/if}
	<div class="scr-table-card">
		<CatalogTable
			catalog={syntheticCatalog}
			searchQ={catalogSearchQ}
			{currentSort}
			infiniteScroll={true}
			{isLoadingMore}
			bind:sentinelEl
			onSelectFund={openFundDetail}
			onSendToDDReview={sendClassesToDDReview}
			onSortChange={handleSortChange}
			onOpenManager={openManagerDetail}
		/>
	</div>
	{:else}
	<!-- ════════════════ SCREENING TAB ════════════════ -->
	<ScreeningRunPanel runs={screeningRuns} results={screeningResults} />
	{/if}
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
	/* ── Full-height page layout ── */
	.scr-page {
		display: flex;
		flex-direction: column;
		height: calc(100vh - 48px);
		overflow: hidden;
	}

	/* ── Top bar (title + export) ── */
	.scr-topbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 24px 0;
		flex-shrink: 0;
	}

	.scr-topbar-left {
		display: flex;
		align-items: center;
		gap: 16px;
	}

	.scr-topbar-right {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.scr-title {
		font-size: 24px;
		font-weight: 800;
		color: var(--ii-text-primary);
		margin: 0;
	}

	/* ── Tabs (shadcn overrides) ── */
	.scr-tabs {
		padding: 0 24px;
		flex-shrink: 0;
	}

	/* ── Horizontal filter bar ── */
	.scr-filterbar {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 12px 24px;
		flex-shrink: 0;
		flex-wrap: wrap;
	}

	.scr-search {
		width: 220px;
		height: 34px;
		padding: 0 10px 0 34px;
		border: 1px solid var(--ii-border);
		border-radius: 8px;
		background: var(--ii-surface-elevated);
		font-size: 13px;
		color: var(--ii-text-primary);
		font-family: var(--ii-font-sans);
		background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%2390a1b9' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.3-4.3'/%3E%3C/svg%3E");
		background-repeat: no-repeat;
		background-position: 10px center;
	}

	.scr-search::placeholder { color: var(--ii-text-muted); }
	.scr-search:focus {
		outline: none;
		border-color: var(--ii-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-brand-primary) 15%, transparent);
	}

	.scr-toggle {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 13px;
		color: var(--ii-text-secondary);
		cursor: pointer;
		white-space: nowrap;
		user-select: none;
	}

	.scr-clear-btn {
		height: 34px;
		padding: 0 14px;
		border: 1px solid var(--ii-border);
		border-radius: 8px;
		background: transparent;
		color: var(--ii-text-secondary);
		font-size: 13px;
		font-weight: 600;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		transition: all 120ms ease;
	}

	.scr-clear-btn:hover {
		background: var(--ii-surface-alt);
		color: var(--ii-text-primary);
	}

	/* ── Table card (fills remaining height, internal scroll) ── */
	.scr-table-card {
		flex: 1;
		min-height: 0;
		margin: 0 24px 16px;
		background: var(--ii-surface);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-lg);
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.scr-error-banner {
		padding: 12px 24px;
		background: color-mix(in srgb, var(--ii-warning) 10%, transparent);
		border: 1px solid var(--ii-warning);
		border-radius: var(--ii-radius-md);
		color: var(--ii-text-primary);
		font-size: 13px;
		font-weight: 500;
		margin: 0 24px;
		flex-shrink: 0;
	}

	.scr-btn {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 8px 16px;
		border-radius: 8px;
		font-size: 13px;
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
</style>
