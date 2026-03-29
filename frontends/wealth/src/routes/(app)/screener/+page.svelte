<!--
  Unified Screener — Master-Detail view.
  Tab "Catalog": 3-universe fund catalog (eVestment style) with sidebar facets + server-side pagination.
  Tab "Managers": SEC manager analysis (absorbed from /us-fund-analysis).
  Tabs "Equities"|"Fixed Income"|"ETF": tenant instrument universe search.
-->
<script lang="ts">
	import { untrack, getContext } from "svelte";
	import { goto, invalidateAll } from "$app/navigation";
	import { Button } from "@investintell/ui/components/ui/button";
	import { PageHeader, ContextPanel, formatAUM } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";

	// Catalog + Securities types
	import type { UnifiedFundItem, UnifiedCatalogPage, CatalogFacets, SecurityPage, SecurityFacets, SecurityItem, CatalogCategory } from "$lib/types/catalog";
	import { EMPTY_CATALOG_PAGE, EMPTY_FACETS, EMPTY_SECURITY_PAGE, EMPTY_SECURITY_FACETS } from "$lib/types/catalog";

	// Manager types
	import type { SecManagerSearchPage, SecManagerDetail, SecManagerFundBreakdown } from "$lib/types/sec-analysis";
	import { EMPTY_SEARCH_PAGE as EMPTY_MANAGER_PAGE } from "$lib/types/sec-analysis";

	// Components
	import {
		CatalogFilterSidebar,
		CatalogTable,
		CatalogDetailPanel,
		SecuritiesTable,
		SecuritiesFilterSidebar,
		SecManagerTable,
		SecHoldingsTable,
		SecStyleDriftChart,
		SecReverseLookup,
		SecPeerCompare,
	} from "$lib/components/screener";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	let { data }: { data: PageData } = $props();

	// ── Tab from URL ──
	type ScreenerTab = "catalog" | "equities" | "managers";
	const initParams = (untrack(() => data.currentParams) as Record<string, string>) ?? {};
	let activeTab = $state<ScreenerTab>((initParams.tab as ScreenerTab) ?? "catalog");

	// ── Catalog state ──
	let catalog = $derived(((data as any).catalog ?? EMPTY_CATALOG_PAGE) as UnifiedCatalogPage);
	let catalogFacets = $derived(((data as any).catalogFacets ?? EMPTY_FACETS) as CatalogFacets);

	// ── Global Securities state (equities — no RLS) ──
	let securities = $derived(((data as any).securities ?? EMPTY_SECURITY_PAGE) as SecurityPage);
	let securityFacets = $derived(((data as any).securityFacets ?? EMPTY_SECURITY_FACETS) as SecurityFacets);
	let secSearchQ = $state(initParams.q ?? "");
	let secSelectedTypes = $state<string[]>(initParams.security_type ? [initParams.security_type] : []);
	let secSelectedExchanges = $state<string[]>(initParams.exchange ? [initParams.exchange] : []);

	// Catalog filter state (from URL params)
	let selectedCategories = $state<CatalogCategory[]>(
		initParams.category ? (initParams.category.split(",") as CatalogCategory[]) : [],
	);
	let selectedFundTypes = $state<string[]>(initParams.fund_type ? initParams.fund_type.split(",") : []);
	let selectedStrategyLabels = $state<string[]>(initParams.strategy_label ? initParams.strategy_label.split(",") : []);
	let selectedDomiciles = $state<string[]>(initParams.domicile ? initParams.domicile.split(",") : []);
	let catalogSearchQ = $state(initParams.q ?? "");
	let catalogAumMin = $state(initParams.aum_min ?? "");
	let catalogMaxER = $state(initParams.max_expense_ratio ?? "");
	let catalogMinReturn1y = $state(initParams.min_return_1y ?? "");
	let catalogMinReturn10y = $state(initParams.min_return_10y ?? "");

	function buildCatalogParams(): URLSearchParams {
		const params = new URLSearchParams();
		params.set("tab", "catalog");
		if (catalogSearchQ) params.set("q", catalogSearchQ);
		if (selectedCategories.length) params.set("category", selectedCategories.join(","));
		if (selectedFundTypes.length) params.set("fund_type", selectedFundTypes.join(","));
		if (selectedStrategyLabels.length) params.set("strategy_label", selectedStrategyLabels.join(","));
		for (const d of selectedDomiciles) params.append("domicile", d);
		if (catalogAumMin) params.set("aum_min", catalogAumMin);
		if (catalogMaxER) params.set("max_expense_ratio", catalogMaxER);
		if (catalogMinReturn1y) params.set("min_return_1y", catalogMinReturn1y);
		if (catalogMinReturn10y) params.set("min_return_10y", catalogMinReturn10y);
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

	// ── Catalog detail panel ──
	let panelOpen = $state(false);
	let selectedFund = $state<UnifiedFundItem | null>(null);
	let selectedSecurity = $state<SecurityItem | null>(null);
	let panelTitle = $derived(selectedFund?.name ?? selectedSecurity?.name ?? "");

	function openFundDetail(item: UnifiedFundItem) {
		selectedFund = item;
		panelOpen = true;
	}

	function closePanel() {
		panelOpen = false;
		selectedFund = null;
		selectedSecurity = null;
	}

	// ── Send selected classes to DD Review ──
	async function sendClassesToDDReview(items: UnifiedFundItem[]) {
		if (items.length === 0) return;
		// For single selection, import + create DD report + navigate
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
		// For multiple: navigate to DD reports list (batch creation not yet supported)
		goto("/dd-reports");
	}

	// ── Securities tab methods (global equities — no RLS) ──

	function openSecurityDetail(item: SecurityItem) {
		selectedSecurity = item;
		panelOpen = true;
	}

	function applySecurityFilters() {
		const params = new URLSearchParams();
		params.set("tab", "equities");
		if (secSearchQ) params.set("q", secSearchQ);
		if (secSelectedTypes.length === 1) params.set("security_type", secSelectedTypes[0]!);
		if (secSelectedExchanges.length === 1) params.set("exchange", secSelectedExchanges[0]!);
		params.set("page", "1");
		params.set("page_size", "50");
		goto(`/screener?${params.toString()}`, { invalidateAll: true });
	}

	function securitiesPageChange(page: number) {
		const params = new URLSearchParams();
		params.set("tab", "equities");
		if (secSearchQ) params.set("q", secSearchQ);
		if (secSelectedTypes.length === 1) params.set("security_type", secSelectedTypes[0]!);
		if (secSelectedExchanges.length === 1) params.set("exchange", secSelectedExchanges[0]!);
		params.set("page", String(page));
		params.set("page_size", "50");
		goto(`/screener?${params.toString()}`, { invalidateAll: true });
	}

	// ── Manager tab state ──
	let managerResults = $derived(((data as any).managerResults ?? EMPTY_MANAGER_PAGE) as SecManagerSearchPage);
	const api = createClientApiClient(getToken);

	let managerActiveSubTab = $state("overview");
	let mgrFilters = $state({ q: initParams.q ?? "", entity_type: "", state: "", has_13f: "", aum_min: "", fund_type: "" });
	let selectedCik = $state<string | null>(null);
	let selectedManagerName = $state("");
	let compareCiks = $state<Set<string>>(new Set());

	let mgrDetailOpen = $state(false);
	let mgrDetail = $state<SecManagerDetail | null>(null);
	let mgrDetailLoading = $state(false);
	let mgrFundBreakdown = $state<SecManagerFundBreakdown | null>(null);

	function applyManagerFilters() {
		const params = new URLSearchParams();
		params.set("tab", "managers");
		if (mgrFilters.q) params.set("q", mgrFilters.q);
		if (mgrFilters.entity_type) params.set("entity_type", mgrFilters.entity_type);
		if (mgrFilters.state) params.set("state", mgrFilters.state);
		if (mgrFilters.has_13f) params.set("has_13f", mgrFilters.has_13f);
		if (mgrFilters.aum_min) params.set("aum_min", mgrFilters.aum_min);
		if (mgrFilters.fund_type) params.set("fund_type", mgrFilters.fund_type);
		goto(`/screener?${params.toString()}`, { invalidateAll: true });
	}

	function clearManagerFilters() {
		mgrFilters = { q: "", entity_type: "", state: "", has_13f: "", aum_min: "", fund_type: "" };
		goto("/screener?tab=managers", { invalidateAll: true });
	}

	function goToManagerPage(p: number) {
		const params = new URLSearchParams();
		params.set("tab", "managers");
		if (mgrFilters.q) params.set("q", mgrFilters.q);
		params.set("page", String(p));
		goto(`/screener?${params.toString()}`, { invalidateAll: true });
	}

	function selectManager(cik: string, name: string) {
		selectedCik = cik;
		selectedManagerName = name;
		managerActiveSubTab = "holdings";
	}

	async function openManagerDetail(cik: string) {
		mgrDetailOpen = true;
		mgrDetailLoading = true;
		mgrFundBreakdown = null;
		try {
			mgrDetail = await api.get<SecManagerDetail>(`/sec/managers/${cik}`);
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

	function toggleCompare(cik: string) {
		const next = new Set(compareCiks);
		if (next.has(cik)) next.delete(cik);
		else if (next.size < 5) next.add(cik);
		compareCiks = next;
	}

	let managerSubTabs = $derived([
		{ value: "overview", label: "Overview" },
		{ value: "holdings", label: "Holdings" },
		{ value: "style-drift", label: "Style Drift" },
		{ value: "reverse", label: "Reverse Lookup" },
		{ value: "compare", label: `Peer Compare${compareCiks.size > 0 ? ` (${compareCiks.size})` : ""}` },
	]);

	// ── Tab navigation ──
	const TAB_CONFIG: { key: ScreenerTab; label: string }[] = [
		{ key: "catalog", label: "Fund Catalog" },
		{ key: "equities", label: "Equities & ETFs" },
		{ key: "managers", label: "Managers" },
	];

	function selectTab(tab: ScreenerTab) {
		closePanel();
		goto(`/screener?tab=${tab}`, { invalidateAll: true });
	}

	// ── CSV Export ──
	function exportCSV() {
		if (activeTab === "catalog") {
			const items = catalog.items;
			if (items.length === 0) return;
			const headers = ["Universe", "Ticker", "Name", "Manager", "AUM", "Region", "Type"];
			const lines = [
				headers.join(","),
				...items.map(r => [
					r.universe,
					r.ticker ?? "",
					`"${r.name}"`,
					`"${r.manager_name ?? ""}"`,
					r.aum ?? "",
					r.region,
					r.fund_type,
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

<!-- Tab bar -->
<div class="scr-tab-bar">
	{#each TAB_CONFIG as { key, label } (key)}
		<button
			class="scr-tab"
			class:scr-tab--active={activeTab === key}
			onclick={() => selectTab(key)}
		>
			{label}
		</button>
	{/each}
</div>

<!-- ════════════════ CATALOG TAB ════════════════ -->
{#if activeTab === "catalog"}
	<div class="scr-master-detail">
		<CatalogFilterSidebar
			facets={catalogFacets}
			bind:selectedCategories
			bind:selectedFundTypes
			bind:selectedStrategyLabels
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
					onSelectFund={openFundDetail}
					onSendToDDReview={sendClassesToDDReview}
					onPageChange={catalogPageChange}
				/>
			</div>
		</div>
	</div>

<!-- ════════════════ MANAGERS TAB ════════════════ -->
{:else if activeTab === "managers"}
	<div class="scr-page">
		<div class="scr-results">
			<!-- Manager sub-tabs -->
			<div class="scr-sub-tabs">
				{#each managerSubTabs as st (st.value)}
					<button
						class="scr-sub-tab"
						class:scr-sub-tab--active={managerActiveSubTab === st.value}
						onclick={() => (managerActiveSubTab = st.value)}
					>
						{st.label}
					</button>
				{/each}
			</div>

			{#if managerActiveSubTab === "overview"}
				<!-- Manager filters -->
				<div class="mgr-filters">
					<form class="mgr-filters-row" onsubmit={(e) => { e.preventDefault(); applyManagerFilters(); }}>
						<div class="mgr-field">
							<label class="scr-label" for="mgr-q">Search</label>
							<input id="mgr-q" class="scr-input" type="text" placeholder="Name, CIK, CRD..." bind:value={mgrFilters.q} />
						</div>
						<div class="mgr-field">
							<label class="scr-label" for="mgr-type">Fund Type</label>
							<select id="mgr-type" class="scr-select" bind:value={mgrFilters.fund_type}>
								<option value="">All Types</option>
								<option value="hedge">Hedge Funds</option>
								<option value="pe">Private Equity</option>
								<option value="vc">Venture Capital</option>
								<option value="real_estate">Real Estate</option>
							</select>
						</div>
						<div class="mgr-field">
							<label class="scr-label" for="mgr-state">State</label>
							<input id="mgr-state" class="scr-input" type="text" placeholder="NY, CA..." bind:value={mgrFilters.state} />
						</div>
						<div class="mgr-field">
							<label class="scr-label" for="mgr-13f">Has 13F</label>
							<select id="mgr-13f" class="scr-select" bind:value={mgrFilters.has_13f}>
								<option value="">All</option>
								<option value="true">Yes</option>
								<option value="false">No</option>
							</select>
						</div>
						<div class="mgr-field">
							<label class="scr-label" for="mgr-aum">AUM Min ($)</label>
							<input id="mgr-aum" class="scr-input" type="number" placeholder="1000000000" bind:value={mgrFilters.aum_min} />
						</div>
						<div class="mgr-actions">
							<button class="scr-btn-text" type="button" onclick={clearManagerFilters}>Clear</button>
							<button class="scr-btn-sm" type="submit">Apply</button>
						</div>
					</form>
				</div>

				<!-- Manager table -->
				<SecManagerTable
					data={managerResults}
					onSelect={selectManager}
					onDetail={openManagerDetail}
					onPageChange={goToManagerPage}
					{compareCiks}
					onToggleCompare={toggleCompare}
				/>

			{:else if managerActiveSubTab === "holdings"}
				<div class="mgr-tab-content">
					<SecHoldingsTable {api} cik={selectedCik} managerName={selectedManagerName} />
				</div>

			{:else if managerActiveSubTab === "style-drift"}
				<div class="mgr-tab-content">
					<SecStyleDriftChart {api} cik={selectedCik} managerName={selectedManagerName} />
				</div>

			{:else if managerActiveSubTab === "reverse"}
				<div class="mgr-tab-content">
					<SecReverseLookup {api} />
				</div>

			{:else if managerActiveSubTab === "compare"}
				<div class="mgr-tab-content">
					<SecPeerCompare {api} ciks={[...compareCiks]} />
				</div>
			{/if}
		</div>
	</div>

<!-- ════════════════ EQUITIES TAB (global — no RLS) ════════════════ -->
{:else if activeTab === "equities"}
	<div class="scr-master-detail">
		<SecuritiesFilterSidebar
			facets={securityFacets}
			bind:selectedTypes={secSelectedTypes}
			bind:selectedExchanges={secSelectedExchanges}
			bind:searchQ={secSearchQ}
			onFilterChange={applySecurityFilters}
		/>

		<div class="scr-main">
			<div class="scr-results">
				<SecuritiesTable
					{securities}
					searchQ={secSearchQ}
					onSelectSecurity={openSecurityDetail}
					onPageChange={securitiesPageChange}
				/>
			</div>
		</div>
	</div>
{/if}

<!-- ════════════════ CONTEXT PANEL ════════════════ -->
<ContextPanel open={panelOpen} onClose={closePanel} title={panelTitle} width="min(50vw, 720px)">
	{#if selectedFund}
		<CatalogDetailPanel fund={selectedFund} />
	{:else if selectedSecurity}
		<div class="sec-detail">
			<div class="dt-section">
				<div class="dt-fund-meta">
					<span>Ticker: {selectedSecurity.ticker ?? "\u2014"}</span>
					<span>CUSIP: {selectedSecurity.cusip}</span>
					<span>Type: {selectedSecurity.security_type}</span>
					{#if selectedSecurity.exchange}<span>Exchange: {selectedSecurity.exchange}</span>{/if}
					{#if selectedSecurity.figi}<span>FIGI: {selectedSecurity.figi}</span>{/if}
				</div>
			</div>
			<div class="dt-section">
				<p class="dt-empty-text">Import this security to your universe to run screening, DD reports, and quant analysis.</p>
			</div>
		</div>
	{/if}
</ContextPanel>

<!-- Manager detail drawer -->
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
	.scr-page {
		display: flex;
		flex-direction: column;
		gap: 24px;
		padding-bottom: 48px;
	}

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
		background: white;
		border: 1px solid #e2e8f0;
		border-radius: 16px;
		overflow: hidden;
		box-shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px -1px rgba(0,0,0,0.1);
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
		background: white;
		border: 1px solid #e2e8f0;
		color: #45556c;
		box-shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px -1px rgba(0,0,0,0.1);
	}

	.scr-btn--outline:hover {
		background: #f8fafc;
		border-color: #cbd5e1;
	}

	/* ── Top-level tab bar ── */
	.scr-tab-bar {
		display: flex;
		gap: 0;
		padding: 0 0 0;
		border-bottom: 1px solid #e2e8f0;
		margin-bottom: 24px;
	}

	.scr-tab {
		padding: 12px 24px;
		border: none;
		border-bottom: 2px solid transparent;
		background: none;
		font-size: 14px;
		font-weight: 600;
		color: #62748e;
		cursor: pointer;
		font-family: var(--ii-font-sans);
		transition: color 120ms, border-color 120ms;
		white-space: nowrap;
	}

	.scr-tab:hover { color: #1d293d; }

	.scr-tab--active {
		color: #1447e6;
		border-bottom-color: #155dfc;
	}

	/* ── Manager sub-tabs ── */
	.scr-sub-tabs {
		display: flex;
		border-bottom: 1px solid #e2e8f0;
		background: #f8fafc;
	}

	.scr-sub-tab {
		padding: 12px 24px;
		border: none;
		border-bottom: 2px solid transparent;
		background: none;
		font-size: 13px;
		font-weight: 600;
		color: #62748e;
		cursor: pointer;
		font-family: var(--ii-font-sans);
		transition: color 120ms, border-color 120ms;
		white-space: nowrap;
	}

	.scr-sub-tab:hover { color: #1d293d; }

	.scr-sub-tab--active {
		color: #1447e6;
		border-bottom-color: #155dfc;
		background: white;
	}

	/* ── Manager filters ── */
	.mgr-filters {
		padding: 20px 24px;
		border-bottom: 1px solid #f1f5f9;
	}

	.mgr-filters-row {
		display: flex;
		flex-wrap: wrap;
		gap: 16px;
		align-items: flex-end;
	}

	.mgr-field {
		display: flex;
		flex-direction: column;
		gap: 6px;
		min-width: 140px;
		flex: 1;
		max-width: 200px;
	}

	.mgr-actions {
		display: flex;
		gap: 8px;
		align-items: flex-end;
		padding-bottom: 2px;
	}

	.scr-btn-text {
		padding: 8px 16px;
		border: none;
		background: none;
		font-size: 13px;
		font-weight: 600;
		color: #62748e;
		cursor: pointer;
		font-family: var(--ii-font-sans);
	}

	.scr-btn-text:hover { color: #1d293d; }

	.scr-btn-sm {
		padding: 8px 20px;
		border: none;
		border-radius: 10px;
		background: #155dfc;
		color: white;
		font-size: 13px;
		font-weight: 600;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		box-shadow: 0 1px 3px rgba(37,99,235,0.25);
	}

	.scr-btn-sm:hover { background: #1447e6; }

	.mgr-tab-content {
		padding: 24px;
	}

	.mgr-loading {
		padding: 24px;
		color: var(--ii-text-muted);
		font-size: 13px;
	}

	/* ── Manager detail panel ── */
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
