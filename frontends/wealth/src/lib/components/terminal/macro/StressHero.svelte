<!--
  StressHero — full-width stress score banner for the macro desk.

  Displays global regime stress score as a horizontal bar with
  dynamic weight category breakdown and regime pin/proceed actions.
  Terminal tokens only. No hex. No radius.
-->
<script lang="ts">
  import { formatNumber, formatShortDate } from "@investintell/ui/utils";

  interface Props {
    stressScore: number;
    regimeLabel: string;
    asOfDate: string;
    financialEffWeight: number;
    realEconEffWeight: number;
    isPinned: boolean;
    onPin: () => void;
    onUnpin: () => void;
    onProceedToAlloc: () => void;
  }

  let {
    stressScore,
    regimeLabel,
    asOfDate,
    financialEffWeight,
    realEconEffWeight,
    isPinned,
    onPin,
    onUnpin,
    onProceedToAlloc,
  }: Props = $props();

  function stressColor(score: number): string {
    if (score < 33) return "var(--terminal-status-ok, var(--terminal-status-success))";
    if (score < 66) return "var(--terminal-accent-amber)";
    return "var(--terminal-status-error)";
  }

  const fillColor = $derived(stressColor(stressScore));
  const fillPct = $derived(Math.min(100, Math.max(0, stressScore)));

  const financialPct = $derived(
    financialEffWeight + realEconEffWeight > 0
      ? formatNumber((financialEffWeight / (financialEffWeight + realEconEffWeight)) * 100, 0)
      : "0"
  );

  const realEconPct = $derived(
    financialEffWeight + realEconEffWeight > 0
      ? formatNumber((realEconEffWeight / (financialEffWeight + realEconEffWeight)) * 100, 0)
      : "0"
  );
</script>

<div class="sh-root">
  <div class="sh-top">
    <div class="sh-score-group">
      <span class="sh-score" style:color={fillColor}>{formatNumber(stressScore, 0)}</span>
      <span class="sh-regime">{regimeLabel.toUpperCase()}</span>
    </div>
    <span class="sh-date">as of {formatShortDate(new Date(asOfDate))}</span>
  </div>

  <div class="sh-bar-wrap">
    <div class="sh-bar">
      <div class="sh-bar-fill" style:width="{fillPct}%" style:background={fillColor}></div>
    </div>
    <div class="sh-bar-ticks">
      <div class="sh-tick" style:left="33%"></div>
      <div class="sh-tick" style:left="66%"></div>
    </div>
    <span class="sh-bar-label">/100</span>
  </div>

  <div class="sh-bottom">
    <div class="sh-weights">
      <span class="sh-weight">FINANCIAL {financialPct}%</span>
      <span class="sh-weight">REAL ECONOMY {realEconPct}%</span>
    </div>
    <div class="sh-actions">
      {#if isPinned}
        <button type="button" class="sh-btn sh-btn--active" onclick={onUnpin}>UNPIN</button>
      {:else}
        <button type="button" class="sh-btn" onclick={onPin}>PIN REGIME</button>
      {/if}
      <button type="button" class="sh-btn sh-btn--proceed" onclick={onProceedToAlloc}>
        PROCEED TO ALLOC &rarr;
      </button>
    </div>
  </div>
</div>

<style>
  .sh-root {
    display: flex;
    flex-direction: column;
    gap: var(--terminal-space-2);
    padding: var(--terminal-space-3) var(--terminal-space-4);
    background: var(--terminal-bg-panel);
    border: var(--terminal-border-hairline);
    font-family: var(--terminal-font-mono);
    flex-shrink: 0;
  }

  .sh-top {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
  }

  .sh-score-group {
    display: flex;
    align-items: baseline;
    gap: var(--terminal-space-3);
  }

  .sh-score {
    font-size: 32px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    line-height: 1;
  }

  .sh-regime {
    font-size: var(--terminal-text-16, 16px);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    color: var(--terminal-fg-primary);
  }

  .sh-date {
    font-size: var(--terminal-text-10);
    color: var(--terminal-fg-muted);
    letter-spacing: var(--terminal-tracking-caps);
  }

  .sh-bar-wrap {
    position: relative;
    display: flex;
    align-items: center;
    gap: var(--terminal-space-2);
  }

  .sh-bar {
    flex: 1;
    height: 6px;
    background: var(--terminal-fg-muted);
    position: relative;
  }

  .sh-bar-fill {
    position: absolute;
    top: 0;
    left: 0;
    height: 100%;
    transition: width var(--terminal-motion-update) var(--terminal-motion-easing-out);
  }

  .sh-bar-ticks {
    position: absolute;
    top: 0;
    left: 0;
    right: 40px;
    height: 6px;
    pointer-events: none;
  }

  .sh-tick {
    position: absolute;
    top: -2px;
    width: 1px;
    height: 10px;
    background: var(--terminal-fg-tertiary);
  }

  .sh-bar-label {
    font-size: var(--terminal-text-10);
    color: var(--terminal-fg-muted);
    font-variant-numeric: tabular-nums;
    flex-shrink: 0;
  }

  .sh-bottom {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .sh-weights {
    display: flex;
    gap: var(--terminal-space-4);
  }

  .sh-weight {
    font-size: var(--terminal-text-10);
    font-weight: 600;
    letter-spacing: var(--terminal-tracking-caps);
    color: var(--terminal-fg-tertiary);
  }

  .sh-actions {
    display: flex;
    gap: var(--terminal-space-2);
  }

  .sh-btn {
    display: inline-flex;
    align-items: center;
    padding: 2px var(--terminal-space-2);
    background: transparent;
    border: var(--terminal-border-hairline);
    border-radius: 0;
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

  .sh-btn:hover {
    border-color: var(--terminal-accent-amber);
    color: var(--terminal-accent-amber);
  }

  .sh-btn--active {
    border-color: var(--terminal-accent-cyan);
    color: var(--terminal-accent-cyan);
  }

  .sh-btn--active:hover {
    border-color: var(--terminal-status-error);
    color: var(--terminal-status-error);
  }

  .sh-btn--proceed {
    border-color: var(--terminal-accent-cyan);
    color: var(--terminal-accent-cyan);
  }

  .sh-btn--proceed:hover {
    border-color: var(--terminal-fg-primary);
    color: var(--terminal-fg-primary);
  }
</style>
