<!--
  Screener filter card — 4 tabs (Funds, Equities, Fixed Income, ETF)
  with tab-specific inline filters. Stacked layout, no sidebar.
-->
<script lang="ts">
  import "./screener.css";
  import { goto } from "$app/navigation";
  import { Button } from "@netz/ui";
  import type { ScreenerTab, ScreenerFacets } from "$lib/types/screening";
  import { EMPTY_FACETS } from "$lib/types/screening";

  interface Props {
    activeTab: ScreenerTab;
    facets: ScreenerFacets;
    initParams: Record<string, string>;
  }

  let { activeTab = "fund", facets = EMPTY_FACETS, initParams = {} }: Props = $props();

  // ── Shared state ──
  let searchQ = $state(initParams.q ?? "");
  let searchFundType = $state<string | null>(initParams.fund_type ?? null);
  let searchAssetClass = $state<string | null>(initParams.asset_class ?? null);
  let searchGeography = $state<string | null>(initParams.geography ?? null);
  let searchManager = $state(initParams.manager ?? "");
  let searchStrategy = $state<string | null>(initParams.strategy ?? null);
  let aumMin = $state(initParams.aum_min ?? "");

  // ── Equity filters ──
  let eqSector = $state(initParams.sector ?? "");
  let eqExchange = $state(initParams.exchange ?? "");
  let eqMarketCapMin = $state(initParams.market_cap_min ?? "");
  let eqPeMax = $state(initParams.pe_max ?? "");
  let eqDivYieldMin = $state(initParams.div_yield_min ?? "");

  // ── ETF filters ──
  let etfFundFamily = $state(initParams.fund_family ?? "");
  let etfExpenseRatioMax = $state(initParams.expense_ratio_max ?? "");

  // ── Fixed Income filters ──
  let bondAssetClass = $state(initParams.bond_asset_class ?? "");
  let bondMaturityRange = $state(initParams.maturity_range ?? "");
  let bondYtmMin = $state(initParams.ytm_min ?? "");

  const TAB_CONFIG: { key: ScreenerTab; label: string }[] = [
    { key: "fund", label: "Funds" },
    { key: "equity", label: "Equities" },
    { key: "bond", label: "Fixed Income" },
    { key: "etf", label: "ETF" },
  ];

  // ── Debounce ──
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  function debouncedApply() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => applyFilters(), 300);
  }

  function selectTab(tab: ScreenerTab) {
    // Reset tab-specific filters when switching
    searchQ = "";
    searchFundType = null;
    searchAssetClass = null;
    searchGeography = null;
    searchManager = "";
    searchStrategy = null;
    aumMin = "";
    eqSector = "";
    eqExchange = "";
    eqMarketCapMin = "";
    eqPeMax = "";
    eqDivYieldMin = "";
    etfFundFamily = "";
    etfExpenseRatioMax = "";
    bondAssetClass = "";
    bondMaturityRange = "";
    bondYtmMin = "";
    goto(`/screener?tab=${tab}`, { invalidateAll: true });
  }

  function applyFilters() {
    const params = new URLSearchParams();
    params.set("tab", activeTab);
    if (searchQ) params.set("q", searchQ);
    if (searchFundType) params.set("fund_type", searchFundType);
    if (searchAssetClass) params.set("asset_class", searchAssetClass);
    if (searchGeography) params.set("geography", searchGeography);
    if (searchManager) params.set("manager", searchManager);
    if (searchStrategy) params.set("strategy", searchStrategy);

    if (activeTab === "fund") {
      if (aumMin) params.set("aum_min", aumMin);
    } else if (activeTab === "equity") {
      if (eqSector) params.set("sector", eqSector);
      if (eqExchange) params.set("exchange", eqExchange);
      if (eqMarketCapMin) params.set("market_cap_min", eqMarketCapMin);
      if (eqPeMax) params.set("pe_max", eqPeMax);
      if (eqDivYieldMin) params.set("div_yield_min", eqDivYieldMin);
    } else if (activeTab === "bond") {
      if (bondAssetClass) params.set("bond_asset_class", bondAssetClass);
      if (bondMaturityRange) params.set("maturity_range", bondMaturityRange);
      if (bondYtmMin) params.set("ytm_min", bondYtmMin);
    } else if (activeTab === "etf") {
      if (etfFundFamily) params.set("fund_family", etfFundFamily);
      if (etfExpenseRatioMax) params.set("expense_ratio_max", etfExpenseRatioMax);
    }

    params.set("page", "1");
    params.set("page_size", "50");
    goto(`/screener?${params.toString()}`, { invalidateAll: true });
  }

  function clearFilters() {
    searchQ = "";
    searchFundType = null;
    searchAssetClass = null;
    searchGeography = null;
    searchManager = "";
    searchStrategy = null;
    aumMin = "";
    eqSector = "";
    eqExchange = "";
    eqMarketCapMin = "";
    eqPeMax = "";
    eqDivYieldMin = "";
    etfFundFamily = "";
    etfExpenseRatioMax = "";
    bondAssetClass = "";
    bondMaturityRange = "";
    bondYtmMin = "";
    goto(`/screener?tab=${activeTab}`, { invalidateAll: true });
  }

  function handleSearchKeydown(e: KeyboardEvent) {
    if (e.key === "Enter") applyFilters();
  }
