<!--
  WeightsEditor.svelte — editable strategic + tactical allocation table.

  Terminal-native: mono font, hairline borders, zero radius.
  Weights display as 0–100% but backend stores as 0–1 decimals.
  Total validation: sum of strategic weights must equal 100 (tolerance 0.1).
-->
<script lang="ts">
  import { formatNumber } from "@investintell/ui";

  interface BlockRow {
    blockId: string;
    name: string;
    strategicWeight: number;
    tacticalOverweight: number;
  }

  interface RegimeSuggestion {
    blockId: string;
    suggestedWeight: number;
  }

  interface WeightsEditorProps {
    blocks: BlockRow[];
    regimeSuggestions: RegimeSuggestion[] | null;
    onSave: (
      strategic: Array<{ blockId: string; weight: number }>,
      tactical: Array<{ blockId: string; overweight: number }>,
    ) => void;
    isSaving: boolean;
  }

  let { blocks, regimeSuggestions, onSave, isSaving }: WeightsEditorProps = $props();

  // Local editable state: display as 0-100 scale
  let editRows = $state<Array<{
    blockId: string;
    name: string;
    strategic: number;
    tactical: number;
    originalStrategic: number;
    originalTactical: number;
  }>>([]);

  // Sync from props when blocks change
  $effect(() => {
    editRows = blocks.map((b) => ({
      blockId: b.blockId,
      name: b.name,
      strategic: b.strategicWeight * 100,
      tactical: b.tacticalOverweight * 100,
      originalStrategic: b.strategicWeight * 100,
      originalTactical: b.tacticalOverweight * 100,
    }));
  });

  const strategicTotal = $derived(
    editRows.reduce((sum, r) => sum + r.strategic, 0),
  );

  const totalValid = $derived(Math.abs(strategicTotal - 100) < 0.1);
  const hasChanges = $derived(
    editRows.some(
      (r) =>
        Math.abs(r.strategic - r.originalStrategic) > 0.001 ||
        Math.abs(r.tactical - r.originalTactical) > 0.001,
    ),
  );

  const canSave = $derived(totalValid && hasChanges && !isSaving);

  function getRegimeSuggestion(blockId: string): number | null {
    if (!regimeSuggestions) return null;
    const s = regimeSuggestions.find((r) => r.blockId === blockId);
    return s ? s.suggestedWeight * 100 : null;
  }

  function handleSave() {
    if (!canSave) return;
    onSave(
      editRows.map((r) => ({ blockId: r.blockId, weight: r.strategic / 100 })),
      editRows.map((r) => ({ blockId: r.blockId, overweight: r.tactical / 100 })),
    );
  }

  function isModified(current: number, original: number): boolean {
    return Math.abs(current - original) > 0.001;
  }
</script>

