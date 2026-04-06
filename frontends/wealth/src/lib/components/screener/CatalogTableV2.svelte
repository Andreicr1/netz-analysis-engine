<!--
  CatalogTableV2 — Level 1 Manager Catalog (Institutional Grid).
  Rows = Managers grouped by CRD. Columns: CRD, Manager, Funds (badges), AUM, Location, Website.
  Row click → Level 2 ManagerDetailPanel (80vw Sheet).
  Design: Dark graphite panel, neon badges, Urbanist font.
-->
<script lang="ts">
  import { formatAUM } from "@investintell/ui";
  import type { ManagerCatalogItem } from "$lib/types/catalog";
  import { FUND_TYPE_BADGE_MAP } from "$lib/types/catalog";

  interface Props {
    items: ManagerCatalogItem[];
    total: number;
    page: number;
    pageSize: number;
    hasNext: boolean;
    searchQuery?: string;
    sort?: string;
    onPageChange?: (page: number) => void;
    onSelectManager?: (manager: ManagerCatalogItem) => void;
  }

  let {
    items = [],
    total = 0,
    page = 1,
    pageSize = 50,
    hasNext = false,
    searchQuery = "",
    sort = "aum_desc",
    onPageChange,
    onSelectManager,
  }: Props = $props();

  import { page as pageState } from "$app/state";
  import { goto } from "$app/navigation";
  import { ChevronUp, ChevronDown } from "lucide-svelte";

  function setSort(col: "name" | "aum") {
    const params = new URLSearchParams(pageState.url.searchParams);
    let newSort = "";
    if (col === "name") {
      newSort = sort === "name_asc" ? "name_desc" : "name_asc";
    } else if (col === "aum") {
      newSort = sort === "aum_desc" ? "aum_asc" : "aum_desc";
    }
    params.set("sort", newSort);
    // Reset to page 1 on sort change
    params.set("page", "1");
    goto(`?${params.toString()}`);
  }

  function openManagerPanel(item: ManagerCatalogItem) {
    onSelectManager?.(item);
  }

  // ── Name cleansing: strip legal suffixes + Title Case ──
  const LEGAL_SUFFIXES =
    /[,.]?\s*\b(LLC|L\.L\.C\.|INC\.?|L\.P\.|LP|LLP|CORP\.?|CORPORATION|LTD\.?|S\.A\.?|N\.A\.?|COMPANY|CO\.?|GROUP)\b[.,]?\s*/gi;

  function formatName(raw: string): string {
    const stripped = raw.replace(LEGAL_SUFFIXES, " ").replace(/\s{2,}/g, " ").trim().replace(/,\s*$/, "");
    return stripped
      .split(" ")
      .map((w) => {
        if (w === "&" || w === "AND") return "&";
        if (w.length <= 2 && w === w.toUpperCase()) return w;
        return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
      })
      .join(" ");
  }

  /** Extract initials (first 2 words) for avatar. */
  function initials(name: string): string {
    return formatName(name)
      .split(" ")
      .filter((w) => w.length > 0 && w !== "&")
      .slice(0, 2)
      .map((w) => w[0])
      .join("")
      .toUpperCase();
  }

  function formatLocation(item: ManagerCatalogItem): string {
    if (item.state && item.country) return `${item.state}, ${item.country}`;
    return item.state ?? item.country ?? "\u2014";
  }

  // ── Pagination ──
  const totalPages = $derived(Math.max(1, Math.ceil(total / pageSize)));

  function goPage(p: number) {
    if (p < 1 || p > totalPages) return;
    onPageChange?.(p);
  }
</script>

