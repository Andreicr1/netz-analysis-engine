<!--
  /macro — Macro Desk (Terminal Command Center).

  Four-zone layout per plan §M1:
    Zone 1: StressHero (7fr) + RegimeMatrix (5fr) side-by-side
    Zone 2: SignalBreakdown (full-width)
    Zone 3: RegionalHealth (6fr) + SparklineWall (6fr)
    CommitteeReviewFeed lives in a right-anchored drawer, toggled
    via Shift+R or the badge in the zone-1 header. It never sits
    inline in the main grid.

  The RegimeMatrix is a page-scoped simulation — it writes to a
  local store (macro-simulation-store.svelte.ts), never to the global
  pinnedRegime store and never to the backend.
-->
<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { getContext } from "svelte";
  import { createClientApiClient } from "$lib/api/client";
  import { pinnedRegime } from "$lib/state/pinned-regime.svelte";
  import { TerminalDrawer, TerminalKbd } from "@investintell/ii-terminal-core";
  import Panel from "$lib/components/terminal/layout/Panel.svelte";
  import PanelHeader from "$lib/components/terminal/layout/PanelHeader.svelte";
  import StressHero from "$lib/components/terminal/macro/StressHero.svelte";
  import SignalBreakdown from "$lib/components/terminal/macro/SignalBreakdown.svelte";
  import RegionalHealthTile from "$lib/components/terminal/macro/RegionalHealthTile.svelte";
  import SparklineWall, {
    type MacroIndicator,
  } from "$lib/components/terminal/macro/SparklineWall.svelte";
  import CommitteeReviewFeed from "$lib/components/terminal/macro/CommitteeReviewFeed.svelte";
  import RegimeMatrix from "$lib/components/terminal/macro/RegimeMatrix.svelte";
  import {
    createMacroSimulationStore,
    type RegimeCell,
  } from "$lib/components/terminal/macro/macro-simulation-store.svelte";

  // -- Types -----------------------------------------------------------

  interface DimensionScoreRead {
    score: number;
    n_indicators: number;
    indicators: Record<string, number>;
  }

  interface RegionalScoreRead {
    composite_score: number;
    coverage: number;
    dimensions: Record<string, DimensionScoreRead>;
    data_freshness: Record<string, unknown>;
    analysis_text: string | null;
  }

  interface MacroScoresResponse {
    as_of_date: string;
    regions: Record<string, RegionalScoreRead>;
    global_indicators: {
      geopolitical_risk_score: number;
      energy_stress: number;
      commodity_stress: number;
      usd_strength: number;
    };
  }

  interface RegimeSignalRead {
    key: string;
    label: string;
    raw_value: number | null;
    unit: string;
    stress_score: number;
    weight_base: number;
    weight_effective: number;
    category: "financial" | "real_economy";
    fred_series: string | null;
  }

  interface GlobalRegimeRead {
    as_of_date: string;
    raw_regime: string;
    stress_score: number | null;
    signal_details: Record<string, string>;
    signal_breakdown: RegimeSignalRead[];
  }

  interface FredTimePoint {
    obs_date: string;
    value: number;
    source: string;
  }

  interface FredDataResponse {
    series_id: string;
    data: FredTimePoint[];
  }

  interface MacroReviewRead {
    id: string;
    status: string;
    is_emergency: boolean;
    as_of_date: string;
    report_json: Record<string, unknown>;
    created_at: string;
    created_by: string | null;
  }

  // -- API client ------------------------------------------------------

  const getToken = getContext<() => Promise<string>>("netz:getToken");
  const api = createClientApiClient(getToken);

  // -- State -----------------------------------------------------------

  let scores = $state<MacroScoresResponse | null>(null);
  let regime = $state<GlobalRegimeRead | null>(null);
  let reviews = $state<MacroReviewRead[]>([]);
  let sparklineData = $state<MacroIndicator[]>([]);
  let loading = $state(true);
  let fetchError = $state(false);

  // Page-scoped simulation store — never reads/writes pinnedRegime.
  const simulation = createMacroSimulationStore();

  // Committee Reviews drawer — closed by default, toggled via
  // Shift+R or the header badge click.
  let committeeDrawerOpen = $state(false);

  // -- FRED series config ----------------------------------------------

  const SPARKLINE_SERIES: Array<{
    seriesId: string;
    name: string;
    unit: string;
  }> = [
    { seriesId: "A191RL1Q225SBEA", name: "GDP Growth", unit: "%" },
    { seriesId: "CPIAUCSL", name: "CPI", unit: "idx" },
    { seriesId: "UNRATE", name: "Unemployment", unit: "%" },
    { seriesId: "DFF", name: "Fed Funds", unit: "%" },
    { seriesId: "DGS10", name: "10Y Yield", unit: "%" },
    { seriesId: "BAA10Y", name: "Credit Spread", unit: "%" },
    { seriesId: "VIXCLS", name: "VIX", unit: "idx" },
    { seriesId: "DTWEXBGS", name: "USD Index", unit: "idx" },
  ];

  // -- Region display config -------------------------------------------

  const REGION_ORDER = ["US", "EUROPE", "ASIA", "EM"] as const;
  const REGION_LABELS: Record<string, string> = {
    US: "US",
    EUROPE: "EU",
    ASIA: "JP",
    EM: "EM",
  };

  // -- Data fetching ---------------------------------------------------

  async function fetchAllData(signal: AbortSignal) {
    try {
      const [scoresRes, regimeRes, reviewsRes] = await Promise.all([
        api.get<MacroScoresResponse>("/macro/scores", undefined, { signal }),
        api.get<GlobalRegimeRead>("/macro/regime", undefined, { signal }),
        api.get<MacroReviewRead[]>("/macro/reviews?limit=10", undefined, { signal }),
      ]);
      scores = scoresRes;
      regime = regimeRes;
      reviews = reviewsRes;
      fetchError = false;
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      fetchError = true;
    } finally {
      loading = false;
    }
  }

  async function fetchSparklines(signal: AbortSignal) {
    const results: MacroIndicator[] = [];

    const fetches = SPARKLINE_SERIES.map(async (cfg) => {
      try {
        const res = await api.get<FredDataResponse>(
          `/macro/fred?series_id=${cfg.seriesId}`,
          undefined,
          { signal },
        );
        if (res.data.length > 0) {
          const history = res.data.map((pt) => ({ date: pt.obs_date, value: pt.value }));
          const last = history[history.length - 1]!;
          const current = last.value;
          const previous = history.length > 1 ? history[history.length - 2]!.value : current;
          results.push({
            seriesId: cfg.seriesId,
            name: cfg.name,
            currentValue: current,
            previousValue: previous,
            history,
            unit: cfg.unit,
          });
        }
      } catch (e: unknown) {
        if (e instanceof DOMException && e.name === "AbortError") throw e;
        // Skip unavailable series silently
      }
    });

    try {
      await Promise.all(fetches);
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === "AbortError") return;
    }

    const order = new Map(SPARKLINE_SERIES.map((s, i) => [s.name, i]));
    results.sort((a, b) => (order.get(a.name) ?? 99) - (order.get(b.name) ?? 99));
    sparklineData = results;
  }

  // -- Derived views ---------------------------------------------------

  const financialEffWeight = $derived(
    (regime?.signal_breakdown ?? [])
      .filter((s) => s.category === "financial")
      .reduce((sum, s) => sum + s.weight_effective, 0),
  );

  const realEconEffWeight = $derived(
    (regime?.signal_breakdown ?? [])
      .filter((s) => s.category === "real_economy")
      .reduce((sum, s) => sum + s.weight_effective, 0),
  );

  interface TileData {
    region: string;
    compositeScore: number;
    dimensions: Array<{ name: string; score: number }>;
  }

  const tiles = $derived.by<TileData[]>(() => {
    if (!scores) return [];
    return REGION_ORDER.map((key) => {
      const reg = scores!.regions[key];
      if (!reg) return null;
      return {
        region: REGION_LABELS[key] ?? key,
        compositeScore: reg.composite_score,
        dimensions: Object.entries(reg.dimensions).map(([name, d]) => ({
          name,
          score: d.score,
        })),
      };
    }).filter((t): t is TileData => t !== null);
  });

  const reviewCards = $derived(
    reviews.map((r) => {
      let summary = "";
      if (r.report_json) {
        const exec = r.report_json.executive_summary ?? r.report_json.summary ?? "";
        summary = typeof exec === "string" ? exec : JSON.stringify(exec);
      }
      return {
        id: r.id,
        status: r.status,
        createdAt: r.created_at,
        summary,
      };
    }),
  );

  const isPinned = $derived(pinnedRegime.current !== null);

  // Effective regime shown on the Hero: the real one by default, or
  // the simulated label when the matrix has a committed cell. The
  // simulated label never propagates to `pinnedRegime`.
  const effectiveRegimeLabel = $derived(
    simulation.label ?? regime?.raw_regime ?? "Unknown",
  );

  function handlePinRegime() {
    if (!regime) return;
    pinnedRegime.pin({
      label: regime.raw_regime,
      region: "GLOBAL",
      score: Math.round(regime.stress_score ?? 0),
    });
  }

  function handleUnpinRegime() {
    pinnedRegime.clear();
  }

  function handleProceedToAlloc() {
    // Route groups (`(terminal)`) are invisible in URLs — target is
    // `/allocation`, NOT `/terminal/allocation`.
    goto(resolve("/allocation"));
  }

  function handleSimulateCell(cell: RegimeCell | null) {
    simulation.setCell(cell);
  }

  // -- Keyboard: Shift+R toggles the committee drawer ------------------

  function isEditableTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) return false;
    const tag = target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
    if (target.isContentEditable) return true;
    const role = target.getAttribute("role");
    if (role === "textbox" || role === "searchbox" || role === "combobox") return true;
    return false;
  }

  $effect(() => {
    if (typeof window === "undefined") return;
    const handler = (event: KeyboardEvent) => {
      if (
        event.shiftKey &&
        !event.metaKey &&
        !event.ctrlKey &&
        !event.altKey &&
        (event.key === "R" || event.key === "r")
      ) {
        if (isEditableTarget(event.target)) return;
        event.preventDefault();
        committeeDrawerOpen = !committeeDrawerOpen;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });

  // -- Effects ---------------------------------------------------------

  $effect(() => {
    const ac = new AbortController();

    fetchAllData(ac.signal);
    fetchSparklines(ac.signal);

    const timer = setInterval(() => {
      fetchAllData(ac.signal);
      fetchSparklines(ac.signal);
    }, 5 * 60 * 1000);

    return () => {
      ac.abort();
      clearInterval(timer);
    };
  });
</script>

<div class="macro-desk" data-macro-root>
  {#if loading}
    <div class="macro-state">Loading macro data...</div>
  {:else if fetchError}
    <div class="macro-state macro-state--error">Failed to load macro data. Retrying...</div>
  {:else}
    <!-- Zone 1: Hero + RegimeMatrix side-by-side. -->
    <div class="macro-zone macro-zone--hero">
      <div class="macro-hero">
        <StressHero
          stressScore={regime?.stress_score ?? 0}
          regimeLabel={effectiveRegimeLabel}
          asOfDate={regime?.as_of_date ?? ""}
          {financialEffWeight}
          {realEconEffWeight}
          {isPinned}
          onPin={handlePinRegime}
          onUnpin={handleUnpinRegime}
          onProceedToAlloc={handleProceedToAlloc}
        />
      </div>
      <div class="macro-matrix">
        <RegimeMatrix
          activeRegime={regime?.raw_regime ?? "Unknown"}
          simulatedCell={simulation.cell}
          onSimulate={handleSimulateCell}
        />
      </div>
    </div>

    <!-- Zone 2: SignalBreakdown full-width. -->
    <SignalBreakdown signals={regime?.signal_breakdown ?? []} />

    <!-- Zone 3: RegionalHealth + SparklineWall (6fr/6fr). Committee
         reviews live in a drawer (Shift+R), never inline. -->
    <div class="macro-bottom">
      <div class="macro-regions">
        <Panel>
          {#snippet header()}
            <PanelHeader label="REGIONAL ECONOMIC HEALTH" />
          {/snippet}
          <div class="region-grid">
            {#each tiles as tile (tile.region)}
              <RegionalHealthTile
                region={tile.region}
                compositeScore={tile.compositeScore}
                dimensions={tile.dimensions}
              />
            {/each}
          </div>
        </Panel>
      </div>

      <div class="macro-sparklines">
        <Panel>
          {#snippet header()}
            <PanelHeader label="MACRO INDICATORS" />
          {/snippet}
          <SparklineWall indicators={sparklineData} />
        </Panel>
      </div>
    </div>

    <!-- Floating committee drawer toggle + shortcut hint. -->
    <button
      type="button"
      class="macro-committee-fab"
      aria-label="Open committee reviews (Shift+R)"
      aria-expanded={committeeDrawerOpen}
      onclick={() => (committeeDrawerOpen = !committeeDrawerOpen)}
    >
      <span class="macro-committee-fab__label">COMMITTEE</span>
      <span class="macro-committee-fab__count">{reviews.length}</span>
      <span class="macro-committee-fab__kbd">
        <TerminalKbd keys={["Shift", "R"]} />
      </span>
    </button>
  {/if}
</div>

<TerminalDrawer
  open={committeeDrawerOpen}
  label="Committee Reviews"
  side="right"
  width={400}
  onClose={() => (committeeDrawerOpen = false)}
>
  <CommitteeReviewFeed reviews={reviewCards} />
</TerminalDrawer>

<style>
  .macro-desk {
    display: flex;
    flex-direction: column;
    gap: var(--terminal-space-3);
    width: 100%;
    height: calc(100vh - 88px);
    font-family: var(--terminal-font-mono);
    overflow-y: auto;
    padding: 24px;
    position: relative;
  }

  .macro-zone--hero {
    display: grid;
    grid-template-columns: 7fr 5fr;
    gap: var(--terminal-space-3);
    flex-shrink: 0;
  }

  .macro-hero,
  .macro-matrix {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .macro-bottom {
    display: grid;
    grid-template-columns: 6fr 6fr;
    gap: var(--terminal-space-3);
    flex: 1;
    min-height: 0;
  }

  .macro-regions,
  .macro-sparklines {
    min-height: 0;
    overflow: hidden;
  }

  .region-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: var(--terminal-space-2);
  }

  /* Floating committee toggle — sits bottom-right above the
     statusbar so it doesn't collide with the TerminalTweaksPanel
     FAB (that one is higher-right). */
  .macro-committee-fab {
    position: fixed;
    bottom: calc(var(--terminal-shell-statusbar-height) + var(--terminal-space-3));
    right: calc(var(--terminal-space-3) + 48px);
    display: inline-flex;
    align-items: center;
    gap: var(--terminal-space-2);
    padding: 4px var(--terminal-space-3);
    background: var(--terminal-bg-panel-raised);
    border: var(--terminal-border-hairline);
    color: var(--terminal-fg-secondary);
    font-family: var(--terminal-font-mono);
    font-size: var(--terminal-text-10);
    letter-spacing: var(--terminal-tracking-caps);
    cursor: pointer;
    z-index: var(--terminal-z-toast);
  }
  .macro-committee-fab:hover {
    color: var(--terminal-accent-amber);
    border-color: var(--terminal-accent-amber);
  }
  .macro-committee-fab:focus-visible {
    outline: var(--terminal-border-focus);
    outline-offset: 1px;
  }
  .macro-committee-fab__label {
    font-weight: 600;
  }
  .macro-committee-fab__count {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 16px;
    padding: 0 4px;
    background: var(--terminal-bg-panel-sunken);
    color: var(--terminal-fg-primary);
    font-variant-numeric: tabular-nums;
  }
  .macro-committee-fab__kbd {
    display: inline-flex;
  }

  .macro-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    font-size: var(--terminal-text-11);
    color: var(--terminal-fg-muted);
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
  }

  .macro-state--error {
    color: var(--terminal-status-error);
  }
</style>
