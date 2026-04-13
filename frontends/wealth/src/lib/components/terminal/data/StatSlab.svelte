<!--
  StatSlab — label + value + optional delta indicator.

  Extracted from PortfolioSummary KPI rows and BacktestTab metrics.
  Monospace typography, tabular-nums, terminal tokens only.
-->
<script lang="ts">
  interface Props {
    label: string;
    value: string;
    /** Optional delta string (e.g. "+2.4%"). */
    delta?: string | null;
    /** Color for the delta text. Maps to terminal status/accent tokens. */
    deltaColor?: "success" | "warn" | "error" | "muted" | "cyan" | "amber";
  }

  let {
    label,
    value,
    delta = null,
    deltaColor = "muted",
  }: Props = $props();

  const colorMap: Record<string, string> = {
    success: "var(--terminal-status-success)",
    warn: "var(--terminal-status-warn)",
    error: "var(--terminal-status-error)",
    muted: "var(--terminal-fg-muted)",
    cyan: "var(--terminal-accent-cyan)",
    amber: "var(--terminal-accent-amber)",
  };

  const resolvedColor = $derived(colorMap[deltaColor] ?? colorMap.muted);
</script>

<div class="ss-root">
  <span class="ss-label">{label}</span>
  <div class="ss-value-row">
    <span class="ss-value">{value}</span>
    {#if delta}
      <span class="ss-delta" style:color={resolvedColor}>{delta}</span>
    {/if}
  </div>
</div>

<style>
  .ss-root {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-family: var(--terminal-font-mono);
  }

  .ss-label {
    font-size: var(--terminal-text-10);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    color: var(--terminal-fg-tertiary);
  }

  .ss-value-row {
    display: flex;
    align-items: baseline;
    gap: var(--terminal-space-2);
  }

  .ss-value {
    font-size: var(--terminal-text-14);
    font-weight: 600;
    color: var(--terminal-fg-primary);
    font-variant-numeric: tabular-nums;
  }

  .ss-delta {
    font-size: var(--terminal-text-11);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
</style>
