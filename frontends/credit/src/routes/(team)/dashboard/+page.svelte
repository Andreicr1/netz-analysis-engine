<!--
  Dashboard — three-tier layout:
  Tier 1 (Command): TaskInbox + alert counts
  Tier 2 (Analytical): PipelineFunnel + AUM DataCards + AI confidence
  Tier 3 (Operational): Risk/return scatter + macro sparklines + activity feed
-->
<script lang="ts">
  import {
    DataCard,
    StatusBadge,
    EmptyState,
    FunnelChart,
    ScatterChart,
    TimeSeriesChart,
  } from "@netz/ui";
  import TaskInbox from "$lib/components/TaskInbox.svelte";
  import PipelineFunnel from "$lib/components/PipelineFunnel.svelte";
  import { createClientApiClient } from "$lib/api/client";
  import { getContext } from "svelte";
  import type { PageData } from "./$types";
  import type {
    PortfolioSummary,
    PipelineSummary,
    PipelineAnalytics,
    MacroSnapshot,
    TaskItem,
  } from "$lib/types/api";

  const getToken = getContext<() => Promise<string>>("netz:getToken");

  type Trend = "up" | "down" | "flat";

  let { data }: { data: PageData } = $props();

  let portfolio = $derived(data.portfolioSummary as PortfolioSummary | null);
  let pipeline = $derived(data.pipelineSummary as PipelineSummary | null);
  let analytics = $derived(data.pipelineAnalytics as PipelineAnalytics | null);
  let macro = $derived(data.macroSnapshot as MacroSnapshot | null);

  // ── FRED Explorer ──
  let fredSearch = $state("");
  let fredSearching = $state(false);
  let fredResults = $state<Array<{ id: string; title: string }>>([]);
  let selectedFredSeries = $state<string[]>([]);
  let fredChartData = $state<Record<string, unknown[]> | null>(null);
  let fredSearchTimer: ReturnType<typeof setTimeout> | undefined;
  let fredSearchSeq = 0;

  function debounceFredSearch() {
    clearTimeout(fredSearchTimer);
    fredSearchTimer = setTimeout(() => searchFred(), 300);
  }

  async function searchFred() {
    const q = fredSearch.trim();
    if (q.length < 2) { fredResults = []; return; }

    const seq = ++fredSearchSeq;
    fredSearching = true;
    try {
      const api = createClientApiClient(getToken);
      const res = await api.get<{ series: Array<{ id: string; title: string }> }>(`/dashboard/fred-search`, { q });
      if (seq === fredSearchSeq) {
        fredResults = res.series ?? [];
      }
    } catch {
      if (seq === fredSearchSeq) {
        fredResults = [];
      }
    } finally {
      if (seq === fredSearchSeq) {
        fredSearching = false;
      }
    }
  }

  async function toggleFredSeries(id: string) {
    if (selectedFredSeries.includes(id)) {
      selectedFredSeries = selectedFredSeries.filter(s => s !== id);
    } else if (selectedFredSeries.length < 4) {
      selectedFredSeries = [...selectedFredSeries, id];
    }
    await loadFredData();
  }

  async function loadFredData() {
    if (selectedFredSeries.length === 0) { fredChartData = null; return; }
    try {
      const api = createClientApiClient(getToken);
      if (selectedFredSeries.length === 1) {
        const res = await api.get<Record<string, unknown>>(`/dashboard/macro-fred-series`, {
          series_id: selectedFredSeries[0],
          period: "6m",
        });
        fredChartData = { [selectedFredSeries[0]]: (res.observations as unknown[]) ?? [] };
      } else {
        const res = await api.get<Record<string, unknown>>(`/dashboard/macro-fred-multi`, {
          series_ids: selectedFredSeries.join(","),
        });
        fredChartData = (res.series as Record<string, unknown[]>) ?? {};
      }
    } catch {
      fredChartData = null;
    }
  }
</script>