<div class="we-root">
  <div class="we-table">
    <div class="we-header">
      <span class="we-col we-col--name">Block</span>
      <span class="we-col we-col--num">Strategic %</span>
      <span class="we-col we-col--num">Tactical +/-</span>
      <span class="we-col we-col--num">Effective %</span>
      <span class="we-col we-col--num">Regime Sug.</span>
    </div>

    {#each editRows as row, i (row.blockId)}
      {@const effective = row.strategic + row.tactical}
      {@const suggestion = getRegimeSuggestion(row.blockId)}
      <div class="we-row">
        <span class="we-col we-col--name">{row.name}</span>
        <span class="we-col we-col--num">
          <input
            type="number"
            class="we-input"
            class:we-input--modified={isModified(row.strategic, row.originalStrategic)}
            min="0"
            max="100"
            step="0.1"
            bind:value={row.strategic}
          />
        </span>
        <span class="we-col we-col--num">
          <input
            type="number"
            class="we-input we-input--tactical"
            class:we-input--modified={isModified(row.tactical, row.originalTactical)}
            min="-50"
            max="50"
            step="0.1"
            bind:value={row.tactical}
          />
        </span>
        <span
          class="we-col we-col--num we-effective"
          class:we-effective--warn={effective < 0 || effective > 100}
        >
          {formatNumber(effective, 1)}%
        </span>
        <span class="we-col we-col--num we-suggestion">
          {#if suggestion !== null}
            {formatNumber(suggestion, 1)}%
          {:else}
            --
          {/if}
        </span>
      </div>
    {/each}

    <div class="we-total" class:we-total--error={!totalValid}>
      <span class="we-col we-col--name">TOTAL</span>
      <span class="we-col we-col--num we-total-value">
        {formatNumber(strategicTotal, 1)}%
      </span>
      <span class="we-col we-col--num"></span>
      <span class="we-col we-col--num we-total-value">
        {formatNumber(
          editRows.reduce((s, r) => s + r.strategic + r.tactical, 0),
          1,
        )}%
      </span>
      <span class="we-col we-col--num"></span>
    </div>
  </div>

  <div class="we-actions">
    {#if !totalValid}
      <span class="we-validation-msg">Strategic weights must sum to 100%</span>
    {/if}
    <button
      type="button"
      class="we-save-btn"
      disabled={!canSave}
      onclick={handleSave}
    >
      {isSaving ? "SAVING..." : "SAVE WEIGHTS"}
    </button>
  </div>
</div>

<style>
  .we-root {
    display: flex;
    flex-direction: column;
    gap: var(--terminal-space-3);
    height: 100%;
    font-family: var(--terminal-font-mono);
  }

  .we-table {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    overflow-y: auto;
  }

  .we-header {
    display: flex;
    align-items: center;
    height: 28px;
    padding: 0 var(--terminal-space-2);
    border-bottom: var(--terminal-border-hairline);
    font-size: var(--terminal-text-10);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    color: var(--terminal-fg-muted);
    flex-shrink: 0;
  }

  .we-row {
    display: flex;
    align-items: center;
    height: 36px;
    padding: 0 var(--terminal-space-2);
    border-bottom: var(--terminal-border-hairline);
    font-size: var(--terminal-text-11);
    color: var(--terminal-fg-secondary);
  }

  .we-row:hover {
    background: var(--terminal-bg-panel-raised);
  }

  .we-col {
    display: flex;
    align-items: center;
  }

  .we-col--name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--terminal-fg-primary);
    font-weight: 600;
  }

  .we-col--num {
    width: 110px;
    flex-shrink: 0;
    justify-content: flex-end;
    font-variant-numeric: tabular-nums;
  }

  .we-input {
    width: 72px;
    height: 24px;
    padding: 0 var(--terminal-space-2);
    background: var(--terminal-bg-void);
    border: var(--terminal-border-hairline);
    border-radius: var(--terminal-radius-none);
    color: var(--terminal-fg-primary);
    font-family: var(--terminal-font-mono);
    font-size: var(--terminal-text-11);
    font-variant-numeric: tabular-nums;
    text-align: right;
    outline: none;
  }

  .we-input:focus {
    border-color: var(--terminal-accent-amber);
  }

  .we-input--modified {
    color: var(--terminal-accent-cyan);
  }

  .we-input--tactical {
    width: 64px;
  }

  .we-effective {
    color: var(--terminal-fg-primary);
  }

  .we-effective--warn {
    color: var(--terminal-status-error);
  }

  .we-suggestion {
    color: var(--terminal-fg-muted);
    font-style: italic;
  }

  .we-total {
    display: flex;
    align-items: center;
    height: 32px;
    padding: 0 var(--terminal-space-2);
    border-top: 1px solid var(--terminal-fg-muted);
    font-size: var(--terminal-text-11);
    font-weight: 700;
    color: var(--terminal-fg-primary);
    flex-shrink: 0;
  }

  .we-total--error {
    color: var(--terminal-status-error);
  }

  .we-total-value {
    font-variant-numeric: tabular-nums;
  }

  .we-actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: var(--terminal-space-3);
    padding: var(--terminal-space-2) 0;
    flex-shrink: 0;
  }

  .we-validation-msg {
    font-size: var(--terminal-text-10);
    color: var(--terminal-status-error);
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
  }

  .we-save-btn {
    height: 28px;
    padding: 0 var(--terminal-space-4);
    background: transparent;
    border: var(--terminal-border-hairline);
    border-radius: var(--terminal-radius-none);
    color: var(--terminal-accent-amber);
    font-family: var(--terminal-font-mono);
    font-size: var(--terminal-text-10);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    cursor: pointer;
    transition:
      border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
      background var(--terminal-motion-tick) var(--terminal-motion-easing-out);
  }

  .we-save-btn:hover:not(:disabled) {
    border-color: var(--terminal-accent-amber);
    background: var(--terminal-bg-panel-raised);
  }

  .we-save-btn:disabled {
    color: var(--terminal-fg-muted);
    cursor: not-allowed;
    opacity: 0.5;
  }
</style>