<div class="ct2-root">
  <!-- ── Table ── -->
  <div class="ct2-table-wrap">
    <table class="ct2-table">
      <thead>
        <tr class="ct2-thead-row">
          <th class="ct2-th ct2-th--crd">CRD</th>
          <th class="ct2-th ct2-th--manager ct2-th--sortable" onclick={() => setSort("name")}>
            Manager
            <div class="sort-stacked">
              <ChevronUp size={12} color={sort === "name_asc" ? "#fff" : "#52525b"} strokeWidth={sort === "name_asc" ? 3 : 2} />
              <ChevronDown size={12} color={sort === "name_desc" ? "#fff" : "#52525b"} strokeWidth={sort === "name_desc" ? 3 : 2} />
            </div>
          </th>
          <th class="ct2-th ct2-th--funds">Funds</th>
          <th class="ct2-th ct2-th--aum ct2-th--sortable" onclick={() => setSort("aum")}>
            AUM
            <div class="sort-stacked">
              <ChevronUp size={12} color={sort === "aum_asc" ? "#fff" : "#52525b"} strokeWidth={sort === "aum_asc" ? 3 : 2} />
              <ChevronDown size={12} color={sort === "aum_desc" ? "#fff" : "#52525b"} strokeWidth={sort === "aum_desc" ? 3 : 2} />
            </div>
          </th>
          <th class="ct2-th ct2-th--location">Location</th>
          <th class="ct2-th ct2-th--website">Website</th>
        </tr>
      </thead>
      <tbody>
        {#each items as item (item.manager_id)}
          <tr
            class="ct2-row"
            onclick={() => openManagerPanel(item)}
          >
            <!-- CRD -->
            <td class="ct2-cell ct2-cell--crd">
              <span class="ct2-crd">{item.manager_id}</span>
            </td>

            <!-- Manager Cell: Avatar + Name -->
            <td class="ct2-cell ct2-cell--manager">
              <div class="ct2-manager-flex">
                <div class="ct2-avatar" title={item.manager_name}>
                  {initials(item.manager_name)}
                </div>
                <span class="ct2-manager-name">
                  {formatName(item.manager_name)}
                </span>
              </div>
            </td>

            <!-- Fund Type Badges -->
            <td class="ct2-cell ct2-cell--funds">
              <div class="ct2-badges">
                {#each item.fund_types as ft}
                  {@const badge = FUND_TYPE_BADGE_MAP[ft]}
                  {#if badge}
                    <span class="ct2-badge {badge.colorClass}">{badge.label}</span>
                  {:else}
                    <span class="ct2-badge badge-default">{ft}</span>
                  {/if}
                {/each}
              </div>
            </td>

            <!-- AUM (right-aligned, formatted) -->
            <td class="ct2-cell ct2-cell--aum">
              {item.total_aum != null ? formatAUM(item.total_aum) : "\u2014"}
            </td>

            <!-- Location -->
            <td class="ct2-cell ct2-cell--location">
              {formatLocation(item)}
            </td>

            <!-- Website -->
            <td class="ct2-cell ct2-cell--website">
              {#if item.website}
                <a
                  href={item.website.startsWith("http") ? item.website : `https://${item.website}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  class="ct2-website-link"
                  onclick={(e: MouseEvent) => e.stopPropagation()}
                >
                  {item.website.toLowerCase().replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")}
                </a>
              {:else}
                <span class="ct2-muted">&mdash;</span>
              {/if}
            </td>
          </tr>
        {:else}
          <tr>
            <td colspan="6" class="ct2-empty">
              {searchQuery ? "No managers match your search." : "No managers found."}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <!-- ── Pagination Footer ── -->
  {#if total > pageSize}
    <div class="ct2-pagination">
      <span class="ct2-pagination-info">
        {((page - 1) * pageSize + 1).toLocaleString()}&ndash;{Math.min(page * pageSize, total).toLocaleString()} of {total.toLocaleString()}
      </span>
      <div class="ct2-pagination-buttons">
        <button class="ct2-page-btn" disabled={page <= 1} onclick={() => goPage(page - 1)}>
          Prev
        </button>
        <span class="ct2-page-num">{page} / {totalPages}</span>
        <button class="ct2-page-btn" disabled={!hasNext} onclick={() => goPage(page + 1)}>
          Next
        </button>
      </div>
    </div>
  {/if}
</div>


<style>
  /* ══════════════════════════════════════════════════════════
     CatalogTableV2 — hardcoded dark palette.
     No CSS variables — Svelte 5 :where() specificity = 0,
     so Tailwind base reset can override var() fallbacks.
     ══════════════════════════════════════════════════════════ */
  .ct2-root {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    background: #141519;
    border-radius: 32px 0 0 0;
    overflow: hidden;
    color: #a1a1aa;
  }

  .ct2-table {
    width: 100%;
    border-collapse: collapse;
  }

  .ct2-table-wrap {
    flex: 1;
    overflow-y: auto;
    overflow-x: auto;
  }

  /* Custom scrollbar for table */
  .ct2-table-wrap::-webkit-scrollbar {
    width: 8px;
    height: 8px;
  }
  .ct2-table-wrap::-webkit-scrollbar-track {
    background: #141519;
  }
  .ct2-table-wrap::-webkit-scrollbar-thumb {
    background: #2a2b33;
    border-radius: 4px;
  }
  .ct2-table-wrap::-webkit-scrollbar-thumb:hover {
    background: #3f3f46;
  }

  /* ── Header ── */
  .ct2-thead-row {
    border-bottom: none;
  }

  .ct2-thead-row:hover {
    background: transparent !important;
  }

  .ct2-th {
    color: #cbccd1;
    font-size: 0.875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    white-space: nowrap;
    height: 48px;
    padding: 0 16px;
    font-family: "Urbanist", sans-serif;
    text-align: left;
    position: sticky;
    top: 0;
    background: rgba(20, 21, 25, 0.95);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    z-index: 10;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  }

  .ct2-th--sortable {
    cursor: pointer;
    transition: color 100ms ease;
  }

  .ct2-th--sortable:hover {
    color: #fff;
  }

  .sort-stacked {
    display: inline-flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    vertical-align: middle;
    margin-left: 6px;
    gap: 0;
  }
  
  .sort-stacked :global(svg) {
    display: block;
    margin: -2px 0; /* Tighten the gap between the two chevrons */
  }

  .ct2-th--crd { width: 100px; padding-left: 24px; }
  .ct2-th--manager { min-width: 240px; }
  .ct2-th--funds { min-width: 180px; }
  .ct2-th--aum { width: 180px; text-align: right; padding-right: 48px; }
  .ct2-th--location { width: 160px; }
  .ct2-th--website { width: 220px; }

  /* ── Rows ── */
  .ct2-row {
    border-bottom: 1px solid rgba(42, 43, 51, 0.5);
    cursor: pointer;
    transition: background 80ms ease;
  }

  .ct2-row:hover {
    background: #22232a !important;
  }

  .ct2-row:nth-child(even) {
    background: rgba(34, 35, 42, 0.3);
  }

  .ct2-row:nth-child(even):hover {
    background: #22232a !important;
  }

  /* ── Cells ── */
  .ct2-cell {
    padding: 12px 16px;
    font-family: "Urbanist", sans-serif;
    font-size: 0.9375rem;
    color: #cbccd1;
    vertical-align: middle;
  }

  .ct2-cell--crd { padding-left: 24px; }

  .ct2-crd {
    font-family: "Geist Mono", monospace;
    font-size: 0.875rem;
    color: #a1a1aa;
  }

  .ct2-manager-flex {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .ct2-avatar {
    width: 34px;
    height: 34px;
    border-radius: 6px;
    background: #22232a;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 700;
    color: #71717a;
    letter-spacing: 0.03em;
    flex-shrink: 0;
  }

  .ct2-manager-name {
    color: #fff;
    font-weight: 600;
    font-size: 1rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 260px;
  }

  .ct2-badges {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  .ct2-badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.04em;
    white-space: nowrap;
    border: 1px solid;
  }

  /* Badge neon palette — hardcoded */
  .badge-mf { color: #60a5fa; background: rgba(96, 165, 250, 0.12); border-color: rgba(96, 165, 250, 0.25); }
  .badge-etf { color: #22d3ee; background: rgba(34, 211, 238, 0.12); border-color: rgba(34, 211, 238, 0.25); }
  .badge-cef { color: #818cf8; background: rgba(129, 140, 248, 0.12); border-color: rgba(129, 140, 248, 0.25); }
  .badge-bdc { color: #fbbf24; background: rgba(251, 191, 36, 0.12); border-color: rgba(251, 191, 36, 0.25); }
  .badge-mmf { color: #94a3b8; background: rgba(148, 163, 184, 0.12); border-color: rgba(148, 163, 184, 0.25); }
  .badge-hf { color: #c084fc; background: rgba(192, 132, 252, 0.12); border-color: rgba(192, 132, 252, 0.25); }
  .badge-pe { color: #34d399; background: rgba(52, 211, 153, 0.12); border-color: rgba(52, 211, 153, 0.25); }
  .badge-vc { color: #fb923c; background: rgba(251, 146, 60, 0.12); border-color: rgba(251, 146, 60, 0.25); }
  .badge-re { color: #2dd4bf; background: rgba(45, 212, 191, 0.12); border-color: rgba(45, 212, 191, 0.25); }
  .badge-sa { color: #f472b6; background: rgba(244, 114, 182, 0.12); border-color: rgba(244, 114, 182, 0.25); }
  .badge-lf { color: #67e8f9; background: rgba(103, 232, 249, 0.12); border-color: rgba(103, 232, 249, 0.25); }
  .badge-pf { color: #f87171; background: rgba(248, 113, 113, 0.12); border-color: rgba(248, 113, 113, 0.25); }
  .badge-ucits { color: #a78bfa; background: rgba(167, 139, 250, 0.12); border-color: rgba(167, 139, 250, 0.25); }
  .badge-default { color: #a1a1aa; background: rgba(161, 161, 170, 0.08); border-color: rgba(161, 161, 170, 0.15); }

  .ct2-cell--aum {
    text-align: right;
    padding-right: 48px;
    font-family: "Geist Mono", monospace;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: #fafafa;
  }

  .ct2-cell--location {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 160px;
  }

  .ct2-website-link {
    color: #a1a1aa;
    text-decoration: none;
    font-size: 0.875rem;
    transition: color 120ms ease;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: block;
    max-width: 200px;
  }

  .ct2-website-link:hover {
    color: #0177fb;
  }

  .ct2-muted {
    color: #71717a;
  }

  .ct2-empty {
    text-align: center;
    padding: 48px 16px !important;
    color: #71717a;
    font-size: 0.9375rem;
  }

  /* ── Pagination ── */
  .ct2-pagination {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 24px;
    border-top: 1px solid #2a2b33;
  }

  .ct2-pagination-info {
    font-size: 0.75rem;
    color: #71717a;
    font-variant-numeric: tabular-nums;
    font-family: "Urbanist", sans-serif;
  }

  .ct2-pagination-buttons {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .ct2-page-btn {
    padding: 4px 14px;
    border: 1px solid #3a3b44;
    border-radius: 8px;
    background: transparent;
    color: #a1a1aa;
    font-size: 0.75rem;
    font-weight: 600;
    font-family: "Urbanist", sans-serif;
    cursor: pointer;
    transition: background 100ms ease, border-color 100ms ease;
  }

  .ct2-page-btn:hover:not(:disabled) {
    background: #22232a;
    border-color: #0177fb;
  }

  .ct2-page-btn:disabled {
    opacity: 0.35;
    cursor: not-allowed;
  }

  .ct2-page-num {
    font-size: 0.75rem;
    color: #71717a;
    font-variant-numeric: tabular-nums;
  }
</style>
