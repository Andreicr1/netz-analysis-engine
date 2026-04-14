<!--
  RegionalHealthTile — regional macro health tile for the macro desk.

  Displays composite score and dimension progress bars for a single
  region (US / EU / JP / EM). No regime badge. Terminal tokens only.
-->
<script lang="ts">
  import { formatNumber } from "@investintell/ui/utils";

  interface DimensionScore {
    name: string;
    score: number;
  }

  interface Props {
    region: string;
    compositeScore: number;
    dimensions: DimensionScore[];
  }

  let { region, compositeScore, dimensions }: Props = $props();

  const DIMENSION_LABELS: Record<string, string> = {
    growth: "Growth",
    inflation: "Inflation",
    employment: "Employment",
    financial_conditions: "Fin. Conditions",
  };

  function dimensionLabel(raw: string): string {
    return DIMENSION_LABELS[raw] ?? raw.replace(/_/g, " ");
  }
</script>

<div class="rht-root">
  <div class="rht-header">
    <span class="rht-region">{region}</span>
  </div>

  <div class="rht-score">
    <span class="rht-score-value">{formatNumber(compositeScore, 0)}</span>
    <span class="rht-score-unit">/100</span>
  </div>

  <div class="rht-dimensions">
    {#each dimensions as dim (dim.name)}
      <div class="rht-dim">
        <span class="rht-dim-label">{dimensionLabel(dim.name)}</span>
        <div class="rht-dim-bar">
          <div class="rht-dim-fill" style:width="{Math.min(100, Math.max(0, dim.score))}%"></div>
        </div>
        <span class="rht-dim-value">{formatNumber(dim.score, 0)}</span>
      </div>
    {/each}
  </div>
</div>

<style>
  .rht-root {
    display: flex;
    flex-direction: column;
    gap: var(--terminal-space-3);
    padding: var(--terminal-space-3);
    background: var(--terminal-bg-panel);
    border: var(--terminal-border-hairline);
    font-family: var(--terminal-font-mono);
    height: 100%;
  }

  .rht-header {
    display: flex;
    align-items: center;
  }

  .rht-region {
    font-size: var(--terminal-text-12);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    color: var(--terminal-fg-primary);
  }

  .rht-score {
    display: flex;
    align-items: baseline;
    gap: 2px;
  }

  .rht-score-value {
    font-size: var(--terminal-text-24);
    font-weight: 700;
    color: var(--terminal-accent-amber);
    font-variant-numeric: tabular-nums;
  }

  .rht-score-unit {
    font-size: var(--terminal-text-11);
    color: var(--terminal-fg-tertiary);
  }

  .rht-dimensions {
    display: flex;
    flex-direction: column;
    gap: var(--terminal-space-2);
  }

  .rht-dim {
    display: grid;
    grid-template-columns: 90px 1fr 24px;
    align-items: center;
    gap: var(--terminal-space-2);
  }

  .rht-dim-label {
    font-size: var(--terminal-text-10);
    color: var(--terminal-fg-secondary);
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .rht-dim-bar {
    height: 4px;
    background: var(--terminal-fg-muted);
    position: relative;
  }

  .rht-dim-fill {
    position: absolute;
    top: 0;
    left: 0;
    height: 100%;
    background: var(--terminal-accent-amber);
    transition: width var(--terminal-motion-update) var(--terminal-motion-easing-out);
  }

  .rht-dim-value {
    font-size: var(--terminal-text-10);
    font-weight: 600;
    color: var(--terminal-fg-secondary);
    font-variant-numeric: tabular-nums;
    text-align: right;
  }
</style>
