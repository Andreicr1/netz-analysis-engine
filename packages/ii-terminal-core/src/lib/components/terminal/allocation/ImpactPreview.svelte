<!--
  ImpactPreview.svelte — right-side panel showing effective allocation
  visualization, regime state, simulation trigger, and builder link.

  Terminal-native: no hex, no radius, mono font, TerminalChart only.
-->
<script lang="ts">
  import { goto } from "$app/navigation";
  import { base } from "$app/paths";
  import { formatNumber, formatPercent, createTerminalChartOptions } from "@investintell/ui";
  import TerminalChart from "../../../components/terminal/charts/TerminalChart.svelte";

  interface EffectiveEntry {
    name: string;
    weight: number;
  }

  interface SimResult {
    proposedCvar: number | null;
    cvarLimit: number | null;
    cvarUtilization: number | null;
    cvarDelta: number | null;
    withinLimit: boolean;
    warnings: string[];
  }

  interface ImpactPreviewProps {
    effective: EffectiveEntry[];
    regime: string;
    simulationResult: SimResult | null;
    onSimulate: () => void;
    isSimulating: boolean;
  }

  let { effective, regime, simulationResult, onSimulate, isSimulating }: ImpactPreviewProps =
    $props();

  // Regime label sanitization + color mapping
  const REGIME_MAP: Record<string, { label: string; colorVar: string }> = {
    REGIME_NORMAL: { label: "Normal", colorVar: "var(--terminal-status-ok)" },
    normal: { label: "Normal", colorVar: "var(--terminal-status-ok)" },
    REGIME_RISK_ON: { label: "Risk On", colorVar: "var(--terminal-accent-cyan)" },
    risk_on: { label: "Risk On", colorVar: "var(--terminal-accent-cyan)" },
    REGIME_RISK_OFF: { label: "Risk Off", colorVar: "var(--terminal-accent-amber)" },
    risk_off: { label: "Risk Off", colorVar: "var(--terminal-accent-amber)" },
    REGIME_CRISIS: { label: "Crisis", colorVar: "var(--terminal-status-error)" },
    crisis: { label: "Crisis", colorVar: "var(--terminal-status-error)" },
  };

  const regimeDisplay = $derived(REGIME_MAP[regime] ?? { label: regime, colorVar: "var(--terminal-fg-muted)" });

  // Stacked bar chart for effective allocation
  const chartOption = $derived.by(() => {
    if (effective.length === 0) return null;

    const sorted = [...effective].sort((a, b) => b.weight - a.weight);
    const data = sorted.map((e) => ({
      name: e.name,
      value: +(e.weight * 100).toFixed(1),
    }));

    return createTerminalChartOptions({
      series: [
        {
          type: "bar",
          data: data.map((d) => d.value),
          barWidth: 16,
          label: {
            show: true,
            position: "right",
            formatter: "{c}%",
            fontSize: 10,
          },
        },
      ],
      xAxis: {
        type: "value",
        min: 0,
        max: 100,
        axisLabel: {
          formatter: "{value}%",
        },
      },
      yAxis: {
        type: "category",
        data: data.map((d) => d.name),
        inverse: true,
        axisLabel: {
          fontSize: 10,
          width: 80,
          overflow: "truncate",
        },
      },
      slot: "secondary",
      showLegend: false,
    });
  });

  function handleBuilderNav() {
    goto(`${base}/portfolio/builder?alloc=default`);
  }
</script>

