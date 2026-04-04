<!--
  Screener Level 1 — Unified Fund Catalog.
  Pills: Screening | Analytics | DD Reviews.
  Toolbar: Search + AUM dropdown + Export (pill-shaped, bg-black).
  Content: CatalogTableV2 (manager-grouped grid from /screener/catalog/managers).
  Design: Figma nodes 4032:1512, 4032:1510, 4032:2123, 4032:1513.
-->
<script lang="ts">
  import { goto } from "$app/navigation";
  import { page as pageState } from "$app/state";
  import { Search, Download, ChevronDown } from "lucide-svelte";
  import { CatalogTableV2 } from "$lib/components/screener";
  import DDReportList from "$lib/components/screener/DDReportList.svelte";
  import type { PageData } from "./$types";

  let { data }: { data: PageData } = $props();

  // ── Tab state (URL-driven) ──
  const TABS = [
    { key: "screening", label: "Screening" },
    { key: "analytics", label: "Analytics" },
    { key: "dd-reviews", label: "DD Reviews" },
  ] as const;

  let activeTab = $derived(data.tab ?? "screening");

  function switchTab(tab: string) {
    if (tab === "analytics") {
      goto("/analysis/lab");
      return;
    }
    const params = new URLSearchParams();
    params.set("tab", tab);
    goto(`/screener?${params.toString()}`, { replaceState: true });
  }

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
      params.set("tab", "screening");
      goto(`/screener?${params.toString()}`, { replaceState: true });
    }, 350);
  }

  // ── Pagination ──
  function onPageChange(newPage: number) {
    const params = new URLSearchParams(pageState.url.searchParams);
    params.set("page", String(newPage));
    goto(`/screener?${params.toString()}`);
  }
</script>

<svelte:head>
  <title>Screener — InvestIntell</title>
</svelte:head>

<div class="scr-page">
  <!-- ── Row 1: Pills + Export ── -->
  <div class="scr-row-1">
    <div class="scr-pills">
      {#each TABS as tab (tab.key)}
        <button
          class="scr-pill"
          class:scr-pill--active={activeTab === tab.key}
          onclick={() => switchTab(tab.key)}
        >
          {tab.label}
        </button>
      {/each}
    </div>

    {#if activeTab === "screening"}
      <button class="scr-export" title="Export">
        <span>Export</span>
        <Download size={20} />
      </button>
    {/if}
  </div>

  <!-- ── Row 2: Search + AUM + Count (only on Screening tab) ── -->
  {#if activeTab === "screening"}
    <div class="scr-row-2">
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

      <button class="scr-aum-pill">
        <span>AUM: Any</span>
        <ChevronDown size={20} />
      </button>

      <span class="scr-count">
        {data.catalog.total.toLocaleString()} managers
      </span>
    </div>
  {/if}

  <!-- ── Tab Content ── -->
  <div class="scr-content">
    {#if activeTab === "screening"}
      <CatalogTableV2
        items={data.catalog.items}
        total={data.catalog.total}
        page={data.page}
        pageSize={data.catalog.page_size}
        hasNext={data.catalog.has_next}
        searchQuery={data.q}
        onPageChange={onPageChange}
      />
    {:else if activeTab === "dd-reviews"}
      <DDReportList />
    {/if}
  </div>
</div>

<style>
  .scr-page {
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 24px;
  }

  /* ── Row 1: Pills + Export ── */
  .scr-row-1 {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  /* ── Pills (Figma: 35.572px radius, py-18, px-27, 20px Urbanist) ── */
  .scr-pills {
    display: flex;
    gap: 0;
  }

  .scr-pill {
    padding: 14px 24px;
    border: none;
    border-radius: 36px;
    background: #000;
    color: #fff;
    font-size: 17px;
    font-weight: 400;
    font-family: "Urbanist", sans-serif;
    cursor: pointer;
    white-space: nowrap;
    transition: background 120ms ease;
  }

  .scr-pill:hover {
    background: #1a1b20;
  }

  .scr-pill--active {
    background: #0177fb;
  }

  .scr-pill--active:hover {
    background: #0166d9;
  }

  /* ── Export pill (Figma: bg-black, 35.572px radius, text #cbccd1 20.7px) ── */
  .scr-export {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 14px 24px;
    border: none;
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

  /* ── Row 2: Search + AUM + Count ── */
  .scr-row-2 {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  /* ── Search pill (Figma: bg-black, 35.572px radius, 20.7px, icon 24px) ── */
  .scr-search {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 24px;
    border: none;
    border-radius: 36px;
    background: #000;
    color: #cbccd1;
    max-width: 320px;
    flex: 1;
  }

  .scr-search-input {
    width: 100%;
    border: none;
    background: transparent;
    color: #fff;
    font-size: 17px;
    font-weight: 400;
    font-family: "Urbanist", sans-serif;
    outline: none;
  }

  .scr-search-input::placeholder {
    color: #cbccd1;
  }

  /* ── AUM dropdown pill (same shape as search) ── */
  .scr-aum-pill {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 14px 24px;
    border: none;
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

  /* ── Count (Figma: text-white 16px Urbanist Regular, right-aligned) ── */
  .scr-count {
    margin-left: auto;
    font-size: 16px;
    color: #fff;
    font-weight: 400;
    font-family: "Urbanist", sans-serif;
    white-space: nowrap;
  }

  /* ── Content ── */
  .scr-content {
    flex: 1;
    min-height: 0;
  }

</style>
