<!--
  SparklineWall — grid of macro indicator mini sparklines.

  Each cell: indicator name, current value + trend arrow, mini line chart.
  Terminal tokens only. ECharts via TerminalChart wrapper.
-->
<script lang="ts">
  import { createTerminalChartOptions } from "@investintell/ui";
  import { formatNumber } from "@investintell/ui/utils";
  import TerminalChart from "$lib/components/terminal/charts/TerminalChart.svelte";

  interface Indicator {
    name: string;
    currentValue: number;
    previousValue: number;
    history: Array<{ date: string; value: number }>;
    unit: string;
  }

  interface Props {
    indicators: Indicator[];
  }

  let { indicators }: Props = $props();

  function trendArrow(current: number, previous: number): string {
    if (current > previous) return "\u25B2";
    if (current < previous) return "\u25BC";
    return "\u25C6";
  }

  function trendColor(current: number, previous: number): string {
    if (current > previous) return "var(--terminal-status-success)";
    if (current < previous) return "var(--terminal-status-error)";
    return "var(--terminal-fg-secondary)";
  }

  function formatUnit(value: number, unit: string): string {
    if (unit === "%") return formatNumber(value, 1) + "%";
    if (unit === "bps") return formatNumber(value, 0) + " bps";
    if (unit === "idx") return formatNumber(value, 1);
    return formatNumber(value, 2);
  }

  function buildSparkOption(history: Array<{ date: string; value: number }>) {
    const data = history.map((pt) => [new Date(pt.date).getTime(), pt.value] as [number, number]);
    return createTerminalChartOptions({
      slot: "tail",
      showXAxisLabels: false,
      showYAxisLabels: false,
      disableAnimation: true,
      series: [
        {
          type: "line",
          showSymbol: false,
          smooth: true,
          lineStyle: { width: 1.25 },
          data,
        },
      ],
      xAxis: { type: "time", show: false },
      yAxis: { type: "value", show: false },
    });
  }
</script>

<div class="sw-root">
  {#each indicators as ind (ind.name)}
    <div class="sw-cell">
      <div class="sw-meta">
        <span class="sw-name">{ind.name}</span>
        <div class="sw-value-row">
          <span class="sw-value">{formatUnit(ind.currentValue, ind.unit)}</span>
          <span class="sw-arrow" style:color={trendColor(ind.currentValue, ind.previousValue)}>
            {trendArrow(ind.currentValue, ind.previousValue)}
          </span>
        </div>
      </div>
      {#if ind.history.length > 1}
        <div class="sw-chart">
          <TerminalChart
            option={buildSparkOption(ind.history)}
            renderer="svg"
            height={48}
            ariaLabel="{ind.name} sparkline"
          />
        </div>
      {/if}
    </div>
  {/each}
</div>

<style>
  .sw-root {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: var(--terminal-space-2);
    font-family: var(--terminal-font-mono);
    width: 100%;
  }

  .sw-cell {
    display: flex;
    flex-direction: column;
    gap: var(--terminal-space-1);
    padding: var(--terminal-space-2);
    background: var(--terminal-bg-panel);
    border: var(--terminal-border-hairline);
  }

  .sw-meta {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .sw-name {
    font-size: var(--terminal-text-10);
    font-weight: 600;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    color: var(--terminal-fg-tertiary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .sw-value-row {
    display: flex;
    align-items: baseline;
    gap: var(--terminal-space-1);
  }

  .sw-value {
    font-size: var(--terminal-text-12);
    font-weight: 600;
    color: var(--terminal-fg-primary);
    font-variant-numeric: tabular-nums;
  }

  .sw-arrow {
    font-size: var(--terminal-text-10);
    font-weight: 700;
  }

  .sw-chart {
    flex: 1;
    min-height: 0;
  }

  /* Override chart wrapper border inside sparkline cells */
  .sw-chart :global(.terminal-chart) {
    border: none;
  }
</style>
