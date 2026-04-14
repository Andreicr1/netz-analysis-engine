<!--
  /allocation — Allocation Editor (Phase 7, Session B).

  Three-column layout: block tree (left 250px) | weights editor
  (center 1fr) | impact preview (right 350px). Terminal-native.
  Weights are 0–1 in backend, displayed as 0–100% in the UI.
-->
<script lang="ts">
  import { getContext } from "svelte";
  import { createClientApiClient } from "$lib/api/client";
  import Panel from "$lib/components/terminal/layout/Panel.svelte";
  import PanelHeader from "$lib/components/terminal/layout/PanelHeader.svelte";
  import WeightsEditor from "$lib/components/terminal/allocation/WeightsEditor.svelte";
  import ImpactPreview from "$lib/components/terminal/allocation/ImpactPreview.svelte";

  // -- Types -----------------------------------------------------------

  interface StrategicAllocationRead {
    allocation_id: string;
    profile: string;
    block_id: string;
    target_weight: number;
    min_weight: number;
    max_weight: number;
    risk_budget: number | null;
    rationale: string | null;
    approved_by: string | null;
    effective_from: string;
    effective_to: string | null;
    created_at: string;
  }

  interface TacticalPositionRead {
    position_id: string;
    profile: string;
    block_id: string;
    overweight: number;
    conviction_score: number | null;
    signal_source: string | null;
    rationale: string | null;
    valid_from: string;
    valid_to: string | null;
    source: string | null;
    created_at: string;
  }

  interface EffectiveAllocationRead {
    profile: string;
    block_id: string;
    strategic_weight: number | null;
    tactical_overweight: number | null;
    effective_weight: number | null;
    min_weight: number | null;
    max_weight: number | null;
  }

  interface GlobalRegimeRead {
    as_of_date: string;
    raw_regime: string;
    stress_score: number | null;
    signal_details: Record<string, unknown>;
  }

  interface RegimeBandsRead {
    profile: string;
    as_of_date: string;
    raw_regime: string;
    stress_score: number | null;
    smoothed_centers: Record<string, number>;
    effective_bands: Record<string, { min: number; max: number; center?: number }>;
    transition_velocity: Record<string, number> | null;
    ips_clamps_applied: string[];
  }

  // -- API client ------------------------------------------------------

  const getToken = getContext<() => Promise<string>>("netz:getToken");
  const api = createClientApiClient(getToken);
  const PROFILE = "default";

  // -- State -----------------------------------------------------------

  let strategicData = $state<StrategicAllocationRead[]>([]);
  let tacticalData = $state<TacticalPositionRead[]>([]);
  let effectiveData = $state<EffectiveAllocationRead[]>([]);
  let regimeData = $state<GlobalRegimeRead | null>(null);
  let regimeBands = $state<RegimeBandsRead | null>(null);

  let loading = $state(true);
  let fetchError = $state(false);
  let isSaving = $state(false);
  let isSimulating = $state(false);
  let simulationResult = $state<{
    proposedCvar: number | null;
    cvarLimit: number | null;
    cvarUtilization: number | null;
    cvarDelta: number | null;
    withinLimit: boolean;
    warnings: string[];
  } | null>(null);

  let selectedBlockId = $state<string | null>(null);

  // -- Block name helper -----------------------------------------------

  function blockDisplayName(blockId: string): string {
    return blockId
      .split("_")
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
  }

  // -- Data fetching ---------------------------------------------------

  async function fetchAllData() {
    try {
      const [strategic, tactical, effective, regime] = await Promise.all([
        api.get<StrategicAllocationRead[]>(`/allocation/${PROFILE}/strategic`),
        api.get<TacticalPositionRead[]>(`/allocation/${PROFILE}/tactical`),
        api.get<EffectiveAllocationRead[]>(`/allocation/${PROFILE}/effective`),
        api.get<GlobalRegimeRead>("/allocation/regime"),
      ]);
      strategicData = strategic;
      tacticalData = tactical;
      effectiveData = effective;
      regimeData = regime;
      fetchError = false;

      // Fetch regime bands (non-blocking — may 404 if worker hasn't run)
      try {
        regimeBands = await api.get<RegimeBandsRead>(`/allocation/${PROFILE}/regime-bands`);
      } catch {
        regimeBands = null;
      }
    } catch {
      fetchError = true;
    } finally {
      loading = false;
    }
  }

  // -- Derived views ---------------------------------------------------

  // Merge strategic + tactical into editor rows
  const editorBlocks = $derived.by(() => {
    const tacticalMap = new Map(tacticalData.map((t) => [t.block_id, t]));
    return strategicData.map((s) => {
      const t = tacticalMap.get(s.block_id);
      return {
        blockId: s.block_id,
        name: blockDisplayName(s.block_id),
        strategicWeight: Number(s.target_weight),
        tacticalOverweight: t ? Number(t.overweight) : 0,
      };
    });
  });

  // Block tree entries
  const blockTree = $derived(
    strategicData.map((s) => ({
      blockId: s.block_id,
      name: blockDisplayName(s.block_id),
      weight: Number(s.target_weight),
    })),
  );

  // Effective for the impact chart
  const effectiveForChart = $derived(
    effectiveData.map((e) => ({
      name: blockDisplayName(e.block_id),
      weight: Number(e.effective_weight ?? 0),
    })),
  );

  // Regime suggestions from bands
  const regimeSuggestions = $derived.by(() => {
    if (!regimeBands) return null;
    return Object.entries(regimeBands.smoothed_centers).map(([blockId, center]) => ({
      blockId,
      suggestedWeight: center,
    }));
  });

  // -- Save handler ----------------------------------------------------

  async function handleSave(
    strategic: Array<{ blockId: string; weight: number }>,
    tactical: Array<{ blockId: string; overweight: number }>,
  ) {
    isSaving = true;
    try {
      // Build strategic update payload
      const strategicMap = new Map(strategicData.map((s) => [s.block_id, s]));
      const allocations = strategic.map((s) => {
        const existing = strategicMap.get(s.blockId);
        return {
          block_id: s.blockId,
          target_weight: s.weight,
          min_weight: existing ? Number(existing.min_weight) : 0,
          max_weight: existing ? Number(existing.max_weight) : 1,
          risk_budget: existing?.risk_budget ?? null,
          rationale: existing?.rationale ?? null,
        };
      });

      // Build tactical update payload
      const positions = tactical
        .filter((t) => Math.abs(t.overweight) > 0.0001)
        .map((t) => ({
          block_id: t.blockId,
          overweight: t.overweight,
          source: "ic_manual",
        }));

      await Promise.all([
        api.put(`/allocation/${PROFILE}/strategic`, { allocations }),
        api.put(`/allocation/${PROFILE}/tactical`, { positions }),
      ]);

      // Refresh data
      await fetchAllData();
    } catch {
      // Error handling — the API client will surface toast/error
    } finally {
      isSaving = false;
    }
  }

  // -- Simulate handler ------------------------------------------------

  async function handleSimulate() {
    // The simulate endpoint expects instrument_id -> weight (not block_id).
    // Block-level simulation is not supported by the current backend.
    // Show informational message.
    simulationResult = {
      proposedCvar: null,
      cvarLimit: null,
      cvarUtilization: null,
      cvarDelta: null,
      withinLimit: true,
      warnings: [
        "Block-level simulation requires portfolio instruments. "
        + "Navigate to the Builder to run full CVaR simulation with instrument-level weights.",
      ],
    };
  }

  // -- Effects ---------------------------------------------------------

  $effect(() => {
    fetchAllData();
    return () => {};
  });
