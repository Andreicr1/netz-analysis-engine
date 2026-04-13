<!--
  Panel — Layer 2 layout primitive for terminal panels.

  Slot-based composition: header, default (body), footer.
  Uses terminal tokens exclusively. Zero hex. Zero radius.
-->
<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    /** Remove body padding (for tables/charts that bleed to edges). */
    flush?: boolean;
    /** Enable vertical scrolling in the body slot. */
    scrollable?: boolean;
    /** Optional header snippet. When provided, renders 28px chrome strip. */
    header?: Snippet;
    /** Optional footer snippet. When provided, renders border-top strip. */
    footer?: Snippet;
    /** Default body content. */
    children: Snippet;
  }

  let {
    flush = false,
    scrollable = false,
    header,
    footer,
    children,
  }: Props = $props();
</script>

<div class="tp-root">
  {#if header}
    <div class="tp-header">
      {@render header()}
    </div>
  {/if}

  <div
    class="tp-body"
    class:tp-body--flush={flush}
    class:tp-body--scrollable={scrollable}
  >
    {@render children()}
  </div>

  {#if footer}
    <div class="tp-footer">
      {@render footer()}
    </div>
  {/if}
</div>

<style>
  .tp-root {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    min-height: 0;
    overflow: hidden;
    background: var(--terminal-bg-panel);
    font-family: var(--terminal-font-mono);
    border-radius: var(--terminal-radius-none);
  }

  .tp-header {
    display: flex;
    align-items: center;
    flex-shrink: 0;
    height: 28px;
    padding: 0 var(--terminal-space-3);
    border-bottom: var(--terminal-border-hairline);
  }

  .tp-body {
    flex: 1;
    min-height: 0;
    padding: var(--terminal-space-3);
  }

  .tp-body--flush {
    padding: 0;
  }

  .tp-body--scrollable {
    overflow-y: auto;
  }

  .tp-footer {
    flex-shrink: 0;
    padding: var(--terminal-space-2) var(--terminal-space-3);
    border-top: var(--terminal-border-hairline);
  }
</style>
