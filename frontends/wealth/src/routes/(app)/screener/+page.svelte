<!--
  Screener Level 1 — Unified Fund Catalog.
  Toolbar: Search + AUM dropdown + Export (pill-shaped, bg-black).
  Content: CatalogTableV2 (manager-grouped grid from /screener/catalog/managers).
  Pills are in the parent +layout.svelte.
-->
<script lang="ts">
  import { goto } from "$app/navigation";
  import { page as pageState } from "$app/state";
  import { Search, Download, ChevronDown } from "lucide-svelte";
  import { CatalogTableV2 } from "$lib/components/screener";
  import type { PageData } from "./$types";

  let { data }: { data: PageData } = $props();

  // ── Search (synced to SSR data) ──
  let searchInput = $derived(data.q ?? "");
  let searchDebounce: ReturnType<typeof setTimeout> | null = null;

  function onSearchInput(e: Event) {
    const val = (e.target as HTMLInputElement).value;
    if (searchDebounce) clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      const params = new URLSearchParams(pageState.url.searchParams);
      if (val) {
        params.set("q", val);
      } else {
        params.delete("q");
      }
      params.delete("page");
      goto(`/screener?${params.toString()}`, { replaceState: true });
    }, 350);
  }

  // ── Pagination ──
  function onPageChange(newPage: number) {
    const params = new URLSearchParams(pageState.url.searchParams);
    params.set("page", String(newPage));
    goto(`/screener?${params.toString()}`);
  }

  // ── AUM Dropdown ──
  let aumDropdownOpen = $state(false);
  const AUM_OPTIONS = [
    { label: "AUM: Any", value: null },
    { label: "> $100M", value: 100000000 },
    { label: "> $1B", value: 1000000000 },
    { label: "> $10B", value: 10000000000 },
  ];

  let currentAum = $derived(
    pageState.url.searchParams.get("aum_min") ? Number(pageState.url.searchParams.get("aum_min")) : null
  );
  let currentAumLabel = $derived(
    AUM_OPTIONS.find((o) => o.value === currentAum)?.label ?? "AUM: Any"
  );

  function onAumSelect(val: number | null) {
    aumDropdownOpen = false;
    const params = new URLSearchParams(pageState.url.searchParams);
    if (val) {
      params.set("aum_min", String(val));
    } else {
      params.delete("aum_min");
    }
    params.delete("page");
    goto(`/screener?${params.toString()}`);
  }
</script>

<svelte:head>
  <title>Screener — InvestIntell</title>
</svelte:head>

<div class="scr-page">
  <!-- ── Toolbar: Search + AUM + Export + Count ── -->
  <div class="scr-toolbar">
    <div class="scr-toolbar-left">
      <div class="scr-search">
        <Search size={20} />
        <input
          type="text"
          class="scr-search-input"
          placeholder="Search by name..."
          value={searchInput}
          oninput={onSearchInput}
        />
      </div>

      <div class="scr-aum-wrapper">
        <button class="scr-aum-pill" onclick={() => aumDropdownOpen = !aumDropdownOpen}>
          <span>{currentAumLabel}</span>
          <ChevronDown size={20} />
        </button>

        {#if aumDropdownOpen}
          <div class="scr-aum-dropdown">
            {#each AUM_OPTIONS as opt}
              <button class="scr-aum-option" onclick={() => onAumSelect(opt.value)}>
                {opt.label}
              </button>
            {/each}
          </div>
        {/if}
      </div>
    </div>

    <div class="scr-toolbar-right">
      <span class="scr-count">
        {data.catalog.total.toLocaleString()} managers
      </span>
      <button class="scr-export" title="Export">
        <span>Export</span>
        <Download size={20} />
      </button>
    </div>
  </div>

  <!-- ── Table ── -->
  <div class="scr-content">
    <CatalogTableV2
      items={data.catalog.items}
      total={data.catalog.total}
      page={data.page}
      pageSize={data.catalog.page_size}
      hasNext={data.catalog.has_next}
      searchQuery={data.q}
      sort={data.sort || "aum_desc"}
      onPageChange={onPageChange}
    />
  </div>
</div>

<style>
  .scr-page {
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  /* ── Toolbar ── */
  .scr-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .scr-toolbar-left {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .scr-toolbar-right {
    display: flex;
    align-items: center;
    gap: 16px;
  }

  /* ── Search pill ── */
  .scr-search {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 24px;
    border: 1px solid #fff;
    border-radius: 36px;
    background: #000;
    color: #cbccd1;
    max-width: 320px;
    flex: 1;
  }

  .scr-search-input {
    flex: 1;
    min-width: 0;
    height: 100%;
    border: none !important;
    background: transparent !important;
    color: #fff;
    font-size: 17px;
    font-weight: 400;
    font-family: "Urbanist", sans-serif;
    outline: none !important;
    box-shadow: none !important;
    padding: 0;
    appearance: none;
    -webkit-appearance: none;
  }

  .scr-search-input::placeholder {
    color: #cbccd1;
  }

  /* ── AUM dropdown pill ── */
  .scr-aum-wrapper {
    position: relative;
    display: inline-block;
  }

  .scr-aum-dropdown {
    position: absolute;
    top: calc(100% + 8px);
    left: 0;
    background: #1a1b20;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 8px 0;
    min-width: 180px;
    z-index: 50;
    display: flex;
    flex-direction: column;
    box-shadow: 0 4px 20px rgba(0,0,0,0.4);
  }

  .scr-aum-option {
    padding: 10px 20px;
    background: transparent;
    border: none;
    color: #cbccd1;
    text-align: left;
    font-family: "Urbanist", sans-serif;
    font-size: 16px;
    cursor: pointer;
    transition: background 120ms ease;
  }

  .scr-aum-option:hover {
    background: #2a2b30;
    color: #fff;
  }

  .scr-aum-pill {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 14px 24px;
    border: 1px solid #fff;
    border-radius: 36px;
    background: #000;
    color: #cbccd1;
    font-size: 17px;
    font-weight: 400;
    font-family: "Urbanist", sans-serif;
    cursor: pointer;
    white-space: nowrap;
    transition: background 120ms ease;
  }

  .scr-aum-pill:hover {
    background: #1a1b20;
  }

  /* ── Count ── */
  .scr-count {
    font-size: 16px;
    color: #fff;
    font-weight: 400;
    font-family: "Urbanist", sans-serif;
    white-space: nowrap;
  }

  /* ── Export pill ── */
  .scr-export {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 14px 24px;
    border: 1px solid #fff;
    border-radius: 36px;
    background: #000;
    color: #cbccd1;
    font-size: 17px;
    font-weight: 400;
    font-family: "Urbanist", sans-serif;
    cursor: pointer;
    white-space: nowrap;
    transition: background 120ms ease;
  }

  .scr-export:hover {
    background: #1a1b20;
  }

  /* ── Content ── */
  .scr-content {
    flex: 1;
    min-height: 0;
  }
</style>
