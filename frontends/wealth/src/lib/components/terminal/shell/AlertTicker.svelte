<!--
	AlertTicker.svelte — streaming alert marquee primitive.
	=======================================================

	Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md
		§1.4 TerminalShell, Phase 5 alerts stream.

	Horizontal marquee of the 5 most recent portfolio alerts. Mounts
	inside TerminalStatusBar's ticker snippet slot. When a `streamUrl`
	prop is provided, subscribes via `createTerminalStream` and
	coalesces events into a reactive snapshot via
	`createTickBuffer` from @investintell/ui/runtime (satisfies the
	Stability Guardrails P2 Batched requirement). When omitted, the
	ticker renders a STANDBY placeholder.

	Part C scope: TerminalShell passes `streamUrl=undefined` because
	the backend `/alerts/stream` endpoint is Phase 5 territory. The
	component is ready to consume the stream the moment that endpoint
	ships — no further changes required.
-->
<script lang="ts">
	import { onDestroy } from "svelte";
	import {
		createTickBuffer,
		type TickBuffer,
	} from "@investintell/ui/runtime";
	import {
		createTerminalStream,
		type TerminalStreamHandle,
	} from "$lib/components/terminal/runtime/stream";

	type AlertSeverity = "info" | "warn" | "error" | "critical";

	interface AlertEvent {
		id: string;
		severity: AlertSeverity;
		title: string;
		/** ISO 8601 timestamp emitted by the backend. */
		timestamp: string;
	}

	interface AlertTickerProps {
		/**
		 * URL of the SSE endpoint. Optional — when omitted (Part C
		 * default), the component renders a static STANDBY state
		 * without subscribing. Phase 5 wires this to
		 * `/alerts/stream` when the backend endpoint ships.
		 */
		streamUrl?: string;
	}

	let { streamUrl }: AlertTickerProps = $props();

	const MAX_EVENTS = 5;

	// Coalesce incoming alerts into a bounded reactive snapshot.
	// Last-write-wins per alert id so backend replays do not explode
	// the buffer. Interval clock at 500 ms gives a human-legible
	// cadence without burning raf budget — tickers do not need 60fps.
	const buffer: TickBuffer<AlertEvent> = createTickBuffer<AlertEvent>({
		keyOf: (evt) => evt.id,
		maxKeys: MAX_EVENTS * 4,
		evictionPolicy: "drop_oldest",
		clock: { intervalMs: 500 },
	});

	let handle: TerminalStreamHandle | null = null;
	let connectionStatus = $state<"idle" | "connecting" | "open" | "error">(
		"idle",
	);

	$effect(() => {
		const url = streamUrl;
		if (!url) {
			connectionStatus = "idle";
			return;
		}
		connectionStatus = "connecting";
		const localHandle = createTerminalStream<AlertEvent>({
			url,
			onOpen: () => {
				connectionStatus = "open";
			},
			onMessage: (evt) => {
				buffer.write(evt);
			},
			onError: () => {
				connectionStatus = "error";
			},
			onClose: () => {
				connectionStatus = "idle";
			},
		});
		handle = localHandle;
		return () => {
			localHandle.close();
			handle = null;
		};
	});

	onDestroy(() => {
		handle?.close();
		buffer.dispose();
	});

	const sortedEvents = $derived.by<AlertEvent[]>(() => {
		const snapshot = buffer.snapshot;
		if (snapshot.size === 0) return [];
		// Newest first. Timestamps are ISO 8601 — lexicographic sort
		// matches chronological sort for same-timezone data.
		return Array.from(snapshot.values())
			.sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1))
			.slice(0, MAX_EVENTS);
	});

	const hasEvents = $derived(sortedEvents.length > 0);

	function severityClass(sev: AlertSeverity): string {
		return `at-sev at-sev--${sev}`;
	}

	function severityLabel(sev: AlertSeverity): string {
		switch (sev) {
			case "info":
				return "INFO";
			case "warn":
				return "WARN";
			case "error":
				return "ERR";
			case "critical":
				return "CRIT";
		}
	}

	function shortTimestamp(iso: string): string {
		// ISO 8601 → HH:MM:SS extraction. Acceptable without the
		// @investintell/ui formatter since this is a raw machine
		// value, not a locale-sensitive user-facing date.
		if (iso.length < 19) return iso;
		return iso.substring(11, 19);
	}
</script>

<div class="at-track" role="status" aria-live="polite" aria-atomic="false">
	{#if hasEvents}
		<div class="at-scroll">
			{#each sortedEvents as evt (evt.id)}
				<span class="at-entry">
					<span class={severityClass(evt.severity)}>
						<span class="at-dot"></span>
						<span class="at-sev-label">{severityLabel(evt.severity)}</span>
					</span>
					<span class="at-ts">{shortTimestamp(evt.timestamp)}</span>
					<span class="at-sep">·</span>
					<span class="at-title">{evt.title}</span>
				</span>
			{/each}
		</div>
	{:else}
		<span class="at-standby">
			STANDBY — alert stream {connectionStatus === "connecting"
				? "connecting…"
				: connectionStatus === "error"
					? "offline"
					: "not connected"}
		</span>
	{/if}
</div>

<style>
	.at-track {
		display: flex;
		align-items: center;
		width: 100%;
		overflow: hidden;
		white-space: nowrap;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-secondary);
	}

	.at-scroll {
		display: inline-flex;
		gap: var(--terminal-space-4);
		min-width: 0;
	}

	.at-entry {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-1);
	}

	.at-sev {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-weight: 700;
	}

	.at-sev--info {
		color: var(--terminal-accent-cyan);
	}
	.at-sev--warn {
		color: var(--terminal-status-warn);
	}
	.at-sev--error,
	.at-sev--critical {
		color: var(--terminal-status-error);
	}

	.at-dot {
		display: inline-block;
		width: 5px;
		height: 5px;
		background: currentColor;
		box-shadow: 0 0 6px currentColor;
	}

	.at-sev-label {
		font-size: var(--terminal-text-10);
	}

	.at-ts {
		color: var(--terminal-fg-tertiary);
		font-variant-numeric: tabular-nums;
	}

	.at-sep {
		color: var(--terminal-fg-muted);
	}

	.at-title {
		color: var(--terminal-fg-secondary);
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.at-standby {
		color: var(--terminal-fg-muted);
		animation: at-pulse 2.4s ease-in-out infinite;
	}

	@keyframes at-pulse {
		0%,
		100% {
			opacity: 0.45;
		}
		50% {
			opacity: 1;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.at-standby {
			animation: none;
		}
	}
</style>
