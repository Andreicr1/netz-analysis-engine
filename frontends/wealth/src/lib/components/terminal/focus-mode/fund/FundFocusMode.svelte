<!--
	FundFocusMode.svelte — first consumer of the FocusMode primitive.
	=================================================================

	Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md
		§1.3 FocusMode primitive, Phase 1 exit criteria.

	Wraps EntityAnalyticsVitrine inside the generic FocusMode shell.
	The existing seven-module cascade inside Vitrine is preserved
	as-is — this wrapper is purely a shell composer. Once Part C
	ships TerminalShell + URL deep links, FundWarRoomModal.svelte
	will be retired in favor of this component.
-->
<script lang="ts">
	import FocusMode from "../FocusMode.svelte";
	import EntityAnalyticsVitrine from "$lib/components/analytics/entity/EntityAnalyticsVitrine.svelte";

	interface FundFocusModeProps {
		fundId: string;
		fundLabel: string;
		onClose: () => void;
	}

	let { fundId, fundLabel, onClose }: FundFocusModeProps = $props();

	const snapshot = buildSnapshot();

	function buildSnapshot(): string {
		const now = new Date();
		return now.toISOString().replace("T", " ").slice(0, 19) + "Z";
	}
</script>

<FocusMode
	entityKind="fund"
	entityId={fundId}
	entityLabel={fundLabel}
	{onClose}
>
	{#snippet reactor()}
		<div class="ffm-reactor">
			<EntityAnalyticsVitrine id={fundId} />
		</div>
	{/snippet}

	{#snippet rail()}
		<div class="ffm-rail-block">
			<span class="ffm-rail-label">ENTITY</span>
			<span class="ffm-rail-value">{fundId}</span>
		</div>
		<div class="ffm-rail-block">
			<span class="ffm-rail-label">MODE</span>
			<span class="ffm-rail-value">TERMINAL // FOCUS</span>
		</div>
		<div class="ffm-rail-block">
			<span class="ffm-rail-label">SNAPSHOT</span>
			<span class="ffm-rail-value">{snapshot}</span>
		</div>
		<div class="ffm-rail-block ffm-rail-hint">
			<span class="ffm-rail-label">NAV</span>
			<span class="ffm-rail-value">ESC · CLICK BACKDROP</span>
		</div>
	{/snippet}
</FocusMode>

<style>
	.ffm-reactor {
		min-width: 0;
		min-height: 0;
	}

	.ffm-rail-block {
		background: var(--terminal-bg-void);
		padding: var(--terminal-space-3) var(--terminal-space-4);
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
	}

	.ffm-rail-label {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: 0.1em;
		text-transform: uppercase;
	}

	.ffm-rail-value {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-primary);
		word-break: break-all;
	}

	.ffm-rail-hint .ffm-rail-value {
		color: var(--terminal-fg-tertiary);
	}
</style>
