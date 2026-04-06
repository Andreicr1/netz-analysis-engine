<!--
  ManagerDetailPanel — Level 2 Canvas (full-space swap).
  Replaces L1 manager grid when a manager is selected.
  No Sheet/modal — occupies the same content area as CatalogTableV2.
  Premium header + high-density fund table. 5 columns: Name, Ticker, Type, Strategy, AUM.
-->
<script lang="ts">
  import { getContext } from "svelte";
  import { goto } from "$app/navigation";
  import { ArrowLeft, ExternalLink, Loader2, Sparkles } from "lucide-svelte";
  import { formatAUM } from "@investintell/ui";
  import { createClientApiClient } from "$lib/api/client";
  import type { UnifiedFundItem, UnifiedCatalogPage, ManagerCatalogItem } from "$lib/types/catalog";
  import { FUND_TYPE_BADGE_MAP } from "$lib/types/catalog";

  interface Props {
    manager: ManagerCatalogItem;
    onBack: () => void;
  }

  let { manager, onBack }: Props = $props();

  const getToken = getContext<() => Promise<string>>("netz:getToken");
  const api = createClientApiClient(getToken);

  let fundItems = $state<UnifiedFundItem[]>([]);
  let isLoadingFunds = $state(false);
  let totalFunds = $state(0);

  $effect(() => {
    if (manager?.manager_id) {
      fetchFunds(manager.manager_id);
    }
  });

  async function fetchFunds(crd: string) {
    isLoadingFunds = true;
    try {
      const result = await api.get<UnifiedCatalogPage>("/screener/catalog", {
        manager_id: crd,
        has_nav: "true",
        has_aum: "false",
        page_size: "200",
      });
      fundItems = result.items ?? [];
      totalFunds = result.total ?? 0;
    } catch {
      fundItems = [];
      totalFunds = 0;
    } finally {
      isLoadingFunds = false;
    }
  }

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

  function badgeFor(ft: string) {
    return FUND_TYPE_BADGE_MAP[ft] ?? { label: ft, colorClass: "badge-default" };
  }

  function openFactSheet(fund: UnifiedFundItem) {
    const params = new URLSearchParams({
      manager: manager.manager_id,
      manager_name: manager.manager_name,
    });
    goto(`/screener/fund/${fund.external_id}?${params.toString()}`);
  }

  let ddConfirmFund = $state<UnifiedFundItem | null>(null);
  let ddGenerating = $state(false);

  function promptDD(fund: UnifiedFundItem) {
    ddConfirmFund = fund;
  }

  function cancelDD() {
    ddConfirmFund = null;
  }

  async function confirmDD() {
    if (!ddConfirmFund || ddGenerating) return;
    ddGenerating = true;
    try {
      const result = await api.post<{ id: string; instrument_id: string }>("/dd-reports/generate", {
        instrument_external_id: ddConfirmFund.external_id,
      });
      ddConfirmFund = null;
      goto(`/screener/dd-reports/${result.instrument_id}/${result.id}`);
    } catch {
      ddGenerating = false;
    }
  }
</script>

