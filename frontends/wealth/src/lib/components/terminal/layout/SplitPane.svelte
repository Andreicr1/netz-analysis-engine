<!--
  SplitPane — CSS grid wrapper with named template columns.

  Used for Builder 2-column (40/60) and Live 3-column layouts.
  The `columns` prop is a raw CSS grid-template-columns string.
-->
<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    /** CSS grid-template-columns value (e.g. "2fr 3fr", "1fr 1fr 1fr"). */
    columns: string;
    /** Gap between grid children. Default: 1px (hairline). */
    gap?: string;
    children: Snippet;
  }

  let {
    columns,
    gap = "1px",
    children,
  }: Props = $props();
</script>

<div
  class="sp-root"
  style:grid-template-columns={columns}
  style:gap={gap}
>
  {@render children()}
</div>

<style>
  .sp-root {
    display: grid;
    width: 100%;
    height: 100%;
    min-height: 0;
    overflow: hidden;
    background: var(--terminal-bg-void);
  }
</style>
