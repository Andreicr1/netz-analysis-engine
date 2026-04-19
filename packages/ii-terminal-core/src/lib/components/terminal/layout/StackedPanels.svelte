<!--
  StackedPanels — vertical stack with hairline dividers between children.

  Used for Live bottom row (PortfolioSummary + DriftMonitorPanel stacked).
  Children are flexed vertically with equal weight by default.
-->
<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    children: Snippet;
  }

  let { children }: Props = $props();
</script>

<div class="sk-root">
  {@render children()}
</div>

<style>
  .sk-root {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    min-height: 0;
    overflow: hidden;
    background: var(--terminal-bg-void);
  }

  .sk-root > :global(*) {
    flex: 1;
    min-height: 0;
  }

  .sk-root > :global(* + *) {
    border-top: var(--terminal-border-hairline);
  }
</style>