<div class="l2-root">
  <!-- ── Premium Header ── -->
  <div class="l2-header">
    <button class="l2-back" onclick={onBack}>
      <ArrowLeft size={16} />
      <span>Back to Managers</span>
    </button>
    <div class="l2-header-row">
      <div class="l2-header-left">
        <h2 class="l2-title">{formatName(manager.manager_name)}</h2>
        <div class="l2-meta">
          <span class="l2-meta-mono">CRD: {manager.manager_id}</span>
          <span class="l2-dot"></span>
          <span class="l2-meta-highlight">{totalFunds || manager.fund_count} fund{(totalFunds || manager.fund_count) !== 1 ? "s" : ""}</span>
          {#if manager.state || manager.country}
            <span class="l2-dot"></span>
            <span>{manager.state ?? ""}{manager.state && manager.country ? ", " : ""}{manager.country ?? ""}</span>
          {/if}
        </div>
      </div>
      {#if manager.total_aum != null}
        <div class="l2-header-right">
          <div class="l2-aum-label">Total Managed AUM</div>
          <div class="l2-aum-value">{formatAUM(manager.total_aum)}</div>
        </div>
      {/if}
    </div>
  </div>

  <!-- ── Fund Table ── -->
  <div class="l2-table-area">
    {#if isLoadingFunds}
      <div class="l2-loading">
        <Loader2 class="animate-spin" size={22} />
        <span>Loading funds...</span>
      </div>
    {:else if fundItems.length === 0}
      <div class="l2-empty">No fund data available for this manager.</div>
    {:else}
      <table class="l2-table">
        <thead>
          <tr class="l2-thead">
            <th class="l2-th l2-th--name">Fund Name</th>
            <th class="l2-th l2-th--ticker">Ticker</th>
            <th class="l2-th l2-th--type">Type</th>
            <th class="l2-th l2-th--strategy">Strategy</th>
            <th class="l2-th l2-th--aum">GAV / AUM</th>
            <th class="l2-th l2-th--actions"></th>
          </tr>
        </thead>
        <tbody>
          {#each fundItems as fund, i (fund.external_id)}
            {@const b = badgeFor(fund.fund_type)}
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
            <tr
              class="l2-row"
              class:l2-row--alt={i % 2 === 1}
              onclick={() => openFactSheet(fund)}
            >
              <td class="l2-cell l2-cell--name">
                {formatName(fund.name)}
              </td>
              <td class="l2-cell l2-cell--ticker">
                {#if fund.ticker}
                  <span class="l2-ticker-badge">{fund.ticker}</span>
                {:else}
                  <span class="l2-muted">&mdash;</span>
                {/if}
              </td>
              <td class="l2-cell l2-cell--type">
                <span class="l2-type-badge" style="color:{BADGE_HEX[b.colorClass] ?? '#a1a1aa'};background:{BADGE_BG[b.colorClass] ?? 'rgba(161,161,170,0.08)'};border-color:{BADGE_BORDER[b.colorClass] ?? 'rgba(161,161,170,0.15)'}">
                  {b.label}
                </span>
              </td>
              <td class="l2-cell l2-cell--strategy">
                {fund.strategy_label ?? "\u2014"}
              </td>
              <td class="l2-cell l2-cell--aum">
                {fund.aum != null ? formatAUM(fund.aum) : "\u2014"}
              </td>
              <td class="l2-cell l2-cell--actions">
                <button
                  class="l2-action-btn"
                  title="Generate DD Report"
                  onclick={(e: MouseEvent) => { e.stopPropagation(); promptDD(fund); }}
                >
                  <Sparkles size={14} />
                </button>
                <button
                  class="l2-action-btn"
                  title="Fact Sheet"
                  onclick={(e: MouseEvent) => { e.stopPropagation(); openFactSheet(fund); }}
                >
                  <ExternalLink size={14} />
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>

      <div class="l2-footer">
        {totalFunds} fund{totalFunds !== 1 ? "s" : ""}
      </div>
    {/if}
  </div>
</div>

<!-- ── DD Confirmation Dialog ── -->
{#if ddConfirmFund}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="fixed inset-0 z-[60] flex items-center justify-center">
    <div class="absolute inset-0 bg-black/50 backdrop-blur-sm" onclick={cancelDD}></div>
    <div class="l2-dialog">
      <h3 class="l2-dialog-title">Generate DD Report</h3>
      <p class="l2-dialog-body">
        Generate an 8-chapter Due Diligence report for
        <strong class="text-white">{ddConfirmFund.name}</strong>?
        This is a high-stakes operation (~26k tokens, ~2 minutes).
      </p>
      <div class="l2-dialog-actions">
        <button class="l2-dialog-cancel" onclick={cancelDD} disabled={ddGenerating}>Cancel</button>
        <button class="l2-dialog-confirm" onclick={confirmDD} disabled={ddGenerating}>
          {#if ddGenerating}
            <Loader2 size={14} class="animate-spin" />
            Generating...
          {:else}
            <Sparkles size={14} />
            Generate Report
          {/if}
        </button>
      </div>
    </div>
  </div>
{/if}

<script module>
  /** Badge color maps — extracted for scoped CSS compat */
  const BADGE_HEX: Record<string, string> = {
    "badge-mf":"#60a5fa","badge-etf":"#22d3ee","badge-cef":"#818cf8","badge-bdc":"#fbbf24",
    "badge-mmf":"#94a3b8","badge-hf":"#c084fc","badge-pe":"#34d399","badge-vc":"#fb923c",
    "badge-re":"#2dd4bf","badge-sa":"#f472b6","badge-lf":"#67e8f9","badge-pf":"#f87171",
    "badge-ucits":"#a78bfa","badge-default":"#a1a1aa",
  };
  const BADGE_BG: Record<string, string> = {
    "badge-mf":"rgba(96,165,250,0.10)","badge-etf":"rgba(34,211,238,0.10)","badge-cef":"rgba(129,140,248,0.10)",
    "badge-bdc":"rgba(251,191,36,0.10)","badge-mmf":"rgba(148,163,184,0.10)","badge-hf":"rgba(192,132,252,0.10)",
    "badge-pe":"rgba(52,211,153,0.10)","badge-vc":"rgba(251,146,60,0.10)","badge-re":"rgba(45,212,191,0.10)",
    "badge-sa":"rgba(244,114,182,0.10)","badge-lf":"rgba(103,232,249,0.10)","badge-pf":"rgba(248,113,113,0.10)",
    "badge-ucits":"rgba(167,139,250,0.10)","badge-default":"rgba(161,161,170,0.06)",
  };
  const BADGE_BORDER: Record<string, string> = {
    "badge-mf":"rgba(96,165,250,0.20)","badge-etf":"rgba(34,211,238,0.20)","badge-cef":"rgba(129,140,248,0.20)",
    "badge-bdc":"rgba(251,191,36,0.20)","badge-mmf":"rgba(148,163,184,0.20)","badge-hf":"rgba(192,132,252,0.20)",
    "badge-pe":"rgba(52,211,153,0.20)","badge-vc":"rgba(251,146,60,0.20)","badge-re":"rgba(45,212,191,0.20)",
    "badge-sa":"rgba(244,114,182,0.20)","badge-lf":"rgba(103,232,249,0.20)","badge-pf":"rgba(248,113,113,0.20)",
    "badge-ucits":"rgba(167,139,250,0.20)","badge-default":"rgba(161,161,170,0.12)",
  };
</script>

<style>
  /* ══════════════════════════════════════════════════════════
     Level 2 — Canvas-swap manager drill-down.
     High-density institutional table. $20k/yr terminal feel.
     ══════════════════════════════════════════════════════════ */

  .l2-root {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    background: #141519;
    border-radius: 32px 0 0 0;
    overflow: hidden;
    animation: l2-fade-in 200ms ease-out;
  }

  @keyframes l2-fade-in {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  /* ── Header ── */

  .l2-header {
    flex-shrink: 0;
    padding: 24px 32px 20px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  }

  .l2-back {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 0;
    border: none;
    background: transparent;
    color: #71717a;
    font-size: 0.8125rem;
    font-family: "Urbanist", sans-serif;
    cursor: pointer;
    transition: color 120ms ease;
    margin-bottom: 16px;
  }

  .l2-back:hover {
    color: #0177fb;
  }

  .l2-header-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
  }

  .l2-title {
    font-size: 1.875rem;
    font-weight: 700;
    letter-spacing: -0.025em;
    color: #fafafa;
    font-family: "Urbanist", sans-serif;
    line-height: 1.15;
    margin: 0;
  }

  .l2-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 8px;
    font-size: 0.8125rem;
    color: #71717a;
    font-family: "Urbanist", sans-serif;
  }

  .l2-meta-mono {
    font-family: "Geist Mono", monospace;
  }

  .l2-meta-highlight {
    color: #fafafa;
    font-weight: 500;
  }

  .l2-dot {
    width: 3px;
    height: 3px;
    border-radius: 50%;
    background: #3a3b44;
    flex-shrink: 0;
  }

  .l2-header-right {
    text-align: right;
    flex-shrink: 0;
  }

  .l2-aum-label {
    font-size: 0.6875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #71717a;
    font-family: "Urbanist", sans-serif;
    margin-bottom: 4px;
  }

  .l2-aum-value {
    font-size: 1.5rem;
    font-weight: 700;
    color: #fafafa;
    font-family: "Geist Mono", monospace;
    font-variant-numeric: tabular-nums;
  }

  /* ── Table area — matches L1 ct2-table-wrap ── */

  .l2-table-area {
    flex: 1;
    overflow-y: auto;
    overflow-x: auto;
  }

  .l2-table-area::-webkit-scrollbar { width: 8px; height: 8px; }
  .l2-table-area::-webkit-scrollbar-track { background: #141519; }
  .l2-table-area::-webkit-scrollbar-thumb { background: #2a2b33; border-radius: 4px; }
  .l2-table-area::-webkit-scrollbar-thumb:hover { background: #3f3f46; }

  .l2-loading {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    padding: 80px 0;
    color: #71717a;
    font-size: 0.9375rem;
  }

  .l2-empty {
    padding: 80px 0;
    text-align: center;
    color: #71717a;
    font-size: 0.9375rem;
  }

  .l2-table {
    width: 100%;
    border-collapse: collapse;
  }

  /* ── Table header — identical to L1 ct2-th ── */

  .l2-thead {
    border-bottom: none;
  }

  .l2-th {
    color: #cbccd1;
    font-size: 0.875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
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
    white-space: nowrap;
  }

  .l2-th--name { padding-left: 24px; }
  .l2-th--ticker { width: 100px; }
  .l2-th--type { width: 80px; }
  .l2-th--strategy { width: 180px; }
  .l2-th--aum { width: 180px; text-align: right; padding-right: 48px; }
  .l2-th--actions { width: 80px; }

  /* ── Table rows — identical to L1 ct2-row ── */

  .l2-row {
    border-bottom: 1px solid rgba(42, 43, 51, 0.5);
    cursor: pointer;
    transition: background 80ms ease;
  }

  .l2-row:hover {
    background: #22232a !important;
  }

  .l2-row--alt {
    background: rgba(34, 35, 42, 0.3);
  }

  /* ── Cells — identical to L1 ct2-cell ── */

  .l2-cell {
    padding: 12px 16px;
    font-family: "Urbanist", sans-serif;
    font-size: 0.9375rem;
    color: #cbccd1;
    vertical-align: middle;
  }

  .l2-cell--name {
    padding-left: 24px;
    color: #fff;
    font-weight: 600;
    font-size: 1rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 420px;
  }

  .l2-cell--ticker {
    padding: 12px 16px;
  }

  .l2-ticker-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.05);
    color: #a1a1aa;
    font-family: "Geist Mono", monospace;
    font-size: 0.875rem;
    font-weight: 500;
    letter-spacing: 0.02em;
  }

  .l2-muted {
    color: #71717a;
  }

  .l2-cell--type {
    padding: 12px 16px;
  }

  .l2-type-badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.04em;
    border: 1px solid;
    white-space: nowrap;
  }

  .l2-cell--strategy {
    color: #cbccd1;
    font-size: 0.9375rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 180px;
  }

  .l2-cell--aum {
    text-align: right;
    padding-right: 48px;
    font-family: "Geist Mono", monospace;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: #fafafa;
    font-size: 0.9375rem;
  }

  .l2-cell--actions {
    text-align: right;
    padding-right: 16px;
    white-space: nowrap;
  }

  .l2-action-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: #71717a;
    cursor: pointer;
    transition: color 100ms ease, background 100ms ease;
  }

  .l2-action-btn:hover {
    color: #fafafa;
    background: rgba(255, 255, 255, 0.06);
  }

  /* ── Footer — matches L1 ct2-pagination ── */

  .l2-footer {
    flex-shrink: 0;
    padding: 12px 24px;
    font-size: 0.75rem;
    color: #71717a;
    border-top: 1px solid #2a2b33;
    font-family: "Urbanist", sans-serif;
    font-variant-numeric: tabular-nums;
  }

  /* ── DD Confirm Dialog ── */

  .l2-dialog {
    position: relative;
    background: #1a1b20;
    border: 1px solid #2a2b33;
    border-radius: 16px;
    padding: 24px;
    width: 100%;
    max-width: 28rem;
    box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5);
    z-index: 10;
  }

  .l2-dialog-title {
    font-size: 1.125rem;
    font-weight: 700;
    color: #fafafa;
    margin: 0 0 8px;
  }

  .l2-dialog-body {
    font-size: 0.875rem;
    color: #71717a;
    margin: 0 0 16px;
  }

  .l2-dialog-actions {
    display: flex;
    justify-content: flex-end;
    gap: 12px;
  }

  .l2-dialog-cancel {
    padding: 8px 16px;
    border-radius: 8px;
    border: 1px solid #3a3b44;
    background: transparent;
    color: #a1a1aa;
    font-size: 0.875rem;
    cursor: pointer;
  }

  .l2-dialog-confirm {
    padding: 8px 16px;
    border-radius: 8px;
    background: #0177fb;
    color: white;
    font-size: 0.875rem;
    font-weight: 500;
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .l2-dialog-confirm:disabled,
  .l2-dialog-cancel:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
