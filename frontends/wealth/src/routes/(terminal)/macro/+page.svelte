<!--
  /macro — Macro Desk (Terminal Command Center).

  Layout: StressHero (full-width) → SignalBreakdown (2-col) →
  Bottom grid: Regional Health (5fr) | Indicators (4fr) | Committee (3fr).
  Terminal-native primitives only.
-->
<script lang="ts">
  import { goto } from "$app/navigation";
  import { getContext } from "svelte";
  import { createClientApiClient } from "$lib/api/client";
  import { pinnedRegime } from "$lib/state/pinned-regime.svelte";
  import Panel from "$lib/components/terminal/layout/Panel.svelte";
  import PanelHeader from "$lib/components/terminal/layout/PanelHeader.svelte";
  import StressHero from "$lib/components/terminal/macro/StressHero.svelte";
  import SignalBreakdown from "$lib/components/terminal/macro/SignalBreakdown.svelte";
  import RegionalHealthTile from "$lib/components/terminal/macro/RegionalHealthTile.svelte";
  import SparklineWall from "$lib/components/terminal/macro/SparklineWall.svelte";
  import CommitteeReviewFeed from "$lib/components/terminal/macro/CommitteeReviewFeed.svelte";

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
  let sparklineData = $state<Array<{
    name: string;
    currentValue: number;
    previousValue: number;
    history: Array<{ date: string; value: number }>;
    unit: string;
  }>>([]);
  let loading = $state(true);
  let fetchError = $state(false);

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
    const results: typeof sparklineData = [];

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

  const financialSignals = $derived(
    (regime?.signal_breakdown ?? [])
      .filter((s) => s.category === "financial")
      .sort((a, b) => b.weight_effective - a.weight_effective),
  );

  const realEconSignals = $derived(
    (regime?.signal_breakdown ?? [])
      .filter((s) => s.category === "real_economy")
      .sort((a, b) => b.weight_effective - a.weight_effective),
  );

  const financialEffWeight = $derived(
    financialSignals.reduce((sum, s) => sum + s.weight_effective, 0),
  );

  const realEconEffWeight = $derived(
    realEconSignals.reduce((sum, s) => sum + s.weight_effective, 0),
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
    goto("/terminal/allocation");
  }

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
    <StressHero
      stressScore={regime?.stress_score ?? 0}
      regimeLabel={regime?.raw_regime ?? "Unknown"}
      asOfDate={regime?.as_of_date ?? ""}
      {financialEffWeight}
      {realEconEffWeight}
      {isPinned}
      onPin={handlePinRegime}
      onUnpin={handleUnpinRegime}
      onProceedToAlloc={handleProceedToAlloc}
    />

    <SignalBreakdown signals={regime?.signal_breakdown ?? []} />

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

      <div class="macro-feed">
        <Panel scrollable>
          {#snippet header()}
            <PanelHeader label="COMMITTEE REVIEWS">
              {#snippet actions()}
                <span class="macro-review-count">{reviews.length}</span>
              {/snippet}
            </PanelHeader>
          {/snippet}
          <CommitteeReviewFeed reviews={reviewCards} />
        </Panel>
      </div>
    </div>
  {/if}
</div>

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
  }

  .macro-bottom {
    display: grid;
    grid-template-columns: 5fr 4fr 3fr;
    gap: var(--terminal-space-3);
    flex: 1;
    min-height: 0;
  }

  .macro-regions {
    min-height: 0;
    overflow: hidden;
  }

  .region-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: var(--terminal-space-2);
  }

  .macro-sparklines {
    min-height: 0;
    overflow: hidden;
  }

  .macro-feed {
    min-height: 0;
    overflow: hidden;
  }

  .macro-review-count {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    height: 16px;
    padding: 0 4px;
    font-size: var(--terminal-text-10);
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    background: var(--terminal-fg-muted);
    color: var(--terminal-fg-inverted);
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
