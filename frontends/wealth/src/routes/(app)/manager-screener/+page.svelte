<!--
  Manager Screener — SEC EDGAR Workstation.
  Paginated table with checkbox selection, 5-block filter sidebar,
  peer comparison mode, 4-tab detail drawer with lazy fetch, add-to-universe.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { goto, invalidateAll } from "$app/navigation";
	import { page } from "$app/stores";
	import {
		PageHeader, Button, ContextPanel, StatusBadge, ConsequenceDialog,
		formatAUM, formatNumber, formatPercent, formatDate,
	} from "@netz/ui";
	import type { ConsequenceDialogPayload } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type {
		ManagerRow, ScreenerPage, ManagerProfile, HoldingsData,
		InstitutionalData, UniverseStatus, CompareResult, DetailTab,
	} from "$lib/types/manager-screener";
	import { EMPTY_SCREENER } from "$lib/types/manager-screener";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let screener = $derived((data.screener ?? EMPTY_SCREENER) as ScreenerPage);

	// ── Filter state ──────────────────────────────────────────────────────

	const initParams = data.currentParams as Record<string, string> ?? {};
	let textSearch = $state(initParams.text_search ?? "");
	let aumMin = $state(initParams.aum_min ?? "");
	let aumMax = $state(initParams.aum_max ?? "");
	let complianceClean = $state(initParams.compliance_clean === "true");
	let hasInstitutional = $state(initParams.has_institutional_holders === "true");

	function applyFilters() {
		const params = new URLSearchParams();
		if (textSearch) params.set("text_search", textSearch);
		if (aumMin) params.set("aum_min", aumMin);
		if (aumMax) params.set("aum_max", aumMax);
		if (complianceClean) params.set("compliance_clean", "true");
		if (hasInstitutional) params.set("has_institutional_holders", "true");
		params.set("page", "1");
		params.set("page_size", "25");
		goto(`/manager-screener?${params.toString()}`, { invalidateAll: true });
	}

	function clearFilters() {
		textSearch = "";
		aumMin = "";
		aumMax = "";
		complianceClean = false;
		hasInstitutional = false;
		goto("/manager-screener", { invalidateAll: true });
	}

	function goToPage(p: number) {
		const params = new URLSearchParams($page.url.searchParams);
		params.set("page", String(p));
		goto(`/manager-screener?${params.toString()}`, { invalidateAll: true });
	}

	function handleFilterKeydown(e: KeyboardEvent) {
		if (e.key === "Enter") applyFilters();
	}

	// ── Selection state (checkboxes for peer comparison) ──────────────────

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

	// ── Peer Comparison ───────────────────────────────────────────────────

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

	// All unique sectors across compared managers for overlap chart
	let compareSectors = $derived.by(() => {
		if (!compareResult?.sector_allocations) return [];
		const all = new Set<string>();
		for (const alloc of Object.values(compareResult.sector_allocations)) {
			for (const s of Object.keys(alloc)) all.add(s);
		}
		return [...all].sort();
	});

	// ── Detail panel (single manager drill-down) ──────────────────────────

	let panelOpen = $state(false);
	let panelCrd = $state<string | null>(null);
	let panelFirm = $state("");
	let activeTab = $state<DetailTab>("profile");
	let detailLoading = $state(false);

	let profileData = $state<ManagerProfile | null>(null);
	let holdingsData = $state<HoldingsData | null>(null);
	let institutionalData = $state<InstitutionalData | null>(null);
	let universeData = $state<UniverseStatus | null>(null);

	async function openDetail(manager: ManagerRow) {
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

	function closeDetail() {
		panelOpen = false;
		panelCrd = null;
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
			// Refresh universe status
			universeData = await api.get<UniverseStatus>(`/manager-screener/managers/${panelCrd}/universe-status`);
			await invalidateAll();
		} catch (e) {
			addError = e instanceof Error ? e.message : "Failed to add";
		} finally {
			adding = false;
		}
	}

	// ── Helpers ───────────────────────────────────────────────────────────

	function sectorBarWidth(alloc: Record<string, number>, sector: string): number {
		const max = Math.max(...Object.values(alloc), 0.01);
		return ((alloc[sector] ?? 0) / max) * 100;
	}
