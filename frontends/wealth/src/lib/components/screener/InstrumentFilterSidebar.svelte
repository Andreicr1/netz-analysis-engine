<!--
  Instrument search filter sidebar — search, chips, dynamic dimension filters, facet summary.
  Cascade: Asset Class → Strategy (re-fetch facets on Asset Class change).
  Batch: 300ms debounce on filter changes before navigating.
-->
<script lang="ts">
  import "./screener.css";
  import { slide } from "svelte/transition";
  import { goto } from "$app/navigation";
  import { Button } from "@investintell/ui/components/ui/button";
  import { formatNumber } from "@investintell/ui";
  import type { ScreenerFacets, FacetItem } from "$lib/types/screening";
  import { EMPTY_FACETS } from "$lib/types/screening";

  type ChipKey =
    | "all"
    | "us_funds"
    | "ucits"
    | "etfs"
    | "bonds"
    | "equities"
    | "hedge_funds";
  type FacetKey =
    | "geographies"
    | "domiciles"
    | "currencies"
    | "strategies"
    | "asset_classes";

  interface Props {
    facets: ScreenerFacets;
    initParams: Record<string, string>;
  }

  let { facets = EMPTY_FACETS, initParams = {} }: Props = $props();

  let searchQ = $state(initParams.q ?? "");
  let searchSource = $state<string | null>(initParams.source ?? null);
  let searchInstrumentType = $state<string | null>(
    initParams.instrument_type ?? null,
  );
  let searchGeography = $state<string | null>(initParams.geography ?? null);
  let searchDomicile = $state<string | null>(initParams.domicile ?? null);
  let searchCurrency = $state<string | null>(initParams.currency ?? null);
  let searchAssetClass = $state<string | null>(initParams.asset_class ?? null);
  let searchStrategy = $state<string | null>(initParams.strategy ?? null);
  let searchAumMin = $state(initParams.aum_min ?? "");

  let activeChip = $state<ChipKey>("all");

  const CHIP_FILTERS: Record<
    ChipKey,
    { source?: string; instrument_type?: string }
  > = {
    all: {},
    us_funds: { source: "internal", instrument_type: "fund" },
    ucits: { source: "esma", instrument_type: "fund" },
    etfs: { instrument_type: "etf" },
    bonds: { instrument_type: "bond" },
    equities: { instrument_type: "equity" },
    hedge_funds: { instrument_type: "hedge_fund" },
  };

  const CHIP_LABELS: Record<ChipKey, string> = {
    all: "All",
    us_funds: "Mutual Funds",
    ucits: "UCITS",
    etfs: "ETFs",
    bonds: "Bonds",
    equities: "Equities",
    hedge_funds: "Hedge Funds",
  };

  // ── Dynamic facets per asset type (WM-S2-04) ──
  const CHIP_FACETS: Record<ChipKey, FacetKey[]> = {
    all: ["geographies", "domiciles", "currencies"],
    us_funds: ["geographies", "currencies", "strategies"],
    ucits: ["domiciles", "currencies"],
    etfs: ["geographies", "currencies", "asset_classes"],
    bonds: ["geographies", "currencies"],
    equities: ["geographies", "currencies"],
    hedge_funds: ["geographies", "currencies", "strategies"],
  };

  const FACET_LABELS: Record<FacetKey, string> = {
    geographies: "Geography",
    domiciles: "Domicile",
    currencies: "Currency",
    strategies: "Strategy",
    asset_classes: "Asset Class",
  };

  const ALL_FACET_KEYS: FacetKey[] = [
    "geographies",
    "domiciles",
    "currencies",
    "strategies",
    "asset_classes",
  ];

  let activeFacets = $derived(CHIP_FACETS[activeChip]);

  function facetItems(key: FacetKey): FacetItem[] {
    return facets[key] ?? [];
  }

  function isFacetActive(key: FacetKey): boolean {
    return activeFacets.includes(key);
  }

  function facetTooltip(key: FacetKey): string {
    const applicableTo = Object.entries(CHIP_FACETS)
      .filter(([, facetKeys]) => facetKeys.includes(key))
      .map(([chip]) => CHIP_LABELS[chip as ChipKey])
      .join(", ");
    return `Applies to ${applicableTo}`;
  }

  // ── Facet value bindings (map FacetKey → state) ──
  function getFacetValue(key: FacetKey): string | null {
    switch (key) {
      case "geographies":
        return searchGeography;
      case "domiciles":
        return searchDomicile;
      case "currencies":
        return searchCurrency;
      case "strategies":
        return searchStrategy;
      case "asset_classes":
        return searchAssetClass;
      default:
        return null;
    }
  }

  function setFacetValue(key: FacetKey, value: string | null) {
    switch (key) {
      case "geographies":
        searchGeography = value;
        break;
      case "domiciles":
        searchDomicile = value;
        break;
      case "currencies":
        searchCurrency = value;
        break;
      case "strategies":
        searchStrategy = value;
        break;
      case "asset_classes":
        searchAssetClass = value;
        // Cascade: clear strategy when asset class changes
        searchStrategy = null;
        break;
    }
    debouncedApply();
  }

  function selectChip(chip: ChipKey) {
    activeChip = chip;
    const filters = CHIP_FILTERS[chip];
    searchSource = filters.source ?? null;
    searchInstrumentType = filters.instrument_type ?? null;
    applySearchFilters();
  }

  // ── Debounced apply (300ms batch) ──
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  function debouncedApply() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => applySearchFilters(), 300);
  }

  // ── AUM debounce (500ms) ──
  let aumTimer: ReturnType<typeof setTimeout> | null = null;

  function onAumInput() {
    if (aumTimer) clearTimeout(aumTimer);
    aumTimer = setTimeout(() => applySearchFilters(), 500);
  }

  function applySearchFilters() {
    const params = new URLSearchParams();
    params.set("mode", "instruments");
    if (searchQ) params.set("q", searchQ);
    if (searchSource) params.set("source", searchSource);
    if (searchInstrumentType)
      params.set("instrument_type", searchInstrumentType);
    if (searchGeography) params.set("geography", searchGeography);
    if (searchDomicile) params.set("domicile", searchDomicile);
    if (searchCurrency) params.set("currency", searchCurrency);
    if (searchAssetClass) params.set("asset_class", searchAssetClass);
    if (searchStrategy) params.set("strategy", searchStrategy);
    if (searchAumMin) params.set("aum_min", searchAumMin);
    params.set("page", "1");
    params.set("page_size", "50");
    goto(`/screener?${params.toString()}`, { invalidateAll: true });
  }

  function clearSearchFilters() {
    searchQ = "";
    searchSource = null;
    searchInstrumentType = null;
    searchGeography = null;
    searchDomicile = null;
    searchCurrency = null;
    searchAssetClass = null;
    searchStrategy = null;
    searchAumMin = "";
    activeChip = "all";
    goto("/screener?mode=instruments", { invalidateAll: true });
  }

  function handleSearchKeydown(e: KeyboardEvent) {
    if (e.key === "Enter") applySearchFilters();
  }

  // Strategy is disabled when no asset class is selected (unless the chip already provides strategies)
  let strategyDisabledReason = $derived.by(() => {
    if (activeFacets.includes("strategies")) {
      // Strategy facet is active — only disable if no strategies available
      return facetItems("strategies").length === 0
        ? "No strategies available"
        : null;
    }
    return null; // Hidden, not disabled
  });
