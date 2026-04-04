<!--
  ManagerDetailPanel — Level 2 Sheet (80vw).
  Slides in from right with manager header + flat fund table.
  Funds fetched async from /screener/catalog?manager_id={crd}.
  ALL styles use Tailwind or inline — no scoped <style> (portal compat).
-->
<script lang="ts">
  import { getContext } from "svelte";
  import * as Sheet from "@investintell/ui/components/ui/sheet";
  import { goto } from "$app/navigation";
  import { ExternalLink, Loader2, Sparkles } from "lucide-svelte";
  import { formatAUM } from "@investintell/ui";
  import { createClientApiClient } from "$lib/api/client";
  import type { UnifiedFundItem, UnifiedCatalogPage, ManagerCatalogItem } from "$lib/types/catalog";
  import { FUND_TYPE_BADGE_MAP } from "$lib/types/catalog";

  interface Props {
    open?: boolean;
    manager?: ManagerCatalogItem | null;
  }

  let { open = $bindable(false), manager = null }: Props = $props();

  const getToken = getContext<() => Promise<string>>("netz:getToken");
  const api = createClientApiClient(getToken);

  let fundItems = $state<UnifiedFundItem[]>([]);
  let isLoadingFunds = $state(false);
  let totalFunds = $state(0);

  $effect(() => {
    if (open && manager?.manager_id) {
      fetchFunds(manager.manager_id);
    }
  });

  async function fetchFunds(crd: string) {
    isLoadingFunds = true;
    try {
      const result = await api.get<UnifiedCatalogPage>("/screener/catalog", {
        manager_id: crd,
        has_nav: "false",
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
    open = false;
    goto(`/screener/fund/${fund.external_id}`);
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
      open = false;
      ddConfirmFund = null;
      goto(`/screener/dd-reports/${result.instrument_id}/${result.id}`);
    } catch {
      ddGenerating = false;
    }
  }

  /** Badge inline styles (hardcoded for portal compat — no scoped CSS) */
  const BADGE_COLORS: Record<string, string> = {
    "badge-mf": "color:#60a5fa;background:rgba(96,165,250,0.12);border-color:rgba(96,165,250,0.25)",
    "badge-etf": "color:#22d3ee;background:rgba(34,211,238,0.12);border-color:rgba(34,211,238,0.25)",
    "badge-cef": "color:#818cf8;background:rgba(129,140,248,0.12);border-color:rgba(129,140,248,0.25)",
    "badge-bdc": "color:#fbbf24;background:rgba(251,191,36,0.12);border-color:rgba(251,191,36,0.25)",
    "badge-mmf": "color:#94a3b8;background:rgba(148,163,184,0.12);border-color:rgba(148,163,184,0.25)",
    "badge-hf": "color:#c084fc;background:rgba(192,132,252,0.12);border-color:rgba(192,132,252,0.25)",
    "badge-pe": "color:#34d399;background:rgba(52,211,153,0.12);border-color:rgba(52,211,153,0.25)",
    "badge-vc": "color:#fb923c;background:rgba(251,146,60,0.12);border-color:rgba(251,146,60,0.25)",
    "badge-re": "color:#2dd4bf;background:rgba(45,212,191,0.12);border-color:rgba(45,212,191,0.25)",
    "badge-sa": "color:#f472b6;background:rgba(244,114,182,0.12);border-color:rgba(244,114,182,0.25)",
    "badge-lf": "color:#67e8f9;background:rgba(103,232,249,0.12);border-color:rgba(103,232,249,0.25)",
    "badge-pf": "color:#f87171;background:rgba(248,113,113,0.12);border-color:rgba(248,113,113,0.25)",
    "badge-ucits": "color:#a78bfa;background:rgba(167,139,250,0.12);border-color:rgba(167,139,250,0.25)",
    "badge-default": "color:#a1a1aa;background:rgba(161,161,170,0.08);border-color:rgba(161,161,170,0.15)",
  };

  function badgeStyle(colorClass: string): string {
    return BADGE_COLORS[colorClass] ?? "color:#a1a1aa;background:rgba(161,161,170,0.08);border-color:rgba(161,161,170,0.15)";
  }
</script>

<Sheet.Root bind:open>
  <Sheet.Content
    side="right"
    class="!w-[80vw] !max-w-[80vw] !gap-0 !p-0 flex flex-col overflow-hidden"
    style="width:80vw!important;max-width:80vw!important;background:#111215!important;color:#fafafa!important;border-left:1px solid rgba(255,255,255,0.1)"
  >
    {#if manager}
      <!-- ── Header ── -->
      <div style="padding:32px 40px 24px;border-bottom:1px solid rgba(255,255,255,0.06);flex-shrink:0">
        <div style="margin-bottom:12px">
          <Sheet.Title style="font-size:1.75rem;font-weight:700;letter-spacing:-0.02em;color:#fafafa;font-family:Urbanist,sans-serif">
            {formatName(manager.manager_name)}
          </Sheet.Title>
          <Sheet.Description style="display:flex;align-items:center;gap:8px;margin-top:6px;font-size:0.8125rem;color:#71717a;font-family:Urbanist,sans-serif">
            <span style="font-family:'Geist Mono',monospace">CRD: {manager.manager_id}</span>
            <span style="width:4px;height:4px;border-radius:50%;background:#3a3b44;flex-shrink:0"></span>
            <span>{manager.fund_count} fund{manager.fund_count !== 1 ? "s" : ""}</span>
            {#if manager.total_aum != null}
              <span style="width:4px;height:4px;border-radius:50%;background:#3a3b44;flex-shrink:0"></span>
              <span>AUM: {formatAUM(manager.total_aum)}</span>
            {/if}
            {#if manager.state || manager.country}
              <span style="width:4px;height:4px;border-radius:50%;background:#3a3b44;flex-shrink:0"></span>
              <span>{manager.state ?? ""}{manager.state && manager.country ? ", " : ""}{manager.country ?? ""}</span>
            {/if}
          </Sheet.Description>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          {#each manager.fund_types ?? [] as ft}
            {@const b = badgeFor(ft)}
            <span
              style="display:inline-flex;align-items:center;padding:3px 10px;border-radius:999px;font-size:10px;font-weight:700;letter-spacing:0.04em;border:1px solid;{badgeStyle(b.colorClass)}"
            >{b.label}</span>
          {/each}
        </div>
      </div>

      <!-- ── Fund Table ── -->
      <div style="flex:1;overflow-y:auto">
        {#if isLoadingFunds}
          <div style="display:flex;align-items:center;justify-content:center;gap:10px;padding:64px 24px;color:#71717a;font-size:0.875rem">
            <Loader2 class="animate-spin text-primary" size={24} />
            <span>Loading funds...</span>
          </div>
        {:else if fundItems.length === 0}
          <div style="padding:64px 24px;text-align:center;color:#71717a;font-size:0.875rem">
            No fund data available for this manager.
          </div>
        {:else}
          <div style="overflow-x:auto">
            <table style="width:100%;border-collapse:collapse">
              <thead>
                <tr style="border-bottom:1px solid rgba(255,255,255,0.08)">
                  <th style="color:#71717a;font-size:0.6875rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;height:44px;padding:0 16px 0 40px;text-align:left;font-family:Urbanist,sans-serif">Fund Name</th>
                  <th style="color:#71717a;font-size:0.6875rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;height:44px;padding:0 16px;text-align:left;font-family:Urbanist,sans-serif;width:100px">Ticker</th>
                  <th style="color:#71717a;font-size:0.6875rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;height:44px;padding:0 16px;text-align:left;font-family:Urbanist,sans-serif;width:80px">Type</th>
                  <th style="color:#71717a;font-size:0.6875rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;height:44px;padding:0 16px;text-align:left;font-family:Urbanist,sans-serif;width:160px">Strategy</th>
                  <th style="color:#71717a;font-size:0.6875rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;height:44px;padding:0 16px;text-align:right;font-family:Urbanist,sans-serif;width:140px">GAV / AUM</th>
                  <th style="width:80px"></th>
                </tr>
              </thead>
              <tbody>
                {#each fundItems as fund, i (fund.external_id)}
                  <!-- svelte-ignore a11y_click_events_have_key_events -->
                  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
                  <tr
                    style="border-bottom:1px solid rgba(255,255,255,0.04);cursor:pointer;{i % 2 === 1 ? 'background:rgba(255,255,255,0.015)' : ''}"
                    onmouseenter={(e) => (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.04)'}
                    onmouseleave={(e) => (e.currentTarget as HTMLElement).style.background = i % 2 === 1 ? 'rgba(255,255,255,0.015)' : ''}
                    onclick={() => openFactSheet(fund)}
                  >
                    <td style="padding:12px 16px 12px 40px;font-family:Urbanist,sans-serif;font-size:0.8125rem;vertical-align:middle">
                      <span style="color:#fafafa;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block;max-width:400px">{fund.name}</span>
                    </td>
                    <td style="padding:12px 16px;font-size:0.8125rem;vertical-align:middle">
                      {#if fund.ticker}
                        <span style="font-family:'Geist Mono',monospace;font-size:0.75rem;color:#a1a1aa">{fund.ticker}</span>
                      {:else}
                        <span style="color:#71717a;font-size:0.75rem">Private</span>
                      {/if}
                    </td>
                    <td style="padding:12px 16px;vertical-align:middle">
                      <span style="display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;font-size:10px;font-weight:700;letter-spacing:0.04em;border:1px solid;{badgeStyle(badgeFor(fund.fund_type).colorClass)}">{badgeFor(fund.fund_type).label}</span>
                    </td>
                    <td style="padding:12px 16px;font-family:Urbanist,sans-serif;font-size:0.8125rem;color:#a1a1aa;vertical-align:middle;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px">
                      {fund.strategy_label ?? "\u2014"}
                    </td>
                    <td style="padding:12px 16px;text-align:right;font-family:'Geist Mono',monospace;font-weight:600;font-variant-numeric:tabular-nums;color:#fafafa;font-size:0.8125rem;vertical-align:middle">
                      {fund.aum != null ? formatAUM(fund.aum) : "\u2014"}
                    </td>
                    <td style="padding:12px 16px;text-align:right;vertical-align:middle">
                      <button
                        style="display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border:none;border-radius:6px;background:transparent;color:#71717a;cursor:pointer"
                        title="Generate DD Report"
                        onclick={(e: MouseEvent) => { e.stopPropagation(); promptDD(fund); }}
                      >
                        <Sparkles size={14} />
                      </button>
                      <button
                        style="display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border:none;border-radius:6px;background:transparent;color:#71717a;cursor:pointer"
                        title="View Fact Sheet"
                        onclick={(e: MouseEvent) => { e.stopPropagation(); openFactSheet(fund); }}
                      >
                        <ExternalLink size={14} />
                      </button>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
          <div style="padding:12px 40px;font-size:0.75rem;color:#71717a;border-top:1px solid rgba(255,255,255,0.06)">
            {totalFunds} fund{totalFunds !== 1 ? "s" : ""}
          </div>
        {/if}
      </div>
    {/if}
  </Sheet.Content>
</Sheet.Root>

<!-- ── DD Confirmation Dialog ── -->
{#if ddConfirmFund}
  <div class="fixed inset-0 z-[60] flex items-center justify-center">
    <div class="absolute inset-0 bg-black/50 backdrop-blur-sm" onclick={cancelDD} role="presentation"></div>
    <div style="position:relative;background:#1a1b20;border:1px solid #2a2b33;border-radius:16px;padding:24px;width:100%;max-width:28rem;box-shadow:0 25px 50px -12px rgba(0,0,0,0.5);z-index:10">
      <h3 style="font-size:1.125rem;font-weight:700;color:#fafafa;margin-bottom:8px">Generate DD Report</h3>
      <p style="font-size:0.875rem;color:#71717a;margin-bottom:16px">
        Generate an 8-chapter Due Diligence report for
        <strong style="color:#fafafa">{ddConfirmFund.name}</strong>?
        This is a high-stakes operation (~26k tokens, ~2 minutes).
      </p>
      <div style="display:flex;justify-content:flex-end;gap:12px">
        <button
          style="padding:8px 16px;border-radius:8px;border:1px solid #3a3b44;background:transparent;color:#a1a1aa;font-size:0.875rem;cursor:pointer"
          onclick={cancelDD}
          disabled={ddGenerating}
        >
          Cancel
        </button>
        <button
          style="padding:8px 16px;border-radius:8px;background:#0177fb;color:white;font-size:0.875rem;font-weight:500;border:none;cursor:pointer;display:flex;align-items:center;gap:6px"
          onclick={confirmDD}
          disabled={ddGenerating}
        >
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