</script>

<PageHeader title="Manager Screener">
	{#snippet actions()}
		<div class="ms-actions">
			{#if canCompare}
				<Button size="sm" onclick={runCompare} disabled={comparing}>
					{comparing ? "Comparing…" : `Compare ${selectionCount}`}
				</Button>
			{/if}
			{#if selectionCount > 0}
				<Button size="sm" variant="ghost" onclick={clearCompare}>Clear</Button>
			{/if}
		</div>
	{/snippet}
</PageHeader>

<div class="ms-layout">
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- LEFT: Filter panel                                                 -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<aside class="ms-filters">
		<div class="ms-filter-section">
			<h3 class="ms-filter-title">Firm</h3>
			<div class="ms-field">
				<input class="ms-input" type="text" placeholder="Firm name…" bind:value={textSearch} onkeydown={handleFilterKeydown} />
			</div>
			<div class="ms-field-row">
				<input class="ms-input ms-input--half" type="number" placeholder="AUM min" bind:value={aumMin} onkeydown={handleFilterKeydown} />
				<input class="ms-input ms-input--half" type="number" placeholder="AUM max" bind:value={aumMax} onkeydown={handleFilterKeydown} />
			</div>
			<label class="ms-checkbox">
				<input type="checkbox" bind:checked={complianceClean} />
				<span>Compliance clean</span>
			</label>
		</div>

		<div class="ms-filter-section">
			<h3 class="ms-filter-title">Institutional</h3>
			<label class="ms-checkbox">
				<input type="checkbox" bind:checked={hasInstitutional} />
				<span>Has institutional holders</span>
			</label>
		</div>

		<div class="ms-filter-actions">
			<Button size="sm" onclick={applyFilters}>Apply</Button>
			<Button size="sm" variant="ghost" onclick={clearFilters}>Clear</Button>
		</div>

		<div class="ms-filter-count">
			{screener.total_count} manager{screener.total_count !== 1 ? "s" : ""}
		</div>
	</aside>

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- RIGHT: Results table OR Compare view                               -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<section class="ms-main">
		{#if compareResult}
			<!-- ── PEER COMPARISON VIEW ──────────────────────────────── -->
			<div class="ms-compare">
				<div class="ms-compare-header">
					<h3 class="ms-compare-title">Peer Comparison</h3>
					<span class="ms-compare-overlap">
						Portfolio Overlap (Jaccard): <strong>{(compareResult.jaccard_overlap * 100).toFixed(1)}%</strong>
					</span>
					<Button size="sm" variant="ghost" onclick={clearCompare}>Back to list</Button>
				</div>

				<!-- Manager cards row -->
				<div class="ms-compare-cards">
					{#each compareResult.managers as mgr (mgr.crd_number)}
						<div class="ms-compare-card">
							<span class="ms-cc-name">{mgr.firm_name}</span>
							<span class="ms-cc-aum">{mgr.aum_total ? formatAUM(mgr.aum_total) : "—"}</span>
							<span class="ms-cc-crd">CRD {mgr.crd_number}</span>
						</div>
					{/each}
				</div>

				<!-- Sector allocation overlap -->
				{#if compareSectors.length > 0}
					<div class="ms-compare-sectors">
						<h4 class="ms-compare-subtitle">Sector Allocation</h4>
						<div class="ms-sector-grid">
							<!-- Header: sector name + one col per manager -->
							<div class="ms-sg-header">
								<span class="ms-sg-label">Sector</span>
								{#each compareResult.managers as mgr (mgr.crd_number)}
									<span class="ms-sg-mgr">{mgr.firm_name.slice(0, 12)}</span>
								{/each}
							</div>
							{#each compareSectors as sector (sector)}
								<div class="ms-sg-row">
									<span class="ms-sg-label">{sector}</span>
									{#each compareResult.managers as mgr (mgr.crd_number)}
										{@const alloc = compareResult.sector_allocations[mgr.crd_number] ?? {}}
										{@const pct = alloc[sector] ?? 0}
										<div class="ms-sg-cell">
											<div class="ms-sg-bar-track">
												<div class="ms-sg-bar-fill" style:width="{pct * 100}%"></div>
											</div>
											<span class="ms-sg-pct">{(pct * 100).toFixed(1)}%</span>
										</div>
									{/each}
								</div>
							{/each}
						</div>
					</div>
				{/if}
			</div>
		{:else}
			<!-- ── RESULTS TABLE ─────────────────────────────────────── -->
			{#if screener.managers.length === 0}
				<div class="ms-empty">No managers found. Adjust filters or search.</div>
			{:else}
				<div class="ms-table-wrap">
					<table class="ms-table">
						<thead>
							<tr>
								<th class="mth-check"></th>
								<th class="mth-name">Firm</th>
								<th class="mth-aum">AUM</th>
								<th class="mth-state">Location</th>
								<th class="mth-hhi">HHI</th>
								<th class="mth-pos">Positions</th>
								<th class="mth-comp">Disclosures</th>
								<th class="mth-inst">Institutional</th>
								<th class="mth-univ">Universe</th>
							</tr>
						</thead>
						<tbody>
							{#each screener.managers as manager (manager.crd_number)}
								<tr
									class="ms-row"
									class:ms-row--selected={selectedManagers.has(manager.crd_number)}
									onclick={() => openDetail(manager)}
								>
									<td class="mtd-check" onclick={(e) => e.stopPropagation()}>
										<input
											type="checkbox"
											checked={selectedManagers.has(manager.crd_number)}
											onchange={() => toggleSelection(manager.crd_number)}
										/>
									</td>
									<td class="mtd-name">
										<span class="ms-firm-name">{manager.firm_name}</span>
										<span class="ms-firm-crd">CRD {manager.crd_number}</span>
									</td>
									<td class="mtd-aum">{manager.aum_total ? formatAUM(manager.aum_total) : "—"}</td>
									<td class="mtd-loc">{manager.state ?? ""}{manager.state && manager.country ? ", " : ""}{manager.country ?? ""}</td>
									<td class="mtd-hhi">{manager.hhi !== null ? manager.hhi.toFixed(2) : "—"}</td>
									<td class="mtd-pos">{manager.position_count ?? "—"}</td>
									<td class="mtd-comp">{manager.compliance_disclosures ?? 0}</td>
									<td class="mtd-inst">{manager.has_institutional_holders ? "Yes" : "—"}</td>
									<td class="mtd-univ">
										{#if manager.universe_status}
											<StatusBadge status={manager.universe_status} />
										{:else}
											<span class="ms-not-added">—</span>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>

				<!-- Pagination -->
				<div class="ms-pagination">
					<button
						class="ms-page-btn"
						disabled={screener.page <= 1}
						onclick={() => goToPage(screener.page - 1)}
					>Previous</button>
					<span class="ms-page-info">
						Page {screener.page} · {screener.total_count} total
					</span>
					<button
						class="ms-page-btn"
						disabled={!screener.has_next}
						onclick={() => goToPage(screener.page + 1)}
					>Next</button>
				</div>
			{/if}
		{/if}

		{#if compareError}
			<div class="ms-error">{compareError}</div>
		{/if}
	</section>
</div>

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- DETAIL PANEL — 4 tabs with lazy fetch via {@render}                    -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
<ContextPanel open={panelOpen} onClose={closeDetail} title={panelFirm} width="480px">
	{#if panelCrd}
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
	{/if}
</ContextPanel>

<!-- ── Tab render snippets (lazy — only rendered when active) ────────── -->

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
					<div class="dt-fund-row">
						<span class="dt-fund-name">{fund.fund_name}</span>
						<span class="dt-fund-meta">{fund.fund_type ?? ""} · {fund.gross_asset_value ? formatAUM(fund.gross_asset_value) : "—"}</span>
					</div>
				{/each}
			</div>
		{/if}
		{#if profileData.team.length > 0}
			<div class="dt-section">
				<h4 class="dt-section-title">Team ({profileData.team.length})</h4>
				{#each profileData.team as member (member.person_name)}
					<div class="dt-team-row">
						<span class="dt-team-name">{member.person_name}</span>
						<span class="dt-team-role">{member.title ?? member.role ?? ""}</span>
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
					<div class="dt-holding-row">
						<span class="dt-hold-name">{h.issuer_name}</span>
						<span class="dt-hold-meta">{h.sector ?? ""} · {h.weight ? formatPercent(h.weight) : "—"}</span>
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
					<div class="dt-holder-row">
						<span class="dt-holder-name">{holder.filer_name}</span>
						<span class="dt-holder-meta">{holder.filer_type ?? ""} · {holder.market_value ? formatAUM(holder.market_value) : "—"}</span>
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

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- ADD TO UNIVERSE DIALOG                                                 -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
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
	/* ── Layout ──────────────────────────────────────────────────────────── */
	.ms-layout {
		display: grid;
		grid-template-columns: 240px 1fr;
		height: calc(100vh - 64px);
		overflow: hidden;
	}

	.ms-actions {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-xs, 6px);
	}

	/* ── Filter sidebar ──────────────────────────────────────────────────── */
	.ms-filters {
		overflow-y: auto;
		border-right: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-elevated);
		padding: 0;
	}

	.ms-filter-section {
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 14px);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.ms-filter-title {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--netz-text-muted);
		margin-bottom: var(--netz-space-stack-2xs, 6px);
	}

	.ms-field {
		margin-bottom: var(--netz-space-stack-xs, 8px);
	}

	.ms-field-row {
		display: flex;
		gap: var(--netz-space-inline-xs, 6px);
		margin-bottom: var(--netz-space-stack-xs, 8px);
	}

	.ms-input {
		width: 100%;
		height: var(--netz-space-control-height-sm, 30px);
		padding: 0 var(--netz-space-inline-xs, 8px);
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 6px);
		background: var(--netz-surface);
		color: var(--netz-text-primary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-sans);
	}

	.ms-input--half { width: 50%; }

	.ms-input:focus {
		outline: none;
		border-color: var(--netz-border-focus);
	}

	.ms-input::placeholder { color: var(--netz-text-muted); }

	.ms-checkbox {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-xs, 6px);
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-secondary);
		cursor: pointer;
		margin-bottom: var(--netz-space-stack-2xs, 4px);
	}

	.ms-filter-actions {
		display: flex;
		gap: var(--netz-space-inline-xs, 6px);
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 14px);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.ms-filter-count {
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-md, 14px);
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
		font-variant-numeric: tabular-nums;
	}

	/* ── Main area ───────────────────────────────────────────────────────── */
	.ms-main {
		display: flex;
		flex-direction: column;
		overflow: hidden;
		background: var(--netz-surface);
	}

	.ms-empty {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--netz-text-muted);
		font-size: var(--netz-text-body, 0.9375rem);
	}

	.ms-error {
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
		color: var(--netz-danger);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	/* ── Table ────────────────────────────────────────────────────────────── */
	.ms-table-wrap {
		flex: 1;
		overflow: auto;
	}

	.ms-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.ms-table thead {
		position: sticky;
		top: 0;
		z-index: 1;
	}

	.ms-table th {
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

	.ms-table td {
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-sm, 10px);
		border-bottom: 1px solid var(--netz-border-subtle);
		vertical-align: middle;
	}

	.ms-row {
		cursor: pointer;
		transition: background-color 80ms ease;
	}

	.ms-row:hover {
		background: var(--netz-surface-highlight, color-mix(in srgb, var(--netz-brand-primary) 4%, transparent));
	}

	.ms-row--selected {
		background: color-mix(in srgb, var(--netz-brand-primary) 8%, transparent);
	}

	.mth-check { width: 32px; }
	.mth-name { min-width: 180px; }
	.mth-aum { width: 100px; text-align: right; }
	.mth-state { width: 90px; }
	.mth-hhi { width: 60px; text-align: right; }
	.mth-pos { width: 60px; text-align: right; }
	.mth-comp { width: 60px; text-align: right; }
	.mth-inst { width: 70px; }
	.mth-univ { width: 80px; }

	.mtd-name { display: flex; flex-direction: column; gap: 1px; }
	.ms-firm-name { font-weight: 500; color: var(--netz-text-primary); }
	.ms-firm-crd { font-size: var(--netz-text-label, 0.75rem); color: var(--netz-text-muted); }
	.mtd-aum { text-align: right; font-variant-numeric: tabular-nums; color: var(--netz-text-primary); }
	.mtd-loc { color: var(--netz-text-secondary); }
	.mtd-hhi { text-align: right; font-variant-numeric: tabular-nums; color: var(--netz-text-secondary); }
	.mtd-pos { text-align: right; font-variant-numeric: tabular-nums; color: var(--netz-text-secondary); }
	.mtd-comp { text-align: right; font-variant-numeric: tabular-nums; }
	.ms-not-added { color: var(--netz-text-muted); }

	/* ── Pagination ──────────────────────────────────────────────────────── */
	.ms-pagination {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--netz-space-inline-md, 16px);
		padding: var(--netz-space-stack-xs, 10px);
		border-top: 1px solid var(--netz-border-subtle);
		flex-shrink: 0;
	}

	.ms-page-btn {
		padding: 4px 12px;
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 6px);
		background: transparent;
		color: var(--netz-text-secondary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-sans);
		cursor: pointer;
	}

	.ms-page-btn:disabled {
		opacity: 0.4;
		cursor: default;
	}

	.ms-page-btn:not(:disabled):hover {
		background: var(--netz-surface-alt);
	}

	.ms-page-info {
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-muted);
		font-variant-numeric: tabular-nums;
	}

	/* ── Compare view ────────────────────────────────────────────────────── */
	.ms-compare {
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
		overflow-y: auto;
		flex: 1;
	}

	.ms-compare-header {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-md, 16px);
		margin-bottom: var(--netz-space-stack-md, 16px);
	}

	.ms-compare-title {
		font-size: var(--netz-text-h4, 1.125rem);
		font-weight: 700;
		color: var(--netz-text-primary);
	}

	.ms-compare-overlap {
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-secondary);
		margin-left: auto;
	}

	.ms-compare-cards {
		display: flex;
		gap: var(--netz-space-inline-sm, 10px);
		margin-bottom: var(--netz-space-stack-md, 16px);
		overflow-x: auto;
	}

	.ms-compare-card {
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

	.ms-cc-name { font-weight: 600; font-size: var(--netz-text-small, 0.8125rem); color: var(--netz-text-primary); }
	.ms-cc-aum { font-size: var(--netz-text-label, 0.75rem); color: var(--netz-text-secondary); font-variant-numeric: tabular-nums; }
	.ms-cc-crd { font-size: 10px; color: var(--netz-text-muted); }

	.ms-compare-subtitle {
		font-size: var(--netz-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--netz-text-primary);
		margin-bottom: var(--netz-space-stack-xs, 8px);
	}

	.ms-sector-grid {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.ms-sg-header, .ms-sg-row {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-xs, 6px);
	}

	.ms-sg-header {
		padding-bottom: var(--netz-space-stack-2xs, 4px);
		border-bottom: 1px solid var(--netz-border-subtle);
		margin-bottom: var(--netz-space-stack-2xs, 4px);
	}

	.ms-sg-label {
		width: 100px;
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
		flex-shrink: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.ms-sg-row .ms-sg-label {
		color: var(--netz-text-secondary);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.ms-sg-mgr {
		flex: 1;
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		color: var(--netz-text-muted);
		text-align: center;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.ms-sg-cell {
		flex: 1;
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.ms-sg-bar-track {
		flex: 1;
		height: 8px;
		background: var(--netz-surface-alt);
		border-radius: 4px;
		overflow: hidden;
	}

	.ms-sg-bar-fill {
		height: 100%;
		background: var(--netz-brand-primary);
		border-radius: 4px;
		transition: width 300ms ease;
	}

	.ms-sg-pct {
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

	.dt-fund-row, .dt-team-row, .dt-holder-row, .dt-holding-row {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: 4px 0;
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.dt-fund-name, .dt-team-name, .dt-holder-name, .dt-hold-name {
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--netz-text-primary);
	}

	.dt-fund-meta, .dt-team-role, .dt-holder-meta, .dt-hold-meta {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	/* Sector allocation bars in detail */
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

	/* ── Responsive ──────────────────────────────────────────────────────── */
	@media (max-width: 768px) {
		.ms-layout {
			grid-template-columns: 1fr;
			grid-template-rows: auto 1fr;
		}

		.ms-filters {
			border-right: none;
			border-bottom: 1px solid var(--netz-border-subtle);
			max-height: 200px;
		}
	}
</style>
