<!--
  SignalBreakdown — two-column signal panel for regime stress decomposition.

  Left: financial signals. Right: real economy signals.
  Each row shows label, raw value, stress bar, and weight amplification.
  Terminal tokens only. No hex. No radius.
-->
<script lang="ts">
  import { formatNumber } from "@investintell/ui/utils";

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

  interface Props {
    signals: RegimeSignalRead[];
  }

  let { signals }: Props = $props();

  const financialSignals = $derived(
    signals
      .filter((s) => s.category === "financial")
      .sort((a, b) => b.weight_effective - a.weight_effective),
  );

  const realEconSignals = $derived(
    signals
      .filter((s) => s.category === "real_economy")
      .sort((a, b) => b.weight_effective - a.weight_effective),
  );

  function stressColor(score: number): string {
    if (score < 33) return "var(--terminal-status-ok, var(--terminal-status-success))";
    if (score < 66) return "var(--terminal-accent-amber)";
    return "var(--terminal-status-error)";
  }

  function formatRawValue(value: number | null, unit: string): string {
    if (value == null) return "--";
    const formatted = formatNumber(value, 2);
    if (unit === "%") return formatted + "%";
    if (unit) return formatted + unit;
    return formatted;
  }

  function weightColor(base: number, effective: number): string {
    if (effective > base * 1.2) return "var(--terminal-accent-amber)";
    return "var(--terminal-fg-muted)";
  }
</script>

<div class="sb-root">
  <div class="sb-column">
    <span class="sb-column-header">FINANCIAL SIGNALS ({financialSignals.length})</span>
    {#each financialSignals as sig (sig.key)}
      {@const color = stressColor(sig.stress_score)}
      <div class="sb-row">
        <div class="sb-row-top">
          <span class="sb-label">{sig.label.toUpperCase()}</span>
          <span class="sb-value">{formatRawValue(sig.raw_value, sig.unit)}</span>
          <span class="sb-stress" style:color={color}>{formatNumber(sig.stress_score, 0)}/100</span>
        </div>
        <div class="sb-row-bottom">
          <div class="sb-bar">
            <div
              class="sb-bar-fill"
              style:width="{Math.min(100, Math.max(0, sig.stress_score))}%"
              style:background={color}
            ></div>
          </div>
          <span class="sb-weight" style:color={weightColor(sig.weight_base, sig.weight_effective)}>
            w: {formatNumber(sig.weight_base, 2)} &rarr; {formatNumber(sig.weight_effective, 2)}
          </span>
        </div>
      </div>
    {/each}
  </div>

  <div class="sb-column">
    <span class="sb-column-header">REAL ECONOMY SIGNALS ({realEconSignals.length})</span>
    {#each realEconSignals as sig (sig.key)}
      {@const color = stressColor(sig.stress_score)}
      <div class="sb-row">
        <div class="sb-row-top">
          <span class="sb-label">{sig.label.toUpperCase()}</span>
          <span class="sb-value">{formatRawValue(sig.raw_value, sig.unit)}</span>
          <span class="sb-stress" style:color={color}>{formatNumber(sig.stress_score, 0)}/100</span>
        </div>
        <div class="sb-row-bottom">
          <div class="sb-bar">
            <div
              class="sb-bar-fill"
              style:width="{Math.min(100, Math.max(0, sig.stress_score))}%"
              style:background={color}
            ></div>
          </div>
          <span class="sb-weight" style:color={weightColor(sig.weight_base, sig.weight_effective)}>
            w: {formatNumber(sig.weight_base, 2)} &rarr; {formatNumber(sig.weight_effective, 2)}
          </span>
        </div>
      </div>
    {/each}
  </div>
</div>

<style>
  .sb-root {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--terminal-space-4);
    padding: var(--terminal-space-3);
    background: var(--terminal-bg-panel);
    border: var(--terminal-border-hairline);
    font-family: var(--terminal-font-mono);
    flex-shrink: 0;
  }

  .sb-column {
    display: flex;
    flex-direction: column;
    gap: var(--terminal-space-3);
  }

  .sb-column-header {
    font-size: var(--terminal-text-10);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    color: var(--terminal-fg-tertiary);
    text-transform: uppercase;
    padding-bottom: var(--terminal-space-1);
    border-bottom: var(--terminal-border-hairline);
  }

  .sb-row {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .sb-row-top {
    display: flex;
    align-items: baseline;
    gap: var(--terminal-space-2);
  }

  .sb-label {
    width: 120px;
    flex-shrink: 0;
    font-size: var(--terminal-text-10);
    font-weight: 600;
    letter-spacing: var(--terminal-tracking-caps);
    color: var(--terminal-fg-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .sb-value {
    flex: 1;
    text-align: right;
    font-size: var(--terminal-text-11);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--terminal-fg-primary);
  }

  .sb-stress {
    flex-shrink: 0;
    font-size: var(--terminal-text-10);
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }

  .sb-row-bottom {
    display: flex;
    align-items: center;
    gap: var(--terminal-space-2);
  }

  .sb-bar {
    flex: 1;
    height: 4px;
    background: var(--terminal-fg-muted);
    position: relative;
  }

  .sb-bar-fill {
    position: absolute;
    top: 0;
    left: 0;
    height: 100%;
    transition: width var(--terminal-motion-update) var(--terminal-motion-easing-out);
  }

  .sb-weight {
    flex-shrink: 0;
    font-size: var(--terminal-text-10);
    font-variant-numeric: tabular-nums;
  }
</style>
