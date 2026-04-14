<!--
  RegimeTile — regional macro regime tile for the macro desk.

  Displays composite score, regime badge, and dimension progress bars
  for a single region (US / EU / JP / EM). Terminal tokens only.
-->
<script lang="ts">
  interface DimensionScore {
    name: string;
    score: number;
  }

  interface Props {
    region: string;
    compositeScore: number;
    regime: string;
    dimensions: DimensionScore[];
  }

  let { region, compositeScore, regime, dimensions }: Props = $props();

  const REGIME_COLORS: Record<string, string> = {
    Expansion: "var(--terminal-status-success)",
    Cautious: "var(--terminal-accent-amber)",
    Stress: "var(--terminal-status-error)",
  };

  const regimeColor = $derived(REGIME_COLORS[regime] ?? "var(--terminal-fg-secondary)");

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

<div class="rt-root">
  <div class="rt-header">
    <span class="rt-region">{region}</span>
    <span class="rt-regime-badge" style:color={regimeColor} style:border-color={regimeColor}>
      {regime}
    </span>
  </div>

  <div class="rt-score">
    <span class="rt-score-value">{Math.round(compositeScore)}</span>
    <span class="rt-score-unit">/100</span>
  </div>

  <div class="rt-dimensions">
    {#each dimensions as dim (dim.name)}
      <div class="rt-dim">
        <span class="rt-dim-label">{dimensionLabel(dim.name)}</span>
        <div class="rt-dim-bar">
          <div class="rt-dim-fill" style:width="{Math.min(100, Math.max(0, dim.score))}%"></div>
        </div>
        <span class="rt-dim-value">{Math.round(dim.score)}</span>
      </div>
    {/each}
  </div>
</div>

<style>
  .rt-root {
    display: flex;
    flex-direction: column;
    gap: var(--terminal-space-3);
    padding: var(--terminal-space-3);
    background: var(--terminal-bg-panel);
    border: var(--terminal-border-hairline);
    font-family: var(--terminal-font-mono);
    height: 100%;
  }

  .rt-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .rt-region {
    font-size: var(--terminal-text-12);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    color: var(--terminal-fg-primary);
  }

  .rt-regime-badge {
    font-size: var(--terminal-text-10);
    font-weight: 600;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    padding: 2px 6px;
    border: 1px solid;
  }

  .rt-score {
    display: flex;
    align-items: baseline;
    gap: 2px;
  }

  .rt-score-value {
    font-size: var(--terminal-text-24);
    font-weight: 700;
    color: var(--terminal-accent-amber);
    font-variant-numeric: tabular-nums;
  }

  .rt-score-unit {
    font-size: var(--terminal-text-11);
    color: var(--terminal-fg-tertiary);
  }

  .rt-dimensions {
    display: flex;
    flex-direction: column;
    gap: var(--terminal-space-2);
  }

  .rt-dim {
    display: grid;
    grid-template-columns: 90px 1fr 24px;
    align-items: center;
    gap: var(--terminal-space-2);
  }

  .rt-dim-label {
    font-size: var(--terminal-text-10);
    color: var(--terminal-fg-secondary);
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .rt-dim-bar {
    height: 4px;
    background: var(--terminal-fg-muted);
    position: relative;
  }

  .rt-dim-fill {
    position: absolute;
    top: 0;
    left: 0;
    height: 100%;
    background: var(--terminal-accent-amber);
    transition: width var(--terminal-motion-update) var(--terminal-motion-easing-out);
  }

  .rt-dim-value {
    font-size: var(--terminal-text-10);
    font-weight: 600;
    color: var(--terminal-fg-secondary);
    font-variant-numeric: tabular-nums;
    text-align: right;
  }
</style>
