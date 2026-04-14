<!--
  /macro — Macro Desk (Phase 7, Session A).

  12-column grid dashboard: 4 regional regime tiles (top),
  sparkline wall (bottom-left 9 cols), committee review feed
  (bottom-right 3 cols). Terminal-native primitives only.
-->
<script lang="ts">
  import { getContext } from "svelte";
  import { createClientApiClient } from "$lib/api/client";
  import { pinnedRegime } from "$lib/state/pinned-regime.svelte";
  import Panel from "$lib/components/terminal/layout/Panel.svelte";
  import PanelHeader from "$lib/components/terminal/layout/PanelHeader.svelte";
  import RegimeTile from "$lib/components/terminal/macro/RegimeTile.svelte";
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

  interface RegimeHierarchyRead {
    global_regime: string;
    regional_regimes: Record<string, string>;
    composition_reasons: Record<string, string>;
    as_of_date: string | null;
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
  let regime = $state<RegimeHierarchyRead | null>(null);
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

  async function fetchMacroData() {
    try {
      const [scoresRes, regimeRes, reviewsRes] = await Promise.all([
        api.get<MacroScoresResponse>("/macro/scores"),
        api.get<RegimeHierarchyRead>("/macro/regime"),
        api.get<MacroReviewRead[]>("/macro/reviews?limit=10"),
      ]);
      scores = scoresRes;
      regime = regimeRes;
      reviews = reviewsRes;
      fetchError = false;
    } catch {
      fetchError = true;
    } finally {
      loading = false;
    }
  }

  async function fetchSparklines() {
    const results: typeof sparklineData = [];

    const fetches = SPARKLINE_SERIES.map(async (cfg) => {
      try {
        const res = await api.get<FredDataResponse>(`/macro/fred?series_id=${cfg.seriesId}`);
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
      } catch {
        // Skip unavailable series silently
      }
    });

    await Promise.all(fetches);

    // Preserve config ordering
    const order = new Map(SPARKLINE_SERIES.map((s, i) => [s.name, i]));
    results.sort((a, b) => (order.get(a.name) ?? 99) - (order.get(b.name) ?? 99));
    sparklineData = results;
  }

  // -- Derived views ---------------------------------------------------

  interface TileData {
    region: string;
    compositeScore: number;
    regime: string;
    dimensions: Array<{ name: string; score: number }>;
  }

  const tiles = $derived.by<TileData[]>(() => {
    if (!scores || !regime) return [];
    return REGION_ORDER.map((key) => {
      const reg = scores!.regions[key];
      if (!reg) return null;
      const dims = Object.entries(reg.dimensions).map(([name, d]) => ({
        name,
        score: d.score,
      }));
      return {
        region: REGION_LABELS[key] ?? key,
        compositeScore: reg.composite_score,
        regime: regime!.regional_regimes[key] ?? "Unknown",
        dimensions: dims,
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

  // -- Regime display helpers ------------------------------------------

  const REGIME_DISPLAY: Record<string, string> = {
    REGIME_NORMAL: "Normal",
    normal: "Normal",
    REGIME_RISK_ON: "Risk On",
    risk_on: "Risk On",
    REGIME_RISK_OFF: "Risk Off",
    risk_off: "Risk Off",
    REGIME_CRISIS: "Crisis",
    crisis: "Crisis",
  };

  function sanitizeRegime(raw: string): string {
    return REGIME_DISPLAY[raw] ?? raw;
  }

  const globalRegimeLabel = $derived(
    regime ? sanitizeRegime(regime.global_regime) : "Unknown",
  );

  const isPinned = $derived(pinnedRegime.current !== null);

  function handlePinRegime() {
    if (!regime || !scores) return;

    // Compute global composite from regional averages
    const regionKeys = Object.keys(scores.regions);
    const avgScore = regionKeys.length > 0
      ? regionKeys.reduce((sum, k) => sum + (scores!.regions[k]?.composite_score ?? 0), 0) / regionKeys.length
      : 0;

    pinnedRegime.pin({
      label: globalRegimeLabel,
      region: "GLOBAL",
      score: Math.round(avgScore),
    });
  }

  function handleUnpinRegime() {
    pinnedRegime.clear();
  }

  // -- Effects ---------------------------------------------------------

  $effect(() => {
    fetchMacroData();
    fetchSparklines();

    const timer = setInterval(() => {
      fetchMacroData();
      fetchSparklines();
    }, 5 * 60 * 1000); // 5 min poll

    return () => clearInterval(timer);
  });
</script>

<div class="macro-desk" data-macro-root>
  {#if loading}
    <div class="macro-state">Loading macro data...</div>
  {:else if fetchError}
    <div class="macro-state macro-state--error">Failed to load macro data. Retrying...</div>
  {:else}
    <!-- Top row: 4 regime tiles + pin action -->
    <div class="macro-tiles-row">
      <div class="macro-tiles">
        {#each tiles as tile (tile.region)}
          <RegimeTile
            region={tile.region}
            compositeScore={tile.compositeScore}
            regime={tile.regime}
            dimensions={tile.dimensions}
          />
        {/each}
      </div>
      <div class="macro-pin-bar">
        <span class="macro-global-regime">
          GLOBAL: <strong>{globalRegimeLabel}</strong>
        </span>
        {#if isPinned}
          <button
            type="button"
            class="macro-pin-btn macro-pin-btn--active"
            onclick={handleUnpinRegime}
          >
            UNPIN REGIME
          </button>
        {:else}
          <button
            type="button"
            class="macro-pin-btn"
            onclick={handlePinRegime}
          >
            PIN REGIME
          </button>
        {/if}
      </div>
    </div>

    <!-- Bottom row: sparkline wall + committee feed -->
    <div class="macro-bottom">
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
    height: 100%;
    font-family: var(--terminal-font-mono);
    overflow: hidden;
  }

  .macro-tiles-row {
    display: flex;
    flex-direction: column;
    gap: var(--terminal-space-2);
    flex-shrink: 0;
  }

  .macro-tiles {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: var(--terminal-space-3);
  }

  .macro-pin-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 var(--terminal-space-1);
  }

  .macro-global-regime {
    font-size: var(--terminal-text-10);
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    color: var(--terminal-fg-tertiary);
  }

  .macro-global-regime strong {
    color: var(--terminal-fg-primary);
    font-weight: 700;
  }

  .macro-pin-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--terminal-space-1);
    padding: 2px var(--terminal-space-2);
    background: transparent;
    border: var(--terminal-border-hairline);
    border-radius: var(--terminal-radius-none);
    font-family: var(--terminal-font-mono);
    font-size: var(--terminal-text-10);
    font-weight: 600;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    color: var(--terminal-fg-secondary);
    cursor: pointer;
    transition:
      border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
      color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
  }

  .macro-pin-btn:hover {
    border-color: var(--terminal-accent-amber);
    color: var(--terminal-accent-amber);
  }

  .macro-pin-btn--active {
    border-color: var(--terminal-accent-cyan);
    color: var(--terminal-accent-cyan);
  }

  .macro-pin-btn--active:hover {
    border-color: var(--terminal-status-error);
    color: var(--terminal-status-error);
  }

  .macro-bottom {
    display: grid;
    grid-template-columns: 1fr 300px;
    gap: var(--terminal-space-3);
    flex: 1;
    min-height: 0;
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
