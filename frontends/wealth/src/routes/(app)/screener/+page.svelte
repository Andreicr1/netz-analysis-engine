<!--
  Screener — Canvas-swap architecture.
  L1: CatalogTableV2 (manager grid) with toolbar.
  L2: ManagerDetailPanel (fund drill-down) replaces L1 in the same space.
  No Sheet/modal — pure canvas swap.
-->
<script lang="ts">
  import { getContext } from "svelte";
  import { goto } from "$app/navigation";
  import { page as pageState } from "$app/state";
  import { Search, Download, ChevronDown } from "lucide-svelte";
  import { CatalogTableV2 } from "$lib/components/screener";
  import ManagerDetailPanel from "$lib/components/screener/ManagerDetailPanel.svelte";
  import FundFactSheetContent from "$lib/components/screener/FundFactSheetContent.svelte";
  import * as Sheet from "@investintell/ui/components/ui/sheet";
  import type { ManagerCatalogItem, UnifiedFundItem } from "$lib/types/catalog";
  import { FUND_TYPE_LABELS } from "$lib/types/catalog";
  import type { PageData } from "./$types";
  import type { ColumnFiltersState } from "@investintell/ui/components/ui/data-table";
  import {
    EnterpriseFilterBar,
    decodeFilters,
    writeFiltersToParams,
    type ColumnFilterMeta,
  } from "$lib/components/screener/filters";

  let { data }: { data: PageData } = $props();

  const getToken = getContext<() => Promise<string>>("netz:getToken");

  // ── Canvas swap state: null = L1, manager = L2 ──
  let selectedManager = $state<ManagerCatalogItem | null>(null);

  // Restore L2 from URL params (e.g. back from fact sheet)
  $effect(() => {
    const managerId = pageState.url.searchParams.get("manager");
    const managerName = pageState.url.searchParams.get("manager_name");
    if (managerId && managerName && !selectedManager) {
      // Find from loaded items or create minimal stub
      const found = data.catalog.items.find((m: ManagerCatalogItem) => m.manager_id === managerId);
      selectedManager = found ?? {
        manager_id: managerId,
        manager_name: managerName,
        total_aum: null,
        fund_count: 0,
        fund_types: [],
        state: null,
        country: null,
        website: null,
      };
    }
  });

  function onSelectManager(manager: ManagerCatalogItem) {
    selectedManager = manager;
  }

  function onBack() {
    selectedManager = null;
    // Clean URL params
    const params = new URLSearchParams(pageState.url.searchParams);
    params.delete("manager");
    params.delete("manager_name");
    const qs = params.toString();
    goto(`/screener${qs ? `?${qs}` : ""}`, { replaceState: true });
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

  // ── Fund Type Quick Toggles ──
  const FUND_TYPE_PILLS = [
    { key: "MF", label: "MF" },
    { key: "HF", label: "HF" },
    { key: "PE", label: "PE" },
    { key: "VC", label: "VC" },
  ] as const;

  let activeFundTypes = $state<Set<string>>(new Set());

  function toggleFundType(key: string) {
    const next = new Set(activeFundTypes);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    activeFundTypes = next;
  }

  // ══════════════════════════════════════════════════════════════
  //  Enterprise column filters (Branch #4)
  // ══════════════════════════════════════════════════════════════
  //
  // State ownership: the Screener page owns `columnFilters` and the
  // `openFilterColumn` UI toggle. CatalogTableV2 consumes both as props
  // and invokes the callbacks back up — this is the "lift state" pattern
  // that keeps URL sync in one place.

  // Column metadata — derived from the current catalog page so enum
  // options (fund types, countries) reflect what is actually loaded. The
  // popover will not try to filter on columns the user cannot see.
  const fundTypeOptions = $derived.by(() => {
    const seen = new Set<string>();
    for (const item of data.catalog.items) {
      for (const ft of item.fund_types) seen.add(ft);
    }
    return Array.from(seen)
      .sort()
      .map((value) => ({
        value,
        label: FUND_TYPE_LABELS[value] ?? value,
      }));
  });

  const countryOptions = $derived.by(() => {
    const seen = new Set<string>();
    for (const item of data.catalog.items) {
      if (item.country) seen.add(item.country);
    }
    return Array.from(seen)
      .sort()
      .map((value) => ({ value, label: value }));
  });

  const filterColumns = $derived<ColumnFilterMeta[]>([
    { id: "manager_name", label: "Manager", type: "text" },
    { id: "total_aum", label: "AUM", type: "numeric", unit: "currency" },
    {
      id: "fund_types",
      label: "Fund type",
      type: "enum",
      arrayCell: true,
      options: fundTypeOptions,
    },
    {
      id: "country",
      label: "Country",
      type: "enum",
      options: countryOptions,
    },
  ]);

  // Column filter state — hydrated from URL on mount/navigation, lifted
  // from CatalogTableV2, fed back into the URL via writeFiltersToParams.
  let columnFilters = $state<ColumnFiltersState>(
    decodeFilters(pageState.url.searchParams),
  );
  let openFilterColumn = $state<string | null>(null);

  // URL sync — fires on every filter mutation. `replaceState` avoids a
  // history entry per keystroke; `noScroll` + `keepFocus` keep the popover
  // input focused while the user types.
  let lastSyncedUrlKey = $state<string>("");

  $effect(() => {
    // Read columnFilters reactively.
    const current = columnFilters;
    const params = new URLSearchParams(pageState.url.searchParams);
    writeFiltersToParams(params, current);
    const qs = params.toString();
    const target = `/screener${qs ? `?${qs}` : ""}`;
    // Avoid a goto loop: only sync when the resulting URL differs from
    // what we last wrote.
    if (target !== lastSyncedUrlKey) {
      lastSyncedUrlKey = target;
      // Also skip if the URL is already in sync (initial mount case).
      if (target !== pageState.url.pathname + pageState.url.search) {
        goto(target, {
          replaceState: true,
          noScroll: true,
          keepFocus: true,
        });
      }
    }
  });

  // Re-hydrate from URL on navigation (e.g. browser back/forward). When
  // the URL changes but columnFilters has not, adopt the URL as source of
  // truth.
  $effect(() => {
    const urlFilters = decodeFilters(pageState.url.searchParams);
    const localKey = JSON.stringify(columnFilters);
    const urlKey = JSON.stringify(urlFilters);
    if (localKey !== urlKey) {
      columnFilters = urlFilters;
    }
  });

  function removeFilter(columnId: string): void {
    columnFilters = columnFilters.filter(
      (f: ColumnFiltersState[number]) => f.id !== columnId,
    );
    if (openFilterColumn === columnId) openFilterColumn = null;
  }

  function clearAllFilters(): void {
    columnFilters = [];
    openFilterColumn = null;
  }

  function openEditFor(columnId: string): void {
    openFilterColumn = columnId;
  }

  // ══════════════════════════════════════════════════════════════
  //  Floating Fact Sheet preview (Branch #3)
  // ══════════════════════════════════════════════════════════════
  //
  // Instead of navigating to /screener/fund/[id], clicking a fund
  // inside ManagerDetailPanel sets `?fund=EXTERNAL_ID` in the URL
  // and opens a right-side Sheet containing FundFactSheetContent.
  // The standalone route is preserved as the PDF generation shell.

  interface FactSheetRouteData {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    data: Record<string, any> | null;
    error: {
      code?: string;
      message: string;
      recoverable: boolean;
    } | null;
  }

  const API_BASE =
    import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
  const FACT_SHEET_TIMEOUT_MS = 8000;

  let selectedFundId = $state<string | null>(
    pageState.url.searchParams.get("fund"),
  );
  let factSheetRouteData = $state<FactSheetRouteData>({
    data: null,
    error: null,
  });
  let factSheetLoading = $state(false);
  let previewOpen = $derived(selectedFundId != null);

  // Fetch the fact sheet payload whenever selectedFundId changes.
  // Uses the same endpoint the +page.server.ts route load hits, with
  // a matching 8s timeout + recoverable error handling so the same
  // FundFactSheetContent three-branch narrowing works identically.
  $effect(() => {
    const id = selectedFundId;
    if (!id || !getToken) {
      factSheetRouteData = { data: null, error: null };
      return;
    }
    const ctrl = new AbortController();
    factSheetLoading = true;
    factSheetRouteData = { data: null, error: null };

    (async () => {
      try {
        const token = await getToken();
        const res = await fetch(
          `${API_BASE}/screener/catalog/${encodeURIComponent(id)}/fact-sheet`,
          {
            headers: { Authorization: `Bearer ${token}` },
            signal: AbortSignal.any([
              ctrl.signal,
              AbortSignal.timeout(FACT_SHEET_TIMEOUT_MS),
            ]),
          },
        );
        if (!res.ok) {
          const recoverable = res.status >= 500 || res.status === 401 || res.status === 403;
          factSheetRouteData = {
            data: null,
            error: {
              code: `HTTP_${res.status}`,
              message:
                res.status === 404
                  ? "This fund is no longer in the catalog."
                  : `The fact sheet service returned ${res.status}.`,
              recoverable,
            },
          };
          return;
        }
        const payload = await res.json();
        factSheetRouteData = { data: payload, error: null };
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        const isTimeout =
          err instanceof DOMException && err.name === "TimeoutError";
        factSheetRouteData = {
          data: null,
          error: {
            code: isTimeout ? "TIMEOUT" : "UNKNOWN",
            message: isTimeout
              ? `Loading the fund took longer than ${FACT_SHEET_TIMEOUT_MS / 1000}s. Please try again.`
              : err instanceof Error
                ? err.message
                : "Failed to load fund data.",
            recoverable: true,
          },
        };
      } finally {
        factSheetLoading = false;
      }
    })();

    return () => ctrl.abort();
  });

  // Bidirectional URL sync for `?fund=ID`. Writes on state mutation,
  // re-hydrates on browser back/forward.
  let lastSyncedFundUrl = $state<string>("");

  $effect(() => {
    const id = selectedFundId;
    const params = new URLSearchParams(pageState.url.searchParams);
    if (id) {
      params.set("fund", id);
    } else {
      params.delete("fund");
    }
    const qs = params.toString();
    const target = `/screener${qs ? `?${qs}` : ""}`;
    if (target !== lastSyncedFundUrl) {
      lastSyncedFundUrl = target;
      if (target !== pageState.url.pathname + pageState.url.search) {
        goto(target, {
          replaceState: true,
          noScroll: true,
          keepFocus: true,
        });
      }
    }
  });

  $effect(() => {
    const urlFundId = pageState.url.searchParams.get("fund");
    if (urlFundId !== selectedFundId) {
      selectedFundId = urlFundId;
    }
  });

  function openFundPreview(fund: UnifiedFundItem): void {
    selectedFundId = fund.external_id;
  }

  function closeFundPreview(): void {
    selectedFundId = null;
  }

  function retryFactSheet(): void {
    // Bounce through null to re-trigger the fetch effect.
    const id = selectedFundId;
    selectedFundId = null;
    queueMicrotask(() => {
      selectedFundId = id;
    });
  }
</script>

<svelte:head>
  <title>Screener — InvestIntell</title>
</svelte:head>

<div class="scr-page">
  {#if selectedManager}
    <!-- ══ L2: Manager Fund Drill-down (canvas swap) ══ -->
    <ManagerDetailPanel
      manager={selectedManager}
      onBack={onBack}
      onFundClick={openFundPreview}
    />
  {:else}
    <!-- ══ L1: Manager Catalog ══ -->

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

        <!-- Fund Type Quick Toggles -->
        <div class="scr-toggles">
          {#each FUND_TYPE_PILLS as pill (pill.key)}
            <button
              class="scr-toggle"
              class:scr-toggle--active={activeFundTypes.has(pill.key)}
              onclick={() => toggleFundType(pill.key)}
            >
              {pill.label}
            </button>
          {/each}
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

    <!-- ── Enterprise Filter Bar (Branch #4) ── -->
    <div class="scr-filter-bar">
      <EnterpriseFilterBar
        filters={columnFilters}
        columns={filterColumns}
        onRemove={removeFilter}
        onEdit={openEditFor}
        onClearAll={clearAllFilters}
      />
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
        onSelectManager={onSelectManager}
        {columnFilters}
        onColumnFiltersChange={(next) => (columnFilters = next)}
        {filterColumns}
        {openFilterColumn}
        onOpenFilterChange={(id) => (openFilterColumn = id)}
      />
    </div>
  {/if}
</div>

<!--
  ══ Fact Sheet floating preview (Branch #3) ══
  Right-side Sheet, w-[min(100vw,960px)], !z-[60] to sit above the
  AI Drawer (which defaults to z-50). Overlay is bg-black/10 so the
  user still sees the filtered grid behind — a direct sightline to
  the underlying state is the whole point of using a preview rather
  than a full-page navigation. `!` prefixes override the shadcn-svelte
  Sheet defaults that ship with bits-ui.
-->
<Sheet.Root
  open={previewOpen}
  onOpenChange={(v) => {
    if (!v) closeFundPreview();
  }}
>
  <Sheet.Content
    side="right"
    class="!z-[60] w-[min(100vw,960px)] !max-w-[960px] sm:!max-w-[960px] p-0 gap-0 overflow-y-auto fs-sheet-content"
    showCloseButton={true}
  >
    {#if factSheetLoading && !factSheetRouteData.data && !factSheetRouteData.error}
      <div class="fs-sheet-loading">Loading fact sheet…</div>
    {:else}
      <FundFactSheetContent
        routeData={factSheetRouteData}
        showBackButton={false}
        onRetry={retryFactSheet}
      />
    {/if}
  </Sheet.Content>
</Sheet.Root>

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

  /* ── Fund Type Toggles ── */
  .scr-toggles {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .scr-toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 8px 16px;
    border: 1px solid #3a3b44;
    border-radius: 36px;
    background: transparent;
    color: #a1a1aa;
    font-size: 14px;
    font-weight: 600;
    font-family: "Urbanist", sans-serif;
    cursor: pointer;
    white-space: nowrap;
    transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
    letter-spacing: 0.02em;
  }

  .scr-toggle:hover {
    background: #22232a;
    border-color: #52525b;
    color: #fff;
  }

  .scr-toggle--active {
    background: #0177fb;
    border-color: transparent;
    color: #fff;
  }

  .scr-toggle--active:hover {
    background: #0166d9;
  }

  /* ── Filter bar (Branch #4) ── */
  .scr-filter-bar {
    padding: 0 24px;
  }
  .scr-filter-bar:empty {
    display: none;
  }

  /* ── Content ── */
  .scr-content {
    flex: 1;
    min-height: 0;
  }

  /* ══ Fact Sheet Sheet (Branch #3) ═══════════════════════════
     Notion-style single-scroll container + z-index above the AI
     Drawer. The Sheet primitive bakes a `z-50` overlay and we
     cannot pass a class to sheet-overlay (not exposed by
     @investintell/ui) — so we target the overlay via :global
     scoped to the page.

     The max-w-sm default shipped by bits-ui at the sm breakpoint
     overrides our width — we flatten it with a :global rule on
     the sheet-content slot.
     ══════════════════════════════════════════════════════════ */
  :global([data-slot="sheet-overlay"]) {
    z-index: 60 !important;
    background: rgba(0, 0, 0, 0.18) !important;
  }

  :global(.fs-sheet-content) {
    background: var(--ii-bg) !important;
    border-left: 1px solid var(--ii-border-subtle) !important;
    width: min(100vw, 960px) !important;
    max-width: 960px !important;
  }

  @media (min-width: 640px) {
    :global(.fs-sheet-content) {
      max-width: 960px !important;
    }
  }

  .fs-sheet-loading {
    padding: 48px 24px;
    text-align: center;
    font-family: "Urbanist", sans-serif;
    font-size: 13px;
    color: var(--ii-text-muted);
  }
</style>
