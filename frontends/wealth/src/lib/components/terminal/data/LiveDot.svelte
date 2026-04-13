<!--
  LiveDot — 6px status indicator dot.

  Extracted from TerminalStatusBar inline dots and DriftMonitorPanel
  drift state indicators. Four status states mapping to terminal tokens.
  Optional pulse animation for live/streaming contexts.
-->
<script lang="ts">
  type DotStatus = "success" | "warn" | "error" | "muted";

  interface Props {
    status?: DotStatus;
    /** Enable pulse animation (for live streaming indicators). */
    pulse?: boolean;
    /** Optional accessible label. */
    label?: string;
  }

  let {
    status = "muted",
    pulse = false,
    label,
  }: Props = $props();

  const colorMap: Record<DotStatus, string> = {
    success: "var(--terminal-status-success)",
    warn: "var(--terminal-status-warn)",
    error: "var(--terminal-status-error)",
    muted: "var(--terminal-fg-muted)",
  };

  const resolvedColor = $derived(colorMap[status]);
</script>

<span
  class="ld-dot"
  class:ld-dot--pulse={pulse}
  style:background={resolvedColor}
  style:box-shadow={status !== "muted" ? `0 0 8px ${resolvedColor}` : "none"}
  role={label ? "status" : undefined}
  aria-label={label}
></span>

<style>
  .ld-dot {
    display: inline-block;
    width: 6px;
    height: 6px;
    flex-shrink: 0;
    vertical-align: middle;
  }

  .ld-dot--pulse {
    animation: ld-pulse 1.8s ease-in-out infinite;
  }

  @keyframes ld-pulse {
    0%, 100% { opacity: 0.45; }
    50% { opacity: 1; }
  }

  @media (prefers-reduced-motion: reduce) {
    .ld-dot--pulse {
      animation: none;
    }
  }
</style>
