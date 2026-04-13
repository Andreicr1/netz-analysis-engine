<!--
  CascadeTimeline — Zone D of the Builder results panel.

  Pure Svelte 5 + CSS component (NOT ECharts). Renders the 5-phase
  optimizer cascade as horizontal pills with a connector rail.

  States: pending → running (amber pulse) → succeeded (green) → failed (red) → skipped (ghost).
  Connector rail fills left-to-right as phases complete.
-->
<script lang="ts">
	import type { CascadePhase } from "$lib/state/portfolio-workspace.svelte";
	import { formatNumber } from "@investintell/ui";

	interface Props {
		phases: CascadePhase[];
	}

	let { phases }: Props = $props();

	/** Index of the last completed (succeeded/failed) phase for connector fill. */
	const lastCompletedIdx = $derived.by(() => {
		let last = -1;
		for (let i = 0; i < phases.length; i++) {
			const phase = phases[i];
			if (phase && (phase.status === "succeeded" || phase.status === "failed")) last = i;
		}
		return last;
	});

	/** Connector fill percentage (0-100). */
	const fillPct = $derived(
		phases.length > 0 && lastCompletedIdx >= 0
			? ((lastCompletedIdx + 1) / phases.length) * 100
			: 0,
	);
</script>

<div class="ct-root" role="group" aria-label="Optimizer cascade timeline">
	<!-- Connector rail -->
	<div class="ct-rail">
		<div class="ct-rail-bg"></div>
		<div class="ct-rail-fill" style:width="{fillPct}%"></div>
	</div>

	<!-- Phase pills -->
	<div class="ct-pills">
		{#each phases as phase, i (phase.key)}
			<div
				class="ct-pill ct-pill--{phase.status}"
				aria-current={phase.status === "running" ? "step" : undefined}
			>
				<div class="ct-pill-icon">
					{#if phase.status === "succeeded"}
						<span class="ct-icon-check" aria-hidden="true">&#x2713;</span>
					{:else if phase.status === "failed"}
						<span class="ct-icon-x" aria-hidden="true">&#x2717;</span>
					{:else if phase.status === "running"}
						<span class="ct-icon-dot" aria-hidden="true">&#x25CF;</span>
					{:else}
						<span class="ct-icon-dot ct-icon-dot--dim" aria-hidden="true">&#x25CB;</span>
					{/if}
				</div>
				<span class="ct-pill-label">{phase.label}</span>
				{#if phase.status === "succeeded" && phase.objectiveValue != null}
					<span class="ct-pill-value">{formatNumber(phase.objectiveValue, 4)}</span>
				{/if}
			</div>
		{/each}
	</div>
</div>

<style>
	.ct-root {
		position: relative;
		height: 160px;
		display: flex;
		flex-direction: column;
		justify-content: center;
		padding: var(--terminal-space-4) var(--terminal-space-3);
		border-bottom: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		box-sizing: border-box;
	}

	/* ── Connector rail ──────────────────────────────── */

	.ct-rail {
		position: absolute;
		top: 50%;
		left: var(--terminal-space-3);
		right: var(--terminal-space-3);
		height: 2px;
		transform: translateY(-1px);
		pointer-events: none;
	}

	.ct-rail-bg {
		position: absolute;
		inset: 0;
		background: var(--terminal-fg-muted);
	}

	.ct-rail-fill {
		position: absolute;
		top: 0;
		left: 0;
		height: 100%;
		background: var(--terminal-status-success);
		transition: width 0.4s cubic-bezier(0.33, 1, 0.68, 1);
	}

	/* ── Pills container ─────────────────────────────── */

	.ct-pills {
		position: relative;
		display: flex;
		justify-content: space-between;
		gap: var(--terminal-space-1);
		z-index: 1;
	}

	/* ── Individual pill ─────────────────────────────── */

	.ct-pill {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--terminal-space-1);
		flex: 1;
		min-width: 0;
		padding: var(--terminal-space-2);
		border: 1px solid var(--terminal-fg-muted);
		background: var(--terminal-bg-panel);
		transition:
			border-color 0.3s ease,
			opacity 0.3s ease;
	}

	/* States */

	.ct-pill--pending {
		opacity: 0.35;
		border-color: var(--terminal-fg-muted);
		color: var(--terminal-fg-muted);
	}

	.ct-pill--running {
		opacity: 1;
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
		animation: ct-pulse 1.5s ease-in-out infinite;
	}

	.ct-pill--succeeded {
		opacity: 1;
		border-color: var(--terminal-status-success);
		color: var(--terminal-fg-primary);
	}

	.ct-pill--failed {
		opacity: 1;
		border-color: var(--terminal-status-error);
		color: var(--terminal-status-error);
	}

	.ct-pill--failed .ct-pill-label {
		text-decoration: line-through;
	}

	.ct-pill--skipped {
		opacity: 0.25;
		border-style: dashed;
		border-color: var(--terminal-fg-muted);
		color: var(--terminal-fg-muted);
	}

	.ct-pill--skipped .ct-pill-label {
		font-style: italic;
	}

	/* ── Pill internals ──────────────────────────────── */

	.ct-pill-icon {
		font-size: var(--terminal-text-14);
		line-height: 1;
	}

	.ct-icon-check {
		color: var(--terminal-status-success);
	}

	.ct-icon-x {
		color: var(--terminal-status-error);
	}

	.ct-icon-dot {
		color: var(--terminal-accent-amber);
	}

	.ct-icon-dot--dim {
		color: var(--terminal-fg-muted);
	}

	.ct-pill-label {
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		text-align: center;
		line-height: var(--terminal-leading-tight);
	}

	.ct-pill-value {
		font-size: var(--terminal-text-10);
		font-variant-numeric: tabular-nums;
		color: var(--terminal-fg-secondary);
	}

	/* ── Pulse animation ─────────────────────────────── */

	@keyframes ct-pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.5; }
	}
</style>
