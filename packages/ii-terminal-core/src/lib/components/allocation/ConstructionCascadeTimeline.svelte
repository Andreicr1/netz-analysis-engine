<!--
  ConstructionCascadeTimeline.svelte — PORTFOLIO tab wrapper.

  Prop-driven wrapper around CascadeTimelineCore for the build
  results panel. Adds an elapsed timer while the build is in flight.
  The parent page reads from workspace and passes data here.
-->
<script lang="ts">
	import type { CascadeTelemetry } from "../../types/cascade-telemetry";
	import CascadeTimelineCore from "./CascadeTimelineCore.svelte";

	interface Props {
		telemetry: CascadeTelemetry | null;
		runPhase: string;
		class?: string;
	}

	let { telemetry, runPhase, class: className }: Props = $props();

	const isBuilding = $derived(
		runPhase !== "idle" &&
			runPhase !== "done" &&
			runPhase !== "error",
	);
	const isSettled = $derived(runPhase === "done" || runPhase === "error");
	const mode = $derived.by<"live" | "settled">(() => (isBuilding ? "live" : "settled"));

	const phases = $derived(telemetry?.phase_attempts ?? []);
	const winnerSignal = $derived(telemetry?.winner_signal ?? null);
	const coverage = $derived(telemetry?.coverage ?? null);
	const operatorMessage = $derived(telemetry?.operator_message ?? null);
	const signalBinding = $derived(telemetry?.operator_signal?.binding ?? null);

	let elapsedMs = $state(0);
	let intervalId: ReturnType<typeof setInterval> | null = null;
	let buildStartTime: number | null = null;

	$effect(() => {
		if (isBuilding) {
			buildStartTime = Date.now();
			elapsedMs = 0;
			intervalId = setInterval(() => {
				if (buildStartTime) {
					elapsedMs = Date.now() - buildStartTime;
				}
			}, 100);
		} else {
			if (intervalId) {
				clearInterval(intervalId);
				intervalId = null;
			}
		}
		return () => {
			if (intervalId) {
				clearInterval(intervalId);
				intervalId = null;
			}
		};
	});

	const elapsedLabel = $derived.by(() => {
		const secs = Math.floor(elapsedMs / 1000);
		const mins = Math.floor(secs / 60);
		const rem = secs % 60;
		if (mins > 0) return `${mins}m ${rem.toString().padStart(2, "0")}s`;
		return `${secs}s`;
	});

	const visible = $derived(isBuilding || (isSettled && phases.length > 0));
</script>

{#if visible}
	<div class="cct {className ?? ''}">
		{#if isBuilding}
			<div class="cct__elapsed">
				<span class="cct__elapsed-dot"></span>
				BUILDING · {elapsedLabel}
			</div>
		{/if}

		<CascadeTimelineCore
			{phases}
			{winnerSignal}
			{coverage}
			{operatorMessage}
			{signalBinding}
			{mode}
		/>
	</div>
{/if}

<style>
	.cct {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-3);
		border-bottom: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
	}

	.cct__elapsed {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-accent-amber);
		font-variant-numeric: tabular-nums;
	}

	.cct__elapsed-dot {
		display: inline-block;
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--terminal-accent-amber);
		animation: cct-blink 1s ease-in-out infinite;
	}

	@keyframes cct-blink {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.3; }
	}
</style>
