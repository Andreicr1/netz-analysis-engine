<!--
  Connection Quality Indicator — dot + label for SSE connection status.
  Bloomberg-style: pulse only when live, static for degraded/offline.
-->
<script lang="ts">
	import type { ConnectionQuality } from "$wealth/stores/risk-store.svelte";

	interface Props {
		quality: ConnectionQuality;
	}

	let { quality }: Props = $props();

	let label = $derived(
		quality === "live" ? "Live"
		: quality === "degraded" ? "Delayed"
		: "Offline"
	);

	let tooltip = $derived(
		quality === "live" ? "Real-time data via SSE"
		: quality === "degraded" ? "Polling every 30s — SSE connection lost"
		: "No connection"
	);
</script>

<div
	class="conn-status"
	class:conn-live={quality === "live"}
	class:conn-degraded={quality === "degraded"}
	class:conn-offline={quality === "offline"}
	role="status"
	aria-live="polite"
	aria-label="Connection status: {label}"
	title={tooltip}
>
	<span class="conn-dot" class:conn-dot--pulse={quality === "live"}></span>
	<span class="conn-label">{label}</span>
</div>

<style>
	.conn-status {
		display: flex;
		align-items: center;
		gap: 5px;
		font-size: 11px;
		font-weight: 500;
		color: var(--ii-text-muted);
		padding: 2px 8px;
		border-radius: var(--ii-radius-sm, 4px);
		user-select: none;
		cursor: help;
	}

	.conn-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		flex-shrink: 0;
		background: var(--ii-border);
	}

	.conn-live .conn-dot { background: var(--ii-success); }
	.conn-degraded .conn-dot { background: var(--ii-warning); }
	.conn-offline .conn-dot { background: var(--ii-danger); }

	.conn-dot--pulse {
		animation: pulse-dot 2s ease-in-out infinite;
	}

	@keyframes pulse-dot {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.4; }
	}

	.conn-label {
		line-height: 1;
	}
</style>
