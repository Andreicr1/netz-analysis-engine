<!--
  Analytics — Correlações + Backtest & Walk-Forward + Pareto Frontier + What-If + Atribuição
  Figma frame "Correlações + Pareto frontier" (node 1:2)
-->
<script lang="ts">
  import {
    Badge,
    PageHeader,
    PageTabs,
    SectionCard,
    MetricCard,
    EmptyState,
    HeatmapChart,
    ChartContainer,
    Button,
    Input,
    Select,
    formatNumber,
    formatPercent,
  } from "@netz/ui";
  import type { PageData } from "./$types";
  import { createClientApiClient } from "$lib/api/client";
  import { getContext } from "svelte";
  import { goto } from "$app/navigation";

  const getToken = getContext<() => Promise<string>>("netz:getToken");

  let { data }: { data: PageData } = $props();

  // ── Types ────────────────────────────────────────────────────────────────

  type CorrelationMatrix = {
    matrix: number[][];
    labels: string[];
    stats?: {
      sharpe_ratio?: number | null;
      avg_correlation?: number | null;
      effective_n?: number | null;
      max_pair_correlation?: number | null;
      max_pair_names?: [string, string] | null;
      min_pair_correlation?: number | null;
      min_pair_names?: [string, string] | null;
      benchmark_correlation?: number | null;
    };
  };

  type CorrelationRegime = {
    profile: string;
    points: {
      fund_name: string;
      cvar_pct: number;
      return_pct: number;
      is_portfolio?: boolean;
    }[];
    frontier: { cvar_pct: number; return_pct: number }[];
  };

  // ── Server data ──────────────────────────────────────────────────────────

  let correlation = $derived(data.correlation as CorrelationMatrix | null);
  let correlationRegime = $derived(
    data.correlationRegime as CorrelationRegime | null,
  );

  // ── Filters ──────────────────────────────────────────────────────────────

  const PROFILES = [
    { value: "conservative", label: "Conservative" },
    { value: "moderate", label: "Moderate" },
    { value: "growth", label: "Growth" },
  ];

  // svelte-ignore state_referenced_locally
  let selectedPortfolio = $state((data.profile as string) ?? "moderate");
  let dateFrom = $state("");
  let dateTo = $state("");

  function applyPortfolioFilter(profile: string) {
    selectedPortfolio = profile;
    goto(`?portfolio=${profile}`, { replaceState: true, invalidateAll: true });
  }

  // ── Tabs ─────────────────────────────────────────────────────────────────

  const TABS = [
    { value: "correlacoes", label: "Correlations" },
    { value: "backtest", label: "Backtest & Walk-Forward" },
    { value: "pareto", label: "Pareto Frontier" },
    { value: "whatif", label: "What-If Scenarios" },
    { value: "atribuicao", label: "Performance Attribution" },
  ];

  // ── Correlações KPIs ────────────────────────────────────────────────────

  let stats = $derived(correlation?.stats ?? null);

  function fmtNum(v: number | null | undefined, decimals = 2): string {
    return formatNumber(v, decimals, "en-US");
  }

  function fmtPct(v: number | null | undefined): string {
    return formatPercent(v, 1, "en-US");
  }

  const analysisLensSubtitle = $derived.by(() => {
    if (dateFrom && dateTo) return `${dateFrom} - ${dateTo}`;
    if (dateFrom) return `From ${dateFrom}`;
    if (dateTo) return `Until ${dateTo}`;
    return "Consolidated monthly returns";
  });

  const highCorrelationNote = $derived.by(() => {
    if (
      !stats?.max_pair_names ||
      stats.max_pair_correlation == null ||
      stats.max_pair_correlation < 0.7
    )
      return null;
    return `${stats.max_pair_names.join(" ↔ ")} at ${fmtNum(stats.max_pair_correlation)} suggests elevated overlap.`;
  });

  // ── Heatmap data ─────────────────────────────────────────────────────────

  let heatmapData = $derived(
    correlation
      ? {
          matrix: correlation.matrix,
          xLabels: correlation.labels,
          yLabels: correlation.labels,
        }
      : null,
  );

  // ── Pareto Frontier chart (multi-series via ChartContainer) ──────────────

  let paretoOption = $derived.by(() => {
    const fundPoints = (correlationRegime?.points ?? [])
      .filter((p) => !p.is_portfolio)
      .map((p) => ({ value: [p.cvar_pct, p.return_pct], name: p.fund_name }));

    const portfolioPoints = (correlationRegime?.points ?? [])
      .filter((p) => p.is_portfolio)
      .map((p) => ({ value: [p.cvar_pct, p.return_pct], name: p.fund_name }));

    const frontierLine = (correlationRegime?.frontier ?? []).map(
      (p) => [p.cvar_pct, p.return_pct] as [number, number],
    );

    const hasFrontier = frontierLine.length > 0;

    return {
      tooltip: {
        trigger: "item",
        formatter: (params: {
          seriesName?: string;
          name?: string;
          value: [number, number];
        }) => {
          const label = params.name
            ? `<strong>${params.name}</strong><br/>`
            : "";
          return `${label}CVaR: ${formatNumber(params.value[0], 2, "en-US")}%<br/>Return: ${formatNumber(params.value[1], 2, "en-US")}%`;
        },
      },
      legend: {
        bottom: 0,
        textStyle: { fontSize: 11 },
        data: [
          "Funds",
          "Portfolios",
          ...(hasFrontier ? ["Efficient Frontier"] : []),
        ],
      },
      grid: { left: 60, right: 20, top: 20, bottom: 50 },
      xAxis: {
        type: "value",
        name: "Risk (CVaR %)",
        nameLocation: "middle",
        nameGap: 32,
        axisLabel: { fontSize: 11, formatter: (v: number) => `${v}%` },
      },
      yAxis: {
        type: "value",
        name: "Return (%)",
        nameLocation: "middle",
        nameGap: 48,
        axisLabel: { fontSize: 11, formatter: (v: number) => `${v}%` },
      },
      series: [
        {
          name: "Funds",
          type: "scatter",
          data: fundPoints,
          symbolSize: 10,
          itemStyle: { color: "var(--netz-brand-primary)" },
        },
        {
          name: "Portfolios",
          type: "scatter",
          data: portfolioPoints,
          symbolSize: 14,
          symbol: "diamond",
          itemStyle: { color: "var(--netz-warning)" },
        },
        ...(hasFrontier
          ? [
              {
                name: "Efficient Frontier",
                type: "line",
                data: frontierLine,
                lineStyle: {
                  type: "dashed",
                  color: "var(--netz-brand-secondary, #60A5FA)",
                  width: 2,
                },
                itemStyle: { color: "var(--netz-brand-secondary, #60A5FA)" },
                showSymbol: false,
              },
            ]
          : []),
      ],
    } as Record<string, unknown>;
  });

  // ── Backtest state (with polling for pending results) ─────────────────────

  let backtestRunning = $state(false);
  let backtestResult = $state<Record<string, unknown> | null>(null);
  let backtestError = $state<string | null>(null);
  let backtestPollStop: (() => void) | null = null;

  async function triggerBacktest() {
    backtestRunning = true;
    backtestResult = null;
    backtestError = null;
    try {
      const api = createClientApiClient(getToken);
      const result = (await api.post("/analytics/backtest", {
        profile: selectedPortfolio,
      })) as Record<string, unknown>;

      // If pending, poll for results using createPoller (auto-cleanup on unmount)
      if (result.status === "pending" && result.run_id) {
        const runId = String(result.run_id);
        pollBacktestResult(runId);
      } else {
        backtestResult = result;
        backtestRunning = false;
      }
    } catch (e) {
      backtestError = e instanceof Error ? e.message : "Backtest failed";
      backtestRunning = false;
    }
  }

  function pollBacktestResult(runId: string) {
    const api = createClientApiClient(getToken);
    let stopped = false;

    backtestPollStop = () => {
      stopped = true;
    };

    (async () => {
      const maxAttempts = 12; // 60s total (5s x 12)
      for (let i = 0; i < maxAttempts; i++) {
        if (stopped) return;
        await new Promise((r) => setTimeout(r, 5000));
        if (stopped) return;
        try {
          const result = await api.get<Record<string, unknown>>(
            `/analytics/backtest/${runId}`,
          );
          if (result.status !== "pending") {
            backtestResult = result;
            backtestRunning = false;
            return;
          }
        } catch {
          break;
        }
      }
      backtestError = "Backtest timed out. Check back later.";
      backtestRunning = false;
    })();
  }

  // Cleanup polling on component destroy
  $effect(() => {
    return () => {
      backtestPollStop?.();
    };
  });

  // ── Optimization state ────────────────────────────────────────────────────

  let optimizationRunning = $state(false);
  let optimizationError = $state<string | null>(null);

  async function runOptimization() {
    optimizationRunning = true;
    optimizationError = null;
    try {
      const api = createClientApiClient(getToken);
      await api.post("/analytics/optimize", { profile: selectedPortfolio });
      goto(`?portfolio=${selectedPortfolio}`, {
        replaceState: true,
        invalidateAll: true,
      });
    } catch (e) {
      optimizationError =
        e instanceof Error ? e.message : "Optimization failed";
    } finally {
      optimizationRunning = false;
    }
  }

  // ── Pareto optimization (180s timeout, duplicate prevention) ──────────────

  let paretoRunning = $state(false);
  let paretoError = $state<string | null>(null);

  async function runPareto() {
    if (paretoRunning) return; // prevent duplicate
    paretoRunning = true;
    paretoError = null;
    try {
      const api = createClientApiClient(getToken);
      await api.post(
        "/analytics/optimize/pareto",
        { profile: selectedPortfolio },
        { timeoutMs: 180_000 },
      );
      goto(`?portfolio=${selectedPortfolio}`, {
        replaceState: true,
        invalidateAll: true,
      });
    } catch (e) {
      if (e instanceof Error && e.message.includes("429")) {
        paretoError = "Server at capacity. Please try again in a few minutes.";
      } else if (e instanceof Error && e.message.includes("timeout")) {
        paretoError =
          "Optimization timed out. The server may still be processing.";
      } else {
        paretoError =
          e instanceof Error ? e.message : "Pareto optimization failed";
      }
    } finally {
      paretoRunning = false;
    }
  }

  // ── Pair correlation drill-down ──────────────────────────────────────────

  let pairDetail = $state<Record<string, unknown> | null>(null);
  let pairLoading = $state(false);
  let showPairPanel = $derived(pairDetail !== null);

  async function loadPairCorrelation(instA: string, instB: string) {
    pairLoading = true;
    try {
      const api = createClientApiClient(getToken);
      pairDetail = await api.get(
        `/analytics/correlation-regime/${selectedPortfolio}/pair/${encodeURIComponent(instA)}/${encodeURIComponent(instB)}`,
      );
    } catch {
      pairDetail = null;
    } finally {
      pairLoading = false;
    }
  }

  // ── Attribution ──────────────────────────────────────────────────────────

  let attributionData = $state<Record<string, unknown> | null>(null);
  let attributionLoading = $state(false);
  let attributionLoaded = $state(false);
  let selectedFundId = $state("");

  async function loadAttribution() {
    if (!selectedFundId || attributionLoading) return;
    attributionLoading = true;
    try {
      const api = createClientApiClient(getToken);
      attributionData = await api.get(
        `/analytics/attribution/${selectedPortfolio}`,
      );
      attributionLoaded = true;
    } catch {
      attributionData = null;
    } finally {
      attributionLoading = false;
    }
  }
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
  <!-- Page Header -->
  <PageHeader title="Analytics">
    {#snippet actions()}
      <Badge variant="secondary"
        >{PROFILES.find((profile) => profile.value === selectedPortfolio)
          ?.label ?? "Moderate"}</Badge
      >
    {/snippet}
  </PageHeader>
  <p class="mt-1 text-sm text-(--netz-text-muted)">
    Cross-portfolio diagnostics for correlation, optimization, and attribution
    review.
  </p>

  <SectionCard title="Analysis Lens" subtitle={analysisLensSubtitle}>
    <div
      class="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_auto_minmax(0,1fr)]"
    >
      <div class="space-y-1.5">
        <p
          class="text-[11px] font-semibold uppercase tracking-[0.08em] text-(--netz-text-muted)"
        >
          Portfolio
        </p>
        <Select
          bind:value={selectedPortfolio}
          options={PROFILES}
          placeholder="Portfolio"
          onValueChange={applyPortfolioFilter}
        />
      </div>
      <div class="space-y-1.5">
        <p
          class="text-[11px] font-semibold uppercase tracking-[0.08em] text-(--netz-text-muted)"
        >
          From
        </p>
        <Input type="date" bind:value={dateFrom} aria-label="Start date" />
      </div>
      <div
        class="hidden items-end justify-center text-sm text-(--netz-text-muted) lg:flex"
      >
        to
      </div>
      <div class="space-y-1.5">
        <p
          class="text-[11px] font-semibold uppercase tracking-[0.08em] text-(--netz-text-muted)"
        >
          To
        </p>
        <Input type="date" bind:value={dateTo} aria-label="End date" />
      </div>
    </div>
    <div
      class="mt-4 flex flex-wrap items-center gap-2 text-sm text-(--netz-text-muted)"
    >
      <span>Tabs persist in the URL for review continuity.</span>
      <span
        class="hidden h-1 w-1 rounded-full bg-(--netz-text-muted) sm:inline-block"
      ></span>
      <span
        >Use the Pareto tab when committee discussion moves from diagnostics to
        positioning.</span
      >
    </div>
  </SectionCard>

  <!-- 5-tab navigation -->
  <PageTabs tabs={TABS} defaultTab="correlacoes">
    {#snippet children(activeTab)}
      <!-- ═══════════════════════════════════════════════════════════════
			     Tab: Correlações
			     ═══════════════════════════════════════════════════════════════ -->
      {#if activeTab === "correlacoes"}
        <div class="space-y-6">
          <!-- KPI row — 6 MetricCards -->
          <div class="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
            <MetricCard
              label="Sharpe Ratio"
              value={fmtNum(stats?.sharpe_ratio)}
              sublabel="Consolidated portfolio"
            />
            <MetricCard
              label="Average Correlation"
              value={fmtNum(stats?.avg_correlation)}
              sublabel="Across all pairs"
            />
            <MetricCard
              label="Effective Diversification"
              value={fmtNum(stats?.effective_n, 1)}
              sublabel="Effective number of assets"
            />
            <MetricCard
              label="Highest Pair Correlation"
              value={fmtNum(stats?.max_pair_correlation)}
              sublabel={stats?.max_pair_names
                ? stats.max_pair_names.join(" / ")
                : "—"}
              status={stats?.max_pair_correlation !== null &&
              stats?.max_pair_correlation !== undefined &&
              stats.max_pair_correlation > 0.85
                ? "warn"
                : undefined}
            />
            <MetricCard
              label="Lowest Pair Correlation"
              value={fmtNum(stats?.min_pair_correlation)}
              sublabel={stats?.min_pair_names
                ? stats.min_pair_names.join(" / ")
                : "—"}
            />
            <MetricCard
              label="Benchmark Corr."
              value={fmtPct(stats?.benchmark_correlation)}
              sublabel="vs. reference index"
            />
          </div>

          <!-- Heatmap -->
          <SectionCard
            title="Correlation Matrix"
            subtitle="Pearson correlation across monthly fund returns"
          >
            {#if heatmapData && heatmapData.matrix.length > 0}
              <div class="h-120">
                <HeatmapChart
                  matrix={heatmapData.matrix}
                  xLabels={heatmapData.xLabels}
                  yLabels={heatmapData.yLabels}
                  height={460}
                />
              </div>
            {:else}
              <EmptyState
                title="No correlation data"
                message="The correlation matrix will appear after historical NAV is available for at least 2 funds."
              />
            {/if}

            {#if highCorrelationNote}
              <div
                class="mt-4 rounded-(--netz-radius-md) border border-(--netz-warning) bg-(--netz-surface-highlight) px-4 py-3 text-sm text-(--netz-text-secondary)"
              >
                <span class="font-semibold text-(--netz-text-primary)"
                  >Attention:</span
                >
                {highCorrelationNote}
              </div>
            {/if}
          </SectionCard>
        </div>

        <!-- ═══════════════════════════════════════════════════════════════
			     Tab: Backtest & Walk-Forward
			     ═══════════════════════════════════════════════════════════════ -->
      {:else if activeTab === "backtest"}
        <div class="space-y-6">
          <SectionCard
            title="Backtest"
            subtitle="Run historical backtest for the selected profile"
          >
            <div class="flex items-center gap-3">
              <Button
                onclick={triggerBacktest}
                disabled={backtestRunning}
                size="sm"
              >
                {backtestRunning
                  ? "Running... (polling every 5s)"
                  : "Run Backtest"}
              </Button>
            </div>
            {#if backtestError}
              <div
                class="mt-4 rounded-(--netz-radius-md) border border-(--netz-status-error) bg-(--netz-surface-highlight) p-3 text-sm text-(--netz-status-error)"
              >
                {backtestError}
              </div>
            {/if}
            {#if backtestResult}
              <div
                class="mt-4 rounded-(--netz-radius-lg) border border-(--netz-border-subtle) bg-(--netz-surface-highlight) p-4 shadow-(--netz-shadow-1)"
              >
                <p class="text-sm text-(--netz-text-secondary)">
                  Status: <span class="font-mono font-medium"
                    >{backtestResult.status ?? "—"}</span
                  >
                  {#if backtestResult.run_id}
                    | Run ID: <span class="font-mono"
                      >{backtestResult.run_id}</span
                    >
                  {/if}
                </p>
                {#if backtestResult.metrics}
                  <div class="mt-3 grid gap-2 sm:grid-cols-3">
                    {#each Object.entries(backtestResult.metrics as Record<string, number>) as [key, value]}
                      <div
                        class="rounded-(--netz-radius-md) border border-(--netz-border-subtle) bg-(--netz-surface-panel) p-2.5"
                      >
                        <p class="text-xs text-(--netz-text-muted)">{key}</p>
                        <p
                          class="text-sm font-medium text-(--netz-text-primary)"
                        >
                          {typeof value === "number"
                            ? formatNumber(value, 4, "en-US")
                            : value}
                        </p>
                      </div>
                    {/each}
                  </div>
                {/if}
              </div>
            {/if}
          </SectionCard>

          <SectionCard
            title="Walk-Forward Validation"
            subtitle="Out-of-sample analysis with rolling windows"
          >
            <EmptyState
              title="Walk-Forward coming soon"
              message="Walk-forward validation will be enabled when the backtest engine supports rolling out-of-sample windows."
            />
          </SectionCard>
        </div>

        <!-- ═══════════════════════════════════════════════════════════════
			     Tab: Pareto Frontier
			     ═══════════════════════════════════════════════════════════════ -->
      {:else if activeTab === "pareto"}
        <div class="space-y-6">
          <SectionCard
            title="Pareto Frontier — Risk x Return"
            subtitle="CVaR 95% on X axis · Annualized return on Y axis"
          >
            {#snippet actions()}
              <div class="flex gap-2">
                <Button
                  onclick={runOptimization}
                  disabled={optimizationRunning}
                  size="sm"
                >
                  {optimizationRunning ? "Optimizing..." : "Quick Optimization"}
                </Button>
                <Button
                  onclick={runPareto}
                  disabled={paretoRunning}
                  size="sm"
                  variant="outline"
                >
                  {paretoRunning
                    ? "Pareto... (up to 2 min)"
                    : "Multi-objective (Pareto)"}
                </Button>
              </div>
            {/snippet}
            {#if paretoError}
              <div
                class="mb-3 rounded-(--netz-radius-md) border border-(--netz-status-error) bg-(--netz-surface-highlight) p-3 text-sm text-(--netz-status-error)"
              >
                {paretoError}
              </div>
            {/if}
            {#if optimizationError}
              <div
                class="mb-3 rounded-(--netz-radius-md) border border-(--netz-status-error) bg-(--netz-surface-highlight) p-3 text-sm text-(--netz-status-error)"
              >
                {optimizationError}
              </div>
            {/if}

            <!-- Legend chips -->
            <div class="mb-4 flex flex-wrap gap-3">
              <div
                class="flex items-center gap-1.5 rounded-(--netz-radius-pill) border border-(--netz-border-subtle) bg-(--netz-surface-highlight) px-3 py-1.5"
              >
                <span class="h-2.5 w-2.5 rounded-full bg-(--netz-brand-primary)"
                ></span>
                <span class="text-xs text-(--netz-text-muted)"
                  >Individual funds</span
                >
              </div>
              <div
                class="flex items-center gap-1.5 rounded-(--netz-radius-pill) border border-(--netz-border-subtle) bg-(--netz-surface-highlight) px-3 py-1.5"
              >
                <span
                  class="h-2.5 w-2.5 rotate-45 bg-(--netz-warning)"
                  style="display:inline-block;"
                ></span>
                <span class="text-xs text-(--netz-text-muted)">Portfolios</span>
              </div>
              <div
                class="flex items-center gap-1.5 rounded-(--netz-radius-pill) border border-(--netz-border-subtle) bg-(--netz-surface-highlight) px-3 py-1.5"
              >
                <span
                  class="h-0.5 w-5 border-t-2 border-dashed border-(--netz-brand-secondary)"
                ></span>
                <span class="text-xs text-(--netz-text-muted)"
                  >Efficient frontier</span
                >
              </div>
            </div>

            {#if correlationRegime && correlationRegime.points.length > 0}
              <div class="h-100">
                <ChartContainer
                  option={paretoOption}
                  height={380}
                  ariaLabel="Pareto frontier chart"
                />
              </div>
            {:else}
              <EmptyState
                title="No optimization data"
                message="Click 'Quick Optimization' to compute the efficient frontier. Requires historical CVaR for at least 3 funds."
              />
            {/if}
          </SectionCard>
        </div>

        <!-- ═══════════════════════════════════════════════════════════════
			     Tab: What-If Scenarios
			     ═══════════════════════════════════════════════════════════════ -->
      {:else if activeTab === "whatif"}
        <SectionCard
          title="What-If Scenarios"
          subtitle="Scenario simulation and stress testing"
        >
          <EmptyState
            title="Scenarios in development"
            message="What-If scenario analysis will be enabled when the stress_scenario_engine is integrated with the selected portfolio."
          />
        </SectionCard>

        <!-- ═══════════════════════════════════════════════════════════════
			     Tab: Atribuição de Performance
			     ═══════════════════════════════════════════════════════════════ -->
      {:else if activeTab === "atribuicao"}
        <SectionCard
          title="Performance Attribution"
          subtitle="Return decomposition by factor and asset class"
        >
          <div class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
            <Input
              type="text"
              bind:value={selectedFundId}
              placeholder="Fund ID"
              class="sm:max-w-56"
            />
            <Button
              onclick={loadAttribution}
              disabled={attributionLoading || !selectedFundId}
              size="sm"
            >
              {attributionLoading ? "Loading..." : "Load Attribution"}
            </Button>
          </div>
          {#if attributionData}
            <div class="space-y-2">
              {#each Object.entries(attributionData) as [key, value]}
                {#if key !== "fund_id" && key !== "period"}
                  <div
                    class="flex items-center justify-between rounded-(--netz-radius-md) border border-(--netz-border-subtle) bg-(--netz-surface-highlight) px-3 py-2 text-sm"
                  >
                    <span class="text-(--netz-text-primary)">{key}</span>
                    <span class="font-mono text-(--netz-text-secondary)"
                      >{typeof value === "number"
                        ? formatNumber(value, 4, "en-US")
                        : String(value ?? "—")}</span
                    >
                  </div>
                {/if}
              {/each}
            </div>
          {:else if !attributionLoaded}
            <EmptyState
              title="Select a fund"
              message="Enter the Fund ID and click Load Attribution to see the return decomposition."
            />
          {/if}
        </SectionCard>
      {/if}
    {/snippet}
  </PageTabs>
</div>
