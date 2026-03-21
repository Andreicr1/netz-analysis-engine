<!--
  Manager Screener — discover, filter, and compare SEC-registered investment managers.
  URL-driven filters for shareable views. Detail drawer with 5 tabs.
-->
<script lang="ts">
  import {
    PageHeader,
    PageTabs,
    EmptyState,
    Button,
    Input,
    MetricCard,
    formatNumber,
    formatCurrency,
    formatPercent,
    formatAUM,
    formatDate,
  } from "@netz/ui";
  import { createClientApiClient } from "$lib/api/client";
  import { invalidateAll, goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { getContext } from "svelte";
  import type { PageData } from "./$types";

  // ── Types ────────────────────────────────────────────────────

  type ManagerRow = {
    crd_number: string;
    firm_name: string;
    aum_total: number | null;
    registration_status: string | null;
    state: string | null;
    country: string | null;
    compliance_disclosures: number | null;
    top_sectors: Record<string, number>;
    hhi: number | null;
    position_count: number | null;
    drift_churn: number | null;
    has_institutional_holders: boolean;
    universe_status: string | null;
  };

  type ScreenerPage = {
    managers: ManagerRow[];
    total_count: number;
    page: number;
    page_size: number;
    has_next: boolean;
  };

  type ManagerProfile = {
    crd_number: string;
    cik: string | null;
    firm_name: string;
    sec_number: string | null;
    registration_status: string | null;
    aum_total: number | null;
    aum_discretionary: number | null;
    aum_non_discretionary: number | null;
    total_accounts: number | null;
    fee_types: Record<string, boolean> | null;
    client_types: Record<string, boolean> | null;
    state: string | null;
    country: string | null;
    website: string | null;
    compliance_disclosures: number | null;
    last_adv_filed_at: string | null;
    funds: { fund_name: string; gross_asset_value: number | null; fund_type: string | null }[];
    team: { person_name: string; title: string | null; role: string | null }[];
  };

  type HoldingsData = {
    sector_allocation: Record<string, number>;
    top_holdings: {
      cusip: string;
      issuer_name: string;
      sector: string | null;
      market_value: number | null;
      weight: number | null;
    }[];
    hhi: number | null;
    history: { quarter: string; sectors: Record<string, number> }[];
  };

  type DriftData = {
    quarters: {
      quarter: string;
      turnover: number;
      new_positions: number;
      exited_positions: number;
      total_changes: number;
    }[];
    style_drift_detected: boolean;
  };

  type InstitutionalData = {
    coverage_type: string;
    holders: {
      filer_name: string;
      filer_type: string | null;
      filer_cik: string;
      market_value: number | null;
    }[];
  };

  type UniverseData = {
    instrument_id: string | null;
    approval_status: string | null;
    asset_class: string | null;
    geography: string | null;
    currency: string | null;
    block_id: string | null;
    added_at: string | null;
  };

  // ── Props & State ────────────────────────────────────────────

  const getToken = getContext<() => Promise<string>>("netz:getToken");
  let { data }: { data: PageData } = $props();

  let screener = $derived((data.screener ?? { managers: [], total_count: 0, page: 1, page_size: 25, has_next: false }) as ScreenerPage);

  // Filter state
  let textSearch = $state(data.currentParams?.text_search ?? "");
  let aumMin = $state(data.currentParams?.aum_min ?? "");
  let aumMax = $state(data.currentParams?.aum_max ?? "");
  let complianceClean = $state(data.currentParams?.compliance_clean === "true");

  // Detail drawer
  let selectedCrd = $state<string | null>(null);
  let detailTab = $state<"profile" | "holdings" | "drift" | "institutional" | "universe">("profile");
  let profileData = $state<ManagerProfile | null>(null);
  let holdingsData = $state<HoldingsData | null>(null);
  let driftData = $state<DriftData | null>(null);
  let institutionalData = $state<InstitutionalData | null>(null);
  let universeData = $state<UniverseData | null>(null);
  let detailLoading = $state(false);

  // Compare mode
  let compareMode = $state(false);
  let selectedForCompare = $state<Set<string>>(new Set());
  let compareResult = $state<any>(null);
  let comparing = $state(false);

  // Add to Universe dialog
  let showAddDialog = $state(false);
  let addAssetClass = $state("equity");
  let addGeography = $state("US");
  let addCurrency = $state("USD");
  let adding = $state(false);

  // ── Functions ────────────────────────────────────────────────

  function applyFilters() {
    const params = new URLSearchParams();
    if (textSearch) params.set("text_search", textSearch);
    if (aumMin) params.set("aum_min", aumMin);
    if (aumMax) params.set("aum_max", aumMax);
    if (complianceClean) params.set("compliance_clean", "true");
    params.set("page", "1");
    params.set("page_size", "25");
    goto(`/manager-screener?${params.toString()}`, { invalidateAll: true });
  }

  function clearFilters() {
    textSearch = "";
    aumMin = "";
    aumMax = "";
    complianceClean = false;
    goto("/manager-screener", { invalidateAll: true });
  }

  function goToPage(p: number) {
    const params = new URLSearchParams($page.url.searchParams);
    params.set("page", String(p));
    goto(`/manager-screener?${params.toString()}`, { invalidateAll: true });
  }

  async function openDetail(crd: string) {
    selectedCrd = crd;
    detailTab = "profile";
    profileData = null;
    holdingsData = null;
    driftData = null;
    institutionalData = null;
    universeData = null;
    await loadDetailTab("profile");
  }

  function closeDetail() {
    selectedCrd = null;
  }

  async function loadDetailTab(tab: typeof detailTab) {
    if (!selectedCrd) return;
    detailTab = tab;
    detailLoading = true;

    try {
      const api = createClientApiClient(getToken);
      switch (tab) {
        case "profile":
          profileData = await api.get(`/manager-screener/managers/${selectedCrd}/profile`);
          break;
        case "holdings":
          holdingsData = await api.get(`/manager-screener/managers/${selectedCrd}/holdings`);
          break;
        case "drift":
          driftData = await api.get(`/manager-screener/managers/${selectedCrd}/drift`);
          break;
        case "institutional":
          institutionalData = await api.get(`/manager-screener/managers/${selectedCrd}/institutional`);
          break;
        case "universe":
          universeData = await api.get(`/manager-screener/managers/${selectedCrd}/universe-status`);
          break;
      }
    } catch (err) {
      console.error(`Failed to load ${tab} for ${selectedCrd}`, err);
    } finally {
      detailLoading = false;
    }
  }

  function toggleCompare(crd: string) {
    const next = new Set(selectedForCompare);
    if (next.has(crd)) {
      next.delete(crd);
    } else if (next.size < 5) {
      next.add(crd);
    }
    selectedForCompare = next;
  }

  async function runCompare() {
    if (selectedForCompare.size < 2) return;
    comparing = true;
    try {
      const api = createClientApiClient(getToken);
      compareResult = await api.post("/manager-screener/managers/compare", {
        crd_numbers: Array.from(selectedForCompare),
      });
    } catch (err) {
      console.error("Compare failed", err);
    } finally {
      comparing = false;
    }
  }

  async function addToUniverse() {
    if (!selectedCrd) return;
    adding = true;
    try {
      const api = createClientApiClient(getToken);
      await api.post(`/manager-screener/managers/${selectedCrd}/add-to-universe`, {
        asset_class: addAssetClass,
        geography: addGeography,
        currency: addCurrency,
      });
      showAddDialog = false;
      // Reload universe tab
      await loadDetailTab("universe");
    } catch (err) {
      console.error("Add to universe failed", err);
    } finally {
      adding = false;
    }
  }

  // Detail tabs config
  const detailTabs = [
    { value: "profile" as const, label: "Profile" },
    { value: "holdings" as const, label: "Holdings" },
    { value: "drift" as const, label: "Drift" },
    { value: "institutional" as const, label: "Institutional" },
    { value: "universe" as const, label: "Universe" },
  ];
</script>

<PageHeader title="Manager Screener">
  <svelte:fragment slot="actions">
    <Button
      variant={compareMode ? "default" : "outline"}
      size="sm"
      onclick={() => {
        compareMode = !compareMode;
        if (!compareMode) {
          selectedForCompare = new Set();
          compareResult = null;
        }
      }}
    >
      {compareMode ? "Exit Compare" : "Compare Mode"}
    </Button>
    {#if compareMode && selectedForCompare.size >= 2}
      <Button size="sm" onclick={runCompare} disabled={comparing}>
        {comparing ? "Comparing..." : `Compare (${selectedForCompare.size})`}
      </Button>
    {/if}
  </svelte:fragment>
</PageHeader>

<div class="flex gap-6 mt-4">
  <!-- ── Filter Sidebar ──────────────────────────────────────── -->
  <aside class="w-72 shrink-0 space-y-4">
    <div class="rounded-lg border border-border bg-card p-4 space-y-3">
      <h3 class="text-sm font-medium text-muted-foreground">Filters</h3>

      <!-- Text search -->
      <div>
        <label class="text-xs text-muted-foreground" for="text-search">Firm Name</label>
        <Input
          id="text-search"
          placeholder="Search firms..."
          bind:value={textSearch}
          onkeydown={(e: KeyboardEvent) => e.key === "Enter" && applyFilters()}
        />
      </div>

      <!-- AUM range -->
      <div class="grid grid-cols-2 gap-2">
        <div>
          <label class="text-xs text-muted-foreground" for="aum-min">AUM Min</label>
          <Input id="aum-min" type="number" placeholder="Min" bind:value={aumMin} />
        </div>
        <div>
          <label class="text-xs text-muted-foreground" for="aum-max">AUM Max</label>
          <Input id="aum-max" type="number" placeholder="Max" bind:value={aumMax} />
        </div>
      </div>

      <!-- Compliance clean -->
      <label class="flex items-center gap-2 text-sm">
        <input type="checkbox" bind:checked={complianceClean} class="rounded" />
        Clean compliance record
      </label>

      <div class="flex gap-2">
        <Button size="sm" onclick={applyFilters}>Apply</Button>
        <Button size="sm" variant="outline" onclick={clearFilters}>Clear</Button>
      </div>
    </div>
  </aside>

  <!-- ── Main Content ────────────────────────────────────────── -->
  <div class="flex-1 min-w-0">
    <!-- Results summary -->
    <div class="flex items-center justify-between mb-4">
      <p class="text-sm text-muted-foreground">
        {formatNumber(screener.total_count, 0)} managers found
      </p>
      <p class="text-sm text-muted-foreground">
        Page {screener.page} of {Math.max(1, Math.ceil(screener.total_count / screener.page_size))}
      </p>
    </div>

    <!-- Results table -->
    <div class="rounded-lg border border-border overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-muted/50">
          <tr>
            {#if compareMode}
              <th class="px-3 py-2 text-left w-10"></th>
            {/if}
            <th class="px-3 py-2 text-left">Firm</th>
            <th class="px-3 py-2 text-right">AUM</th>
            <th class="px-3 py-2 text-left">State</th>
            <th class="px-3 py-2 text-right">Positions</th>
            <th class="px-3 py-2 text-right">Disclosures</th>
            <th class="px-3 py-2 text-left">Status</th>
            <th class="px-3 py-2 text-left">Universe</th>
          </tr>
        </thead>
        <tbody>
          {#each screener.managers as mgr (mgr.crd_number)}
            <tr
              class="border-t border-border hover:bg-muted/30 cursor-pointer transition-colors"
              onclick={() => openDetail(mgr.crd_number)}
            >
              {#if compareMode}
                <td class="px-3 py-2">
                  <input
                    type="checkbox"
                    checked={selectedForCompare.has(mgr.crd_number)}
                    onclick={(e: MouseEvent) => {
                      e.stopPropagation();
                      toggleCompare(mgr.crd_number);
                    }}
                    disabled={!selectedForCompare.has(mgr.crd_number) && selectedForCompare.size >= 5}
                    class="rounded"
                  />
                </td>
              {/if}
              <td class="px-3 py-2 font-medium">{mgr.firm_name}</td>
              <td class="px-3 py-2 text-right tabular-nums">
                {mgr.aum_total ? formatAUM(mgr.aum_total, "USD", "en-US") : "—"}
              </td>
              <td class="px-3 py-2">{mgr.state ?? "—"}</td>
              <td class="px-3 py-2 text-right tabular-nums">
                {mgr.position_count != null ? formatNumber(mgr.position_count, 0) : "—"}
              </td>
              <td class="px-3 py-2 text-right tabular-nums">
                {mgr.compliance_disclosures ?? 0}
              </td>
              <td class="px-3 py-2">
                <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
                  class:bg-green-500/10={mgr.registration_status === "APPROVED"}
                  class:text-green-400={mgr.registration_status === "APPROVED"}
                  class:bg-yellow-500/10={mgr.registration_status !== "APPROVED"}
                  class:text-yellow-400={mgr.registration_status !== "APPROVED"}
                >
                  {mgr.registration_status ?? "—"}
                </span>
              </td>
              <td class="px-3 py-2">
                {#if mgr.universe_status}
                  <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-blue-500/10 text-blue-400">
                    {mgr.universe_status}
                  </span>
                {:else}
                  <span class="text-muted-foreground">—</span>
                {/if}
              </td>
            </tr>
          {:else}
            <tr>
              <td colspan={compareMode ? 8 : 7} class="px-3 py-12 text-center">
                <EmptyState
                  title="No managers found"
                  description="Try adjusting your filters or search criteria."
                />
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    {#if screener.total_count > screener.page_size}
      <div class="flex items-center justify-center gap-2 mt-4">
        <Button
          size="sm"
          variant="outline"
          disabled={screener.page <= 1}
          onclick={() => goToPage(screener.page - 1)}
        >
          Previous
        </Button>
        <span class="text-sm text-muted-foreground tabular-nums">
          {screener.page} / {Math.ceil(screener.total_count / screener.page_size)}
        </span>
        <Button
          size="sm"
          variant="outline"
          disabled={!screener.has_next}
          onclick={() => goToPage(screener.page + 1)}
        >
          Next
        </Button>
      </div>
    {/if}
  </div>
</div>

<!-- ── Compare Result Modal ──────────────────────────────────── -->
{#if compareResult}
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" role="dialog">
    <div class="bg-card border border-border rounded-lg max-w-4xl w-full max-h-[80vh] overflow-y-auto p-6 m-4">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-semibold">Manager Comparison</h2>
        <Button size="sm" variant="outline" onclick={() => (compareResult = null)}>Close</Button>
      </div>

      <!-- Side-by-side comparison -->
      <div class="grid gap-4" style="grid-template-columns: repeat({compareResult.managers.length}, 1fr);">
        {#each compareResult.managers as mgr}
          <div class="rounded-lg border border-border p-4 space-y-2">
            <h3 class="font-medium text-sm">{mgr.firm_name}</h3>
            <p class="text-xs text-muted-foreground">CRD: {mgr.crd_number}</p>
            <p class="text-sm">AUM: {mgr.aum_total ? formatAUM(mgr.aum_total, "USD", "en-US") : "—"}</p>
            <p class="text-sm">State: {mgr.state ?? "—"}</p>
            <p class="text-sm">Accounts: {mgr.total_accounts ? formatNumber(mgr.total_accounts, 0) : "—"}</p>
            <p class="text-sm">Disclosures: {mgr.compliance_disclosures ?? 0}</p>

            <!-- Sector allocation -->
            {#if compareResult.sector_allocations[mgr.crd_number]}
              <div class="mt-2">
                <p class="text-xs font-medium text-muted-foreground mb-1">Top Sectors</p>
                {#each Object.entries(compareResult.sector_allocations[mgr.crd_number]).slice(0, 5) as [sector, weight]}
                  <div class="flex justify-between text-xs">
                    <span class="truncate">{sector}</span>
                    <span class="tabular-nums">{formatPercent(weight as number)}</span>
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        {/each}
      </div>

      {#if compareResult.jaccard_overlap != null}
        <div class="mt-4 p-3 rounded-lg bg-muted/50">
          <p class="text-sm">
            <span class="font-medium">Portfolio Overlap (Jaccard):</span>
            <span class="tabular-nums ml-1">{formatPercent(compareResult.jaccard_overlap)}</span>
          </p>
        </div>
      {/if}
    </div>
  </div>
{/if}

<!-- ── Detail Drawer ─────────────────────────────────────────── -->
{#if selectedCrd}
  <div class="fixed inset-y-0 right-0 z-40 w-[600px] max-w-full bg-card border-l border-border shadow-2xl overflow-y-auto">
    <div class="p-4 border-b border-border flex items-center justify-between">
      <h2 class="font-semibold">Manager Detail</h2>
      <Button size="sm" variant="outline" onclick={closeDetail}>Close</Button>
    </div>

    <!-- Tab navigation -->
    <div class="flex border-b border-border">
      {#each detailTabs as tab}
        <button
          class="px-4 py-2 text-sm border-b-2 transition-colors"
          class:border-primary={detailTab === tab.value}
          class:text-foreground={detailTab === tab.value}
          class:border-transparent={detailTab !== tab.value}
          class:text-muted-foreground={detailTab !== tab.value}
          onclick={() => loadDetailTab(tab.value)}
        >
          {tab.label}
        </button>
      {/each}
    </div>

    <div class="p-4">
      {#if detailLoading}
        <div class="flex items-center justify-center py-12">
          <span class="text-sm text-muted-foreground">Loading...</span>
        </div>
      {:else if detailTab === "profile" && profileData}
        <!-- Profile tab -->
        <div class="space-y-4">
          <div>
            <h3 class="text-lg font-semibold">{profileData.firm_name}</h3>
            <p class="text-sm text-muted-foreground">CRD: {profileData.crd_number} | CIK: {profileData.cik ?? "—"}</p>
          </div>

          <div class="grid grid-cols-2 gap-3">
            <MetricCard label="Total AUM" value={profileData.aum_total ? formatAUM(profileData.aum_total, "USD", "en-US") : "—"} />
            <MetricCard label="Discretionary" value={profileData.aum_discretionary ? formatAUM(profileData.aum_discretionary, "USD", "en-US") : "—"} />
            <MetricCard label="Accounts" value={profileData.total_accounts ? formatNumber(profileData.total_accounts, 0) : "—"} />
            <MetricCard label="Disclosures" value={String(profileData.compliance_disclosures ?? 0)} />
          </div>

          <div class="text-sm space-y-1">
            <p><span class="text-muted-foreground">Status:</span> {profileData.registration_status ?? "—"}</p>
            <p><span class="text-muted-foreground">Location:</span> {profileData.state ?? "—"}, {profileData.country ?? "—"}</p>
            {#if profileData.website}
              <p><span class="text-muted-foreground">Website:</span> {profileData.website}</p>
            {/if}
            {#if profileData.last_adv_filed_at}
              <p><span class="text-muted-foreground">Last ADV:</span> {formatDate(profileData.last_adv_filed_at)}</p>
            {/if}
          </div>

          <!-- Funds -->
          {#if profileData.funds.length > 0}
            <div>
              <h4 class="text-sm font-medium mb-2">Funds ({profileData.funds.length})</h4>
              <div class="space-y-1">
                {#each profileData.funds as fund}
                  <div class="flex justify-between text-sm border-b border-border/50 py-1">
                    <span class="truncate">{fund.fund_name}</span>
                    <span class="tabular-nums text-muted-foreground">
                      {fund.gross_asset_value ? formatAUM(fund.gross_asset_value, "USD", "en-US") : "—"}
                    </span>
                  </div>
                {/each}
              </div>
            </div>
          {/if}

          <!-- Team -->
          {#if profileData.team.length > 0}
            <div>
              <h4 class="text-sm font-medium mb-2">Team ({profileData.team.length})</h4>
              <div class="space-y-1">
                {#each profileData.team as member}
                  <div class="text-sm border-b border-border/50 py-1">
                    <span class="font-medium">{member.person_name}</span>
                    {#if member.title}
                      <span class="text-muted-foreground"> — {member.title}</span>
                    {/if}
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        </div>

      {:else if detailTab === "holdings" && holdingsData}
        <!-- Holdings tab -->
        <div class="space-y-4">
          {#if holdingsData.hhi != null}
            <MetricCard label="HHI (Concentration)" value={formatNumber(holdingsData.hhi, 4)} />
          {/if}

          <!-- Sector allocation -->
          {#if Object.keys(holdingsData.sector_allocation).length > 0}
            <div>
              <h4 class="text-sm font-medium mb-2">Sector Allocation</h4>
              {#each Object.entries(holdingsData.sector_allocation) as [sector, weight]}
                <div class="flex items-center justify-between text-sm py-1">
                  <span class="truncate">{sector}</span>
                  <div class="flex items-center gap-2">
                    <div class="w-24 h-2 bg-muted rounded-full overflow-hidden">
                      <div class="h-full bg-primary rounded-full" style="width: {Math.min(weight * 100, 100)}%"></div>
                    </div>
                    <span class="tabular-nums w-16 text-right">{formatPercent(weight)}</span>
                  </div>
                </div>
              {/each}
            </div>
          {/if}

          <!-- Top 10 -->
          {#if holdingsData.top_holdings.length > 0}
            <div>
              <h4 class="text-sm font-medium mb-2">Top 10 Holdings</h4>
              <table class="w-full text-sm">
                <thead>
                  <tr class="text-xs text-muted-foreground">
                    <th class="text-left pb-1">Issuer</th>
                    <th class="text-right pb-1">Value</th>
                    <th class="text-right pb-1">Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {#each holdingsData.top_holdings as h}
                    <tr class="border-t border-border/50">
                      <td class="py-1 truncate max-w-[200px]">{h.issuer_name}</td>
                      <td class="py-1 text-right tabular-nums">
                        {h.market_value ? formatCurrency(h.market_value, "USD", "en-US") : "—"}
                      </td>
                      <td class="py-1 text-right tabular-nums">
                        {h.weight != null ? formatPercent(h.weight) : "—"}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </div>

      {:else if detailTab === "drift" && driftData}
        <!-- Drift tab -->
        <div class="space-y-4">
          {#if driftData.style_drift_detected}
            <div class="rounded-lg bg-yellow-500/10 border border-yellow-500/20 p-3">
              <p class="text-sm text-yellow-400 font-medium">Style drift detected — turnover exceeded 30% threshold</p>
            </div>
          {/if}

          {#if driftData.quarters.length > 0}
            <table class="w-full text-sm">
              <thead>
                <tr class="text-xs text-muted-foreground">
                  <th class="text-left pb-1">Quarter</th>
                  <th class="text-right pb-1">Turnover</th>
                  <th class="text-right pb-1">New</th>
                  <th class="text-right pb-1">Exited</th>
                  <th class="text-right pb-1">Changes</th>
                </tr>
              </thead>
              <tbody>
                {#each driftData.quarters as q}
                  <tr class="border-t border-border/50">
                    <td class="py-1">{q.quarter}</td>
                    <td class="py-1 text-right tabular-nums"
                      class:text-yellow-400={q.turnover > 0.3}
                    >
                      {formatPercent(q.turnover)}
                    </td>
                    <td class="py-1 text-right tabular-nums">{q.new_positions}</td>
                    <td class="py-1 text-right tabular-nums">{q.exited_positions}</td>
                    <td class="py-1 text-right tabular-nums">{q.total_changes}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {:else}
            <EmptyState title="No drift data" description="No quarterly changes found for this manager." />
          {/if}
        </div>

      {:else if detailTab === "institutional" && institutionalData}
        <!-- Institutional tab -->
        <div class="space-y-4">
          <div class="flex items-center gap-2">
            <span class="text-sm text-muted-foreground">Coverage:</span>
            <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
              class:bg-green-500/10={institutionalData.coverage_type === "full"}
              class:text-green-400={institutionalData.coverage_type === "full"}
              class:bg-yellow-500/10={institutionalData.coverage_type === "partial"}
              class:text-yellow-400={institutionalData.coverage_type === "partial"}
              class:bg-muted={institutionalData.coverage_type === "none"}
              class:text-muted-foreground={institutionalData.coverage_type === "none"}
            >
              {institutionalData.coverage_type}
            </span>
          </div>

          {#if institutionalData.holders.length > 0}
            <table class="w-full text-sm">
              <thead>
                <tr class="text-xs text-muted-foreground">
                  <th class="text-left pb-1">Institution</th>
                  <th class="text-left pb-1">Type</th>
                  <th class="text-right pb-1">Value</th>
                </tr>
              </thead>
              <tbody>
                {#each institutionalData.holders as holder}
                  <tr class="border-t border-border/50">
                    <td class="py-1 truncate max-w-[200px]">{holder.filer_name}</td>
                    <td class="py-1">{holder.filer_type ?? "—"}</td>
                    <td class="py-1 text-right tabular-nums">
                      {holder.market_value ? formatCurrency(holder.market_value, "USD", "en-US") : "—"}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {:else}
            <EmptyState title="No institutional holders" description="No 13F institutional holders found." />
          {/if}
        </div>

      {:else if detailTab === "universe" && universeData}
        <!-- Universe tab -->
        <div class="space-y-4">
          {#if universeData.instrument_id}
            <div class="rounded-lg border border-border p-4 space-y-2">
              <p class="text-sm"><span class="text-muted-foreground">Status:</span> {universeData.approval_status}</p>
              <p class="text-sm"><span class="text-muted-foreground">Asset Class:</span> {universeData.asset_class}</p>
              <p class="text-sm"><span class="text-muted-foreground">Geography:</span> {universeData.geography}</p>
              <p class="text-sm"><span class="text-muted-foreground">Currency:</span> {universeData.currency}</p>
              {#if universeData.added_at}
                <p class="text-sm"><span class="text-muted-foreground">Added:</span> {formatDate(universeData.added_at)}</p>
              {/if}
            </div>
          {:else}
            <EmptyState title="Not in universe" description="This manager has not been added to your instrument universe." />
            <Button onclick={() => (showAddDialog = true)}>Add to Universe</Button>
          {/if}
        </div>

      {:else if !detailLoading}
        <EmptyState title="No data" description="Select a tab to view details." />
      {/if}
    </div>
  </div>

  <!-- Backdrop -->
  <button
    class="fixed inset-0 z-30 bg-black/30"
    onclick={closeDetail}
    aria-label="Close detail"
  ></button>
{/if}

<!-- ── Add to Universe Dialog ────────────────────────────────── -->
{#if showAddDialog}
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" role="dialog">
    <div class="bg-card border border-border rounded-lg w-96 p-6 space-y-4">
      <h3 class="text-lg font-semibold">Add to Universe</h3>

      <div>
        <label class="text-sm text-muted-foreground" for="add-asset-class">Asset Class</label>
        <Input id="add-asset-class" bind:value={addAssetClass} />
      </div>
      <div>
        <label class="text-sm text-muted-foreground" for="add-geography">Geography</label>
        <Input id="add-geography" bind:value={addGeography} />
      </div>
      <div>
        <label class="text-sm text-muted-foreground" for="add-currency">Currency</label>
        <Input id="add-currency" bind:value={addCurrency} />
      </div>

      <div class="flex justify-end gap-2">
        <Button variant="outline" size="sm" onclick={() => (showAddDialog = false)}>Cancel</Button>
        <Button size="sm" onclick={addToUniverse} disabled={adding}>
          {adding ? "Adding..." : "Add"}
        </Button>
      </div>
    </div>
  </div>
{/if}