<div class="space-y-6 p-6">
  <!-- Tier 1: Command -->
  <section>
    <h2 class="mb-4 text-lg font-semibold text-[var(--netz-text-primary)]">
      Action Queue
    </h2>
    {#if data.taskInbox}
      <div class="mt-4">
        <TaskInbox tasks={data.taskInbox as TaskItem[]} />
      </div>
    {/if}

    <div class="mt-4 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      <DataCard
        label="Deals Awaiting IC"
        value={String(pipeline?.pending_ic ?? 0)}
        trend={(pipeline?.pending_ic_trend ?? "flat") as Trend}
      />
      <DataCard
        label="Documents Pending Review"
        value={String(pipeline?.docs_pending ?? 0)}
        trend="flat"
      />
      <DataCard
        label="Overdue Obligations"
        value={String(portfolio?.overdue_count ?? 0)}
        trend={Number(portfolio?.overdue_count ?? 0) > 0 ? "down" : "flat"}
      />
      <DataCard
        label="Compliance Alerts"
        value={String((data.complianceAlerts as string[] | null)?.length ?? 0)}
        trend="flat"
      />
    </div>
  </section>

  <!-- Tier 2: Analytical -->
  <section>
    <h2 class="mb-4 text-lg font-semibold text-[var(--netz-text-primary)]">
      Pipeline & Portfolio
    </h2>
    <div class="grid gap-4 lg:grid-cols-3">
      <div class="lg:col-span-1">
        {#if analytics}
          <PipelineFunnel data={analytics} />
        {:else}
          <EmptyState
            title="No Pipeline Data"
            description="Pipeline analytics will appear here."
          />
        {/if}
      </div>
      <div class="grid gap-4 lg:col-span-2 lg:grid-cols-2">
        <DataCard
          label="Total AUM"
          value={String(portfolio?.total_aum ?? "—")}
          trend={(portfolio?.aum_trend ?? "flat") as Trend}
        />
        <DataCard
          label="Active Loans"
          value={String(portfolio?.active_count ?? 0)}
          trend="flat"
        />
        <DataCard
          label="AI-Ready Deals"
          value={String(pipeline?.ai_ready ?? 0)}
          trend="up"
        />
        <DataCard
          label="Converted QTD"
          value={String(pipeline?.converted_qtd ?? 0)}
          trend="up"
        />
      </div>
    </div>
  </section>

  <!-- Tier 3: Operational -->
  <section>
    <h2 class="mb-4 text-lg font-semibold text-[var(--netz-text-primary)]">
      Market & Activity
    </h2>
    <div class="grid gap-4 lg:grid-cols-2">
      {#if macro}
        <div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface)] p-4">
          <h3
            class="mb-3 text-sm font-medium text-[var(--netz-text-secondary)]"
          >
            Macro Indicators
          </h3>
          <div class="grid grid-cols-2 gap-3">
            <DataCard
              label="10Y Treasury"
              value={String(macro.treasury10y ?? "—")}
              trend="flat"
            />
            <DataCard
              label="BAA Spread"
              value={String(macro.baaSpread ?? "—")}
              trend="flat"
            />
            <DataCard
              label="Yield Curve"
              value={String(macro.yieldCurve ?? "—")}
              trend="flat"
            />
            <DataCard
              label="CPI YoY"
              value={String(macro.cpiYoy ?? "—")}
              trend="flat"
            />
          </div>
        </div>
      {:else}
        <EmptyState
          title="No Macro Data"
          description="FRED macro data will appear here once available."
        />
      {/if}
      <div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface)] p-4">
        <h3 class="mb-3 text-sm font-medium text-[var(--netz-text-secondary)]">
          FRED Explorer
        </h3>
        <div class="space-y-3">
          <div class="flex gap-2">
            <input
              type="text"
              bind:value={fredSearch}
              placeholder="Search FRED series (e.g. GDP, CPI, FEDFUNDS)..."
              class="flex-1 rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-1.5 text-sm text-[var(--netz-text-primary)]"
              oninput={debounceFredSearch}
            />
          </div>
          {#if fredSearching}
            <p class="text-xs text-[var(--netz-text-muted)]">Searching...</p>
          {/if}
          {#if fredResults.length > 0}
            <div class="max-h-48 space-y-1 overflow-y-auto">
              {#each fredResults as series}
                <button
                  class="w-full rounded px-2 py-1.5 text-left text-xs hover:bg-[var(--netz-bg-hover)] {selectedFredSeries.includes(series.id) ? 'bg-[var(--netz-brand-primary)]/10 font-medium' : ''}"
                  onclick={() => toggleFredSeries(series.id)}
                >
                  <span class="font-mono">{series.id}</span> — {series.title}
                </button>
              {/each}
            </div>
          {/if}
          {#if selectedFredSeries.length > 0}
            <div class="flex flex-wrap gap-1">
              {#each selectedFredSeries as id}
                <span class="inline-flex items-center gap-1 rounded-full bg-[var(--netz-brand-primary)]/10 px-2 py-0.5 text-xs text-[var(--netz-brand-primary)]">
                  {id}
                  <button onclick={() => selectedFredSeries = selectedFredSeries.filter(s => s !== id)}>&times;</button>
                </span>
              {/each}
            </div>
            {#if fredChartData}
              <div class="rounded border border-[var(--netz-border)] p-3">
                <p class="mb-2 text-xs font-medium text-[var(--netz-text-secondary)]">
                  {selectedFredSeries.join(", ")} — Last 30 observations
                </p>
                <div class="space-y-1">
                  {#each Object.entries(fredChartData) as [seriesId, observations]}
                    <div class="flex items-center gap-2 text-xs">
                      <span class="w-24 font-mono">{seriesId}</span>
                      <span class="text-[var(--netz-text-muted)]">
                        Latest: {Array.isArray(observations) && observations.length > 0 ? (observations[observations.length - 1] as Record<string, string>)?.value ?? "—" : "—"}
                      </span>
                    </div>
                  {/each}
                </div>
              </div>
            {/if}
          {/if}
        </div>
      </div>
    </div>
  </section>
</div>