</script>

<div class="filter-card">
  <!-- Tabs -->
  <div class="filter-tabs">
    {#each TAB_CONFIG as { key, label } (key)}
      <button
        class="filter-tab"
        class:filter-tab--active={activeTab === key}
        onclick={() => selectTab(key)}
      >
        {label}
      </button>
    {/each}
  </div>

  <!-- Search -->
  <div class="filter-body">
    <div class="filter-search">
      <input
        class="scr-input filter-search-input"
        type="text"
        placeholder="Search by name, ISIN, ticker, manager…"
        bind:value={searchQ}
        onkeydown={handleSearchKeydown}
      />
    </div>

    <!-- Tab-specific filters -->
    <div class="filter-row">
      {#if activeTab === "fund"}
        <div class="filter-field">
          <label class="scr-label" for="f-fund-type">Fund Type</label>
          <select id="f-fund-type" class="scr-select" bind:value={searchFundType} onchange={debouncedApply}>
            <option value="">All</option>
            <option value="ucits">UCITS</option>
            <option value="mutual_fund">Mutual Funds</option>
            <option value="alternatives">Alternatives</option>
          </select>
        </div>
        <div class="filter-field">
          <label class="scr-label" for="f-aum-min">AUM min (USD)</label>
          <input id="f-aum-min" class="scr-input" type="number" placeholder="e.g. 1000000000" bind:value={aumMin} oninput={debouncedApply} />
        </div>
        <div class="filter-field">
          <label class="scr-label" for="f-geography">Geography</label>
          <select id="f-geography" class="scr-select" bind:value={searchGeography} onchange={debouncedApply}>
            <option value="">All</option>
            {#each facets.geographies as geo (geo.value)}
              <option value={geo.value}>{geo.label} ({geo.count})</option>
            {/each}
          </select>
        </div>
        <div class="filter-field">
          <label class="scr-label" for="f-manager">Investment Manager</label>
          <input id="f-manager" class="scr-input" type="text" placeholder="Vanguard, BlackRock…" bind:value={searchManager} oninput={debouncedApply} />
        </div>
        <div class="filter-field">
          <label class="scr-label" for="f-strategy">Strategy</label>
          <select id="f-strategy" class="scr-select" bind:value={searchStrategy} onchange={debouncedApply}>
            <option value="">All</option>
            {#each facets.strategies as s (s.value)}
              <option value={s.value}>{s.label} ({s.count})</option>
            {/each}
          </select>
        </div>
      {:else if activeTab === "equity"}
        <div class="filter-field">
          <label class="scr-label" for="f-sector">Sector</label>
          <select id="f-sector" class="scr-select" bind:value={eqSector} onchange={debouncedApply}>
            <option value="">All</option>
            {#each facets.sectors as s (s.value)}
              <option value={s.value}>{s.label} ({s.count})</option>
            {/each}
          </select>
        </div>
        <div class="filter-field">
          <label class="scr-label" for="f-exchange">Exchange</label>
          <select id="f-exchange" class="scr-select" bind:value={eqExchange} onchange={debouncedApply}>
            <option value="">All</option>
            {#each facets.exchanges as ex (ex.value)}
              <option value={ex.value}>{ex.label} ({ex.count})</option>
            {/each}
          </select>
        </div>
        <div class="filter-field">
          <label class="scr-label" for="f-mcap">Market Cap min</label>
          <select id="f-mcap" class="scr-select" bind:value={eqMarketCapMin} onchange={debouncedApply}>
            <option value="">Any</option>
            <option value="300000000">Small ($300M+)</option>
            <option value="2000000000">Mid ($2B+)</option>
            <option value="10000000000">Large ($10B+)</option>
            <option value="200000000000">Mega ($200B+)</option>
          </select>
        </div>
        <div class="filter-field">
          <label class="scr-label" for="f-pe">P/E max</label>
          <input id="f-pe" class="scr-input" type="number" placeholder="e.g. 25" bind:value={eqPeMax} oninput={debouncedApply} />
        </div>
        <div class="filter-field">
          <label class="scr-label" for="f-div">Dividend Yield min %</label>
          <input id="f-div" class="scr-input" type="number" step="0.01" placeholder="e.g. 0.02" bind:value={eqDivYieldMin} oninput={debouncedApply} />
        </div>
      {:else if activeTab === "bond"}
        <div class="filter-field">
          <label class="scr-label" for="f-bond-ac">Asset Class</label>
          <select id="f-bond-ac" class="scr-select" bind:value={bondAssetClass} onchange={debouncedApply}>
            <option value="">All</option>
            <option value="ig">Investment Grade</option>
            <option value="hy">High Yield</option>
            <option value="govt">Government</option>
            <option value="muni">Municipal</option>
          </select>
        </div>
        <div class="filter-field">
          <label class="scr-label" for="f-maturity">Maturity Range</label>
          <select id="f-maturity" class="scr-select" bind:value={bondMaturityRange} onchange={debouncedApply}>
            <option value="">All</option>
            <option value="0-2">0-2 Years</option>
            <option value="2-5">2-5 Years</option>
            <option value="5-10">5-10 Years</option>
            <option value="10+">10+ Years</option>
          </select>
        </div>
        <div class="filter-field">
          <label class="scr-label" for="f-ytm">YTM min %</label>
          <input id="f-ytm" class="scr-input" type="number" step="0.01" placeholder="e.g. 0.04" bind:value={bondYtmMin} oninput={debouncedApply} />
        </div>
      {:else if activeTab === "etf"}
        <div class="filter-field">
          <label class="scr-label" for="f-etf-ac">Asset Class</label>
          <select id="f-etf-ac" class="scr-select" bind:value={searchAssetClass} onchange={debouncedApply}>
            <option value="">All</option>
            {#each facets.asset_classes as ac (ac.value)}
              <option value={ac.value}>{ac.label} ({ac.count})</option>
            {/each}
          </select>
        </div>
        <div class="filter-field">
          <label class="scr-label" for="f-family">Issuer / Fund Family</label>
          <input id="f-family" class="scr-input" type="text" placeholder="Vanguard, iShares…" bind:value={etfFundFamily} oninput={debouncedApply} />
        </div>
        <div class="filter-field">
          <label class="scr-label" for="f-er">Expense Ratio max %</label>
          <input id="f-er" class="scr-input" type="number" step="0.001" placeholder="e.g. 0.005" bind:value={etfExpenseRatioMax} oninput={debouncedApply} />
        </div>
      {/if}
    </div>

    <!-- Actions -->
    <div class="filter-actions">
      <Button size="sm" variant="ghost" onclick={clearFilters}>Clear</Button>
      <Button size="sm" onclick={applyFilters}>Apply Filters</Button>
    </div>
  </div>
</div>

<style>
  .filter-card {
    border: 1px solid var(--netz-border-subtle);
    border-radius: 16px;
    background: var(--netz-surface-elevated);
    box-shadow: var(--netz-shadow-sm, 0 1px 3px rgba(0,0,0,0.06));
    overflow: hidden;
  }

  .filter-tabs {
    display: flex;
    border-bottom: 1px solid var(--netz-border-subtle);
  }

  .filter-tab {
    flex: 1;
    padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-md, 16px);
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

  .filter-tab:hover {
    color: var(--netz-text-primary);
    background: var(--netz-surface-alt);
  }

  .filter-tab--active {
    color: var(--netz-brand-primary);
    border-bottom-color: var(--netz-brand-primary);
    font-weight: 600;
  }

  .filter-body {
    padding: var(--netz-space-stack-sm, 14px) var(--netz-space-inline-md, 16px);
    display: flex;
    flex-direction: column;
    gap: var(--netz-space-stack-sm, 12px);
  }

  .filter-search-input {
    width: 100%;
  }

  .filter-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--netz-space-inline-sm, 12px);
  }

  .filter-field {
    flex: 1;
    min-width: 160px;
    max-width: 240px;
  }

  .filter-actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--netz-space-inline-xs, 8px);
  }

  @media (max-width: 768px) {
    .filter-row {
      flex-direction: column;
    }

    .filter-field {
      max-width: none;
    }
  }
</style>