<div class="ip-root">
  <!-- Regime badge -->
  <div class="ip-regime">
    <span class="ip-regime-label">REGIME</span>
    <span class="ip-regime-value" style:color={regimeDisplay.colorVar}>
      {regimeDisplay.label}
    </span>
  </div>

  <!-- Effective allocation chart -->
  <div class="ip-chart">
    {#if chartOption}
      <TerminalChart option={chartOption} ariaLabel="Effective allocation breakdown" />
    {:else}
      <div class="ip-empty">No allocation data</div>
    {/if}
  </div>

  <!-- Simulation section -->
  <div class="ip-sim">
    <button
      type="button"
      class="ip-sim-btn"
      disabled={isSimulating}
      onclick={onSimulate}
      title="Simulation requires portfolio instruments — block-level simulation coming soon"
    >
      {isSimulating ? "SIMULATING..." : "SIMULATE"}
    </button>

    {#if simulationResult}
      <div class="ip-sim-results">
        {#if simulationResult.proposedCvar !== null}
          <div class="ip-sim-row">
            <span class="ip-sim-label">CVaR (95%, 3M)</span>
            <span class="ip-sim-value">
              {formatPercent(simulationResult.proposedCvar, 2)}
            </span>
          </div>
        {/if}
        {#if simulationResult.cvarUtilization !== null}
          <div class="ip-sim-row">
            <span class="ip-sim-label">Risk Budget Used</span>
            <span class="ip-sim-value">
              {formatNumber(simulationResult.cvarUtilization, 1)}%
            </span>
          </div>
        {/if}
        {#if simulationResult.cvarDelta !== null}
          <div class="ip-sim-row">
            <span class="ip-sim-label">Risk Change</span>
            <span
              class="ip-sim-value"
              class:ip-sim-value--positive={simulationResult.cvarDelta > 0}
              class:ip-sim-value--negative={simulationResult.cvarDelta < 0}
            >
              {simulationResult.cvarDelta > 0 ? "+" : ""}
              {formatPercent(simulationResult.cvarDelta, 3)}
            </span>
          </div>
        {/if}
        <div class="ip-sim-row">
          <span class="ip-sim-label">Within Limit</span>
          <span
            class="ip-sim-value"
            class:ip-sim-value--ok={simulationResult.withinLimit}
            class:ip-sim-value--breach={!simulationResult.withinLimit}
          >
            {simulationResult.withinLimit ? "YES" : "NO"}
          </span>
        </div>
        {#if simulationResult.warnings.length > 0}
          <div class="ip-sim-warnings">
            {#each simulationResult.warnings as warn}
              <p class="ip-sim-warn">{warn}</p>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  </div>

  <!-- Builder navigation -->
  <div class="ip-nav">
    <button type="button" class="ip-builder-btn" onclick={handleBuilderNav}>
      -&gt; BUILDER
    </button>
  </div>
</div>

<style>
  .ip-root {
    display: flex;
    flex-direction: column;
    gap: var(--terminal-space-3);
    height: 100%;
    font-family: var(--terminal-font-mono);
  }

  .ip-regime {
    display: flex;
    align-items: baseline;
    gap: var(--terminal-space-2);
    padding: var(--terminal-space-2) 0;
    border-bottom: var(--terminal-border-hairline);
    flex-shrink: 0;
  }

  .ip-regime-label {
    font-size: var(--terminal-text-10);
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    color: var(--terminal-fg-muted);
  }

  .ip-regime-value {
    font-size: var(--terminal-text-14);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
  }

  .ip-chart {
    flex: 1;
    min-height: 120px;
    max-height: 300px;
  }

  .ip-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    font-size: var(--terminal-text-11);
    color: var(--terminal-fg-muted);
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
  }

  .ip-sim {
    display: flex;
    flex-direction: column;
    gap: var(--terminal-space-2);
    flex-shrink: 0;
  }

  .ip-sim-btn {
    width: 100%;
    height: 28px;
    background: transparent;
    border: var(--terminal-border-hairline);
    border-radius: var(--terminal-radius-none);
    color: var(--terminal-accent-cyan);
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

  .ip-sim-btn:hover:not(:disabled) {
    border-color: var(--terminal-accent-cyan);
    background: var(--terminal-bg-panel-raised);
  }

  .ip-sim-btn:disabled {
    color: var(--terminal-fg-muted);
    cursor: not-allowed;
    opacity: 0.5;
  }

  .ip-sim-results {
    display: flex;
    flex-direction: column;
    gap: var(--terminal-space-1);
    padding: var(--terminal-space-2);
    border: var(--terminal-border-hairline);
  }

  .ip-sim-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    font-size: var(--terminal-text-11);
  }

  .ip-sim-label {
    color: var(--terminal-fg-muted);
    font-size: var(--terminal-text-10);
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
  }

  .ip-sim-value {
    font-variant-numeric: tabular-nums;
    color: var(--terminal-fg-primary);
    font-weight: 600;
  }

  .ip-sim-value--positive {
    color: var(--terminal-status-error);
  }

  .ip-sim-value--negative {
    color: var(--terminal-status-ok);
  }

  .ip-sim-value--ok {
    color: var(--terminal-status-ok);
  }

  .ip-sim-value--breach {
    color: var(--terminal-status-error);
  }

  .ip-sim-warnings {
    padding-top: var(--terminal-space-1);
    border-top: var(--terminal-border-hairline);
  }

  .ip-sim-warn {
    font-size: var(--terminal-text-10);
    color: var(--terminal-fg-muted);
    margin: 0;
    line-height: 1.4;
  }

  .ip-nav {
    flex-shrink: 0;
    padding-top: var(--terminal-space-2);
    border-top: var(--terminal-border-hairline);
  }

  .ip-builder-btn {
    width: 100%;
    height: 32px;
    background: transparent;
    border: var(--terminal-border-hairline);
    border-radius: var(--terminal-radius-none);
    color: var(--terminal-accent-amber);
    font-family: var(--terminal-font-mono);
    font-size: var(--terminal-text-11);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    cursor: pointer;
    transition:
      border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
      background var(--terminal-motion-tick) var(--terminal-motion-easing-out);
  }

  .ip-builder-btn:hover {
    border-color: var(--terminal-accent-amber);
    background: var(--terminal-bg-panel-raised);
  }
</style>
