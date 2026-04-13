<!--
  KeyValueStrip — horizontal strip of key-value pairs.

  Extracted from MacroRegimePanel rows and AdvisorTab metrics.
  Consistent spacing, monospace, tabular-nums.
-->
<script lang="ts">
  interface KVItem {
    key: string;
    value: string;
    /** Optional color override for the value text. */
    valueColor?: string;
  }

  interface Props {
    items: KVItem[];
    /** Direction of the strip. Default: horizontal row. */
    direction?: "row" | "column";
  }

  let {
    items,
    direction = "row",
  }: Props = $props();
</script>

<div class="kv-root" class:kv-root--column={direction === "column"}>
  {#each items as item (item.key)}
    <div class="kv-pair">
      <span class="kv-key">{item.key}</span>
      <span
        class="kv-value"
        style:color={item.valueColor ?? "var(--terminal-fg-primary)"}
      >
        {item.value}
      </span>
    </div>
  {/each}
</div>

<style>
  .kv-root {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--terminal-space-3);
    font-family: var(--terminal-font-mono);
  }

  .kv-root--column {
    flex-direction: column;
    align-items: stretch;
  }

  .kv-pair {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--terminal-space-2);
  }

  .kv-key {
    font-size: var(--terminal-text-10);
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    color: var(--terminal-fg-tertiary);
    white-space: nowrap;
  }

  .kv-value {
    font-size: var(--terminal-text-11);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
</style>
