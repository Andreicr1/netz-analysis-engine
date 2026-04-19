<!--
  CascadeTimeline — Zone D of the Builder results panel.

  Pure Svelte 5 + CSS component (NOT ECharts). Renders the 5-phase
  optimizer cascade as horizontal pills with a connector rail.

  States: pending → running (amber pulse) → succeeded (green) → failed (red) → skipped (ghost).
  Connector rail fills left-to-right as phases complete.
-->
<script lang="ts">
	import type { CascadePhase } from "$wealth/state/portfolio-workspace.svelte";
	import type { BuildPhase } from "$wealth/types/portfolio-build";
	import { formatNumber } from "@investintell/ui";

	interface Props {
		phases: CascadePhase[];
		/** PR-A5 A.8 — 0..1 build progress. Visible while a build is in-flight. */
		runProgress?: number;
		/** PR-A5 A.8 — whether the thin progress bar should render. */
		showProgress?: boolean;
		/** PR-A5 B.2 — current pipeline phase (drives the upper strip). */
		pipelinePhase?: BuildPhase | "IDLE";
		/** PR-A5 B.2 — whether the pipeline phase has entered a terminal error state. */
		pipelineErrored?: boolean;
	}

	let {
		phases,
		runProgress = 0,
		showProgress = false,
		pipelinePhase = "IDLE",
		pipelineErrored = false,
	}: Props = $props();

	// PR-A5 B.2 — pipeline strip: 5 chips mapping each top-level phase.
	const PIPELINE_STRIP: ReadonlyArray<{ key: BuildPhase; label: string }> = [
		{ key: "FACTOR_MODELING", label: "FACTOR MODEL" },
		{ key: "SHRINKAGE", label: "COVARIANCE" },
		{ key: "SOCP_OPTIMIZATION", label: "OPTIMIZER" },
		{ key: "BACKTESTING", label: "BACKTEST" },
		{ key: "COMPLETED", label: "COMPLETE" },
	];

	type StripStatus = "pending" | "running" | "succeeded" | "failed" | "skipped";

	const currentIdx = $derived.by(() => {
		const idx = PIPELINE_STRIP.findIndex((c) => c.key === pipelinePhase);
		return idx;
	});

	const stripStatuses = $derived.by<StripStatus[]>(() => {
		return PIPELINE_STRIP.map((chip, i) => {
			if (pipelinePhase === "COMPLETED") return "succeeded";
			if (pipelineErrored) {
				if (currentIdx < 0) return "failed";
				if (i < currentIdx) return "succeeded";
				if (i === currentIdx) return "failed";
				return "skipped";
			}
			if (currentIdx < 0) return "pending";
			if (i < currentIdx) return "succeeded";
			if (i === currentIdx) return "running";
			return "pending";
		});
	});

	const progressPct = $derived(Math.max(0, Math.min(1, runProgress)) * 100);

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

<div class="ct-root" role="group" aria-label="Construction phase timeline">
	<!-- PR-A5 B.2 — pipeline phase strip (coarse top-level). -->
	<div class="ct-strip" aria-label="Pipeline phases">
		{#each PIPELINE_STRIP as chip, i (chip.key)}
			<div
				class="ct-strip-chip ct-strip-chip--{stripStatuses[i]}"
				aria-current={stripStatuses[i] === "running" ? "step" : undefined}
			>
				<span class="ct-strip-label">{chip.label}</span>
			</div>
			{#if i < PIPELINE_STRIP.length - 1}
				<span class="ct-strip-sep" aria-hidden="true">&rarr;</span>
			{/if}
		{/each}
	</div>

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

	{#if showProgress}
		<!-- PR-A5 A.8 — thin 2px run-progress bar under the pills. -->
		<div
			class="ct-progress"
			role="progressbar"
			aria-valuenow={Math.round(progressPct)}
			aria-valuemin="0"
			aria-valuemax="100"
			aria-label="Construction progress"
		>
			<div class="ct-progress-fill" style:width="{progressPct}%"></div>
		</div>
	{/if}
</div>

<style>
	.ct-root {
		position: relative;
		min-height: 160px;
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

	/* ── Thin progress bar (PR-A5 A.8) ───────────────── */

	.ct-progress {
		position: relative;
		margin-top: var(--terminal-space-2);
		height: 2px;
		background: var(--terminal-border-hairline, var(--terminal-fg-muted));
		overflow: hidden;
	}

	.ct-progress-fill {
		height: 100%;
		background: var(--terminal-accent, var(--terminal-accent-amber));
		transition: width 0.3s cubic-bezier(0.33, 1, 0.68, 1);
	}

	/* ── Pulse animation ─────────────────────────────── */

	@keyframes ct-pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.5; }
	}

	/* ── Pipeline strip (PR-A5 B.2) ──────────────────── */

	.ct-strip {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-1);
		margin-bottom: var(--terminal-space-2);
		padding-bottom: var(--terminal-space-2);
		border-bottom: 1px dashed var(--terminal-fg-muted);
	}

	.ct-strip-chip {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		height: 24px;
		padding: 0 var(--terminal-space-2);
		border: 1px solid var(--terminal-fg-muted);
		background: transparent;
		transition:
			border-color 0.3s ease,
			color 0.3s ease,
			opacity 0.3s ease;
	}

	.ct-strip-chip--pending {
		opacity: 0.45;
		color: var(--terminal-fg-muted);
	}

	.ct-strip-chip--running {
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
		animation: ct-pulse 1.5s ease-in-out infinite;
	}

	.ct-strip-chip--succeeded {
		border-color: var(--terminal-status-success);
		color: var(--terminal-fg-primary);
	}

	.ct-strip-chip--failed {
		border-color: var(--terminal-status-error);
		color: var(--terminal-status-error);
	}

	.ct-strip-chip--skipped {
		opacity: 0.35;
		border-style: dashed;
		color: var(--terminal-fg-muted);
	}

	.ct-strip-label {
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		line-height: 1;
	}

	.ct-strip-sep {
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-10);
	}
</style>
