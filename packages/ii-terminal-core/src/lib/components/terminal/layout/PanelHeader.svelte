<!--
  PanelHeader — 28px terminal panel header with monospace uppercase label.

  Optional right-slot for action buttons. Extracted from the repeated
  pattern in PortfolioSummary, DriftMonitorPanel, and Builder tabs.
-->
<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    label: string;
    /** Optional right-aligned actions slot. */
    actions?: Snippet;
  }

  let { label, actions }: Props = $props();
</script>

<div class="ph-root">
  <span class="ph-label">{label}</span>
  {#if actions}
    <div class="ph-actions">
      {@render actions()}
    </div>
  {/if}
</div>

<style>
  .ph-root {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    height: 28px;
    font-family: var(--terminal-font-mono);
  }

  .ph-label {
    font-size: var(--terminal-text-10);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    color: var(--terminal-fg-tertiary);
    text-transform: uppercase;
  }

  .ph-actions {
    display: flex;
    align-items: center;
    gap: var(--terminal-space-2);
  }
</style>