</script>

<!-- Search -->
<div class="scr-filter-section">
  <h3 class="scr-filter-title">Search</h3>
  <div class="scr-field">
    <input
      class="scr-input"
      type="text"
      placeholder="Name, ISIN, ticker, manager…"
      bind:value={searchQ}
      onkeydown={handleSearchKeydown}
    />
  </div>
</div>

<!-- Chips -->
<div class="scr-filter-section">
  <h3 class="scr-filter-title">Type</h3>
  <div class="chip-grid">
    {#each Object.entries(CHIP_LABELS) as [key, label] (key)}
      <button
        class="chip"
        class:chip--active={activeChip === key}
        onclick={() => selectChip(key as ChipKey)}
      >
        {label}
        {#if key === "all"}
          <span class="chip-count">{facets.total_universe}</span>
        {/if}
      </button>
    {/each}
  </div>
</div>

<!-- AUM Minimum -->
<div class="scr-filter-section">
  <h3 class="scr-filter-title">AUM</h3>
  <div class="scr-field">
    <label class="scr-label" for="search-aum-min">Minimum AUM (USD)</label>
    <input
      id="search-aum-min"
      class="scr-input"
      type="number"
      placeholder=""
      bind:value={searchAumMin}
      oninput={onAumInput}
    />
  </div>
</div>

<!-- Asset Class (always visible) -->
<div class="scr-filter-section">
  <h3 class="scr-filter-title">Asset Class</h3>
  <div class="scr-field">
    <select
      id="search-asset-class"
      class="scr-select"
      value={searchAssetClass}
      onchange={(e) =>
        setFacetValue(
          "asset_classes",
          (e.target as HTMLSelectElement).value || null,
        )}
    >
      <option value="">All</option>
      {#each facetItems("asset_classes") as item (item.value)}
        <option value={item.value}>{item.label} ({item.count})</option>
      {/each}
    </select>
  </div>
</div>

<!-- Dynamic dimension filters -->
<div class="scr-filter-section">
  <h3 class="scr-filter-title">Filters</h3>

  {#each ALL_FACET_KEYS as facetKey (facetKey)}
    {@const items = facetItems(facetKey)}
    {@const active = isFacetActive(facetKey)}
    <!-- Skip asset_classes — shown above separately -->
    {#if facetKey !== "asset_classes" && items.length > 0}
      {#if active}
        {#if facetKey === "strategies" && strategyDisabledReason}
          <div
            class="scr-field scr-field--disabled"
            title={strategyDisabledReason}
            transition:slide={{ duration: 200 }}
          >
            <label
              class="scr-label scr-label--disabled"
              for="search-{facetKey}-dis">{FACET_LABELS[facetKey]}</label
            >
            <select
              id="search-{facetKey}-dis"
              class="scr-select scr-select--disabled"
              disabled
            >
              <option>All</option>
            </select>
          </div>
        {:else}
          <div class="scr-field" transition:slide={{ duration: 200 }}>
            <label class="scr-label" for="search-{facetKey}"
              >{FACET_LABELS[facetKey]}</label
            >
            <select
              id="search-{facetKey}"
              class="scr-select"
              value={getFacetValue(facetKey)}
              onchange={(e) =>
                setFacetValue(
                  facetKey,
                  (e.target as HTMLSelectElement).value || null,
                )}
            >
              <option value="">All</option>
              {#each items as item (item.value)}
                <option value={item.value}>{item.label} ({item.count})</option>
              {/each}
            </select>
          </div>
        {/if}
      {:else}
        <div
          class="scr-field scr-field--disabled"
          title={facetTooltip(facetKey)}
          transition:slide={{ duration: 200 }}
        >
          <label
            class="scr-label scr-label--disabled"
            for="search-{facetKey}-dis">{FACET_LABELS[facetKey]}</label
          >
          <select
            id="search-{facetKey}-dis"
            class="scr-select scr-select--disabled"
            disabled
          >
            <option>All</option>
          </select>
        </div>
      {/if}
    {/if}
  {/each}

  <div class="scr-filter-btns">
    <Button size="sm" onclick={applySearchFilters}>Apply</Button>
    <Button size="sm" variant="ghost" onclick={clearSearchFilters}>Clear</Button
    >
  </div>
</div>

<!-- Facet summary -->
<div class="scr-filter-section scr-filter-section--meta">
  <h3 class="scr-filter-title">Universe</h3>
  <div class="scr-meta-row">
    <span class="scr-meta-k">Total</span>
    <span class="scr-meta-v">{formatNumber(facets.total_universe)}</span>
  </div>
  <div class="scr-meta-row">
    <span class="scr-meta-k">Screened</span>
    <span class="scr-meta-v">{formatNumber(facets.total_screened)}</span>
  </div>
  <div class="scr-meta-row">
    <span class="scr-meta-k">Approved</span>
    <span class="scr-meta-v">{formatNumber(facets.total_approved)}</span>
  </div>
</div>

<style>
  .scr-field--disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .scr-label--disabled {
    color: var(--ii-text-muted);
  }

  .scr-select--disabled {
    cursor: not-allowed;
    background: var(--ii-surface-alt);
  }
</style>