</script>

<div class="alloc-page">
  {#if loading}
    <div class="alloc-state">Loading allocation data...</div>
  {:else if fetchError}
    <div class="alloc-state alloc-state--error">
      Failed to load allocation data. Check backend connection.
    </div>
  {:else}
    <!-- Left: Block tree -->
    <div class="alloc-tree">
      <Panel scrollable>
        {#snippet header()}
          <PanelHeader label="ALLOCATION BLOCKS" />
        {/snippet}
        <div class="alloc-block-list">
          {#each blockTree as block (block.blockId)}
            <button
              type="button"
              class="alloc-block-item"
              class:alloc-block-item--selected={selectedBlockId === block.blockId}
              onclick={() => { selectedBlockId = block.blockId; }}
            >
              <span class="alloc-block-name">{block.name}</span>
              <span class="alloc-block-weight">
                {(block.weight * 100).toFixed(1)}%
              </span>
            </button>
          {/each}
          {#if blockTree.length === 0}
            <div class="alloc-block-empty">
              No allocation blocks configured
            </div>
          {/if}
        </div>
      </Panel>
    </div>

    <!-- Center: Weights editor -->
    <div class="alloc-editor">
      <Panel>
        {#snippet header()}
          <PanelHeader label="WEIGHTS EDITOR">
            {#snippet actions()}
              {#if regimeData}
                <span class="alloc-editor-regime">
                  {regimeData.raw_regime}
                </span>
              {/if}
            {/snippet}
          </PanelHeader>
        {/snippet}
        <WeightsEditor
          blocks={editorBlocks}
          {regimeSuggestions}
          onSave={handleSave}
          {isSaving}
        />
      </Panel>
    </div>

    <!-- Right: Impact preview -->
    <div class="alloc-preview">
      <Panel>
        {#snippet header()}
          <PanelHeader label="IMPACT PREVIEW" />
        {/snippet}
        <ImpactPreview
          effective={effectiveForChart}
          regime={regimeData?.raw_regime ?? "unknown"}
          {simulationResult}
          onSimulate={handleSimulate}
          {isSimulating}
        />
      </Panel>
    </div>
  {/if}
</div>

<style>
  .alloc-page {
    display: grid;
    grid-template-columns: 250px 1fr 350px;
    gap: var(--terminal-space-3);
    width: 100%;
    height: 100%;
    font-family: var(--terminal-font-mono);
    overflow: hidden;
  }

  .alloc-tree {
    min-height: 0;
    overflow: hidden;
  }

  .alloc-editor {
    min-height: 0;
    overflow: hidden;
  }

  .alloc-preview {
    min-height: 0;
    overflow: hidden;
  }

  .alloc-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    grid-column: 1 / -1;
    font-size: var(--terminal-text-11);
    color: var(--terminal-fg-muted);
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
  }

  .alloc-state--error {
    color: var(--terminal-status-error);
  }

  /* Block tree items */
  .alloc-block-list {
    display: flex;
    flex-direction: column;
  }

  .alloc-block-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    padding: var(--terminal-space-2) var(--terminal-space-3);
    background: transparent;
    border: none;
    border-bottom: var(--terminal-border-hairline);
    border-radius: var(--terminal-radius-none);
    color: var(--terminal-fg-secondary);
    font-family: var(--terminal-font-mono);
    font-size: var(--terminal-text-11);
    cursor: pointer;
    text-align: left;
    transition:
      background var(--terminal-motion-tick) var(--terminal-motion-easing-out),
      color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
  }

  .alloc-block-item:hover {
    background: var(--terminal-bg-panel-raised);
    color: var(--terminal-fg-primary);
  }

  .alloc-block-item--selected {
    background: var(--terminal-bg-panel-raised);
    color: var(--terminal-accent-amber);
    border-left: 2px solid var(--terminal-accent-amber);
  }

  .alloc-block-name {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .alloc-block-weight {
    flex-shrink: 0;
    font-variant-numeric: tabular-nums;
    color: var(--terminal-fg-muted);
  }

  .alloc-block-empty {
    padding: var(--terminal-space-4);
    text-align: center;
    font-size: var(--terminal-text-10);
    color: var(--terminal-fg-muted);
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
  }

  .alloc-editor-regime {
    font-size: var(--terminal-text-10);
    color: var(--terminal-fg-muted);
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
  }
</style>
