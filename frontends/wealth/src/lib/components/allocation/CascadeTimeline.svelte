<!--
  CascadeTimeline.svelte
  ======================

  Horizontal 3-phase cascade visualization for the PR-A12 RU LP cascade.
  Ships two modes:

    • mode="live"    — streamed during propose SSE. Parent seeds the
                        phases array with three pending entries and
                        mutates status in place as ``optimizer_phase_complete``
                        arrives (phase, status, objective_value).
                        Coverage is unknown mid-stream; the bar hides.

    • mode="settled" — rendered by ProposalReviewPanel after the run
                        completes. Parent reads ``phase_attempts`` and
                        ``coverage`` from the LatestProposalResponse
                        (surfaced by PR-4a backend extension).

  Winner highlighting: the phase whose key matches the resolved winning
  phase (derived client-side from the array for settled mode, from the
  most-recent succeeded phase for live) renders with accent tone.

  Coverage bar thresholds match PR-A14 operator signals:
    • < 20% → critical (hard-fail territory)
    • < 50% → warn
    • ≥ 50% → success

  Source: docs/plans/2026-04-19-netz-terminal-parity-builder-macro-screener.md §B.6.
-->
<script lang="ts">
	import type {
		CascadePhaseAttempt,
		CoverageSummary,
	} from "$lib/types/allocation-page";

	export type CascadeTimelineMode = "live" | "settled";

	interface Props {
		phases: CascadePhaseAttempt[];
		winnerSignal?: string | null;
		coverage?: CoverageSummary | null;
		mode?: CascadeTimelineMode;
		class?: string;
	}

	let {
		phases,
		winnerSignal = null,
		coverage = null,
		mode = "settled",
		class: className,
	}: Props = $props();

	const PHASE_LABELS: Record<string, string> = {
		phase_1_ru_max_return: "Phase 1 · Max Return",
		phase_2_ru_robust: "Phase 2 · Robust",
		phase_3_min_cvar: "Phase 3 · Min Tail Risk",
	};

	const PHASE_ORDER: readonly string[] = [
		"phase_1_ru_max_return",
		"phase_2_ru_robust",
		"phase_3_min_cvar",
	];

	type PhaseStatus = "pending" | "running" | "succeeded" | "failed" | "skipped" | "unknown";

	const STATUS_MAP: Record<string, PhaseStatus> = {
		pending: "pending",
		running: "running",
		in_progress: "running",
		succeeded: "succeeded",
		success: "succeeded",
		optimal: "succeeded",
		failed: "failed",
		error: "failed",
		skipped: "skipped",
	};

	function normalizeStatus(raw: string | null | undefined): PhaseStatus {
		if (!raw) return "unknown";
		return STATUS_MAP[raw.toLowerCase()] ?? "unknown";
	}

	const orderedPhases = $derived.by(() => {
		const byKey = new Map(phases.map((p) => [p.phase, p]));
		return PHASE_ORDER.map((key) => {
			const found = byKey.get(key);
			return (
				found ?? {
					phase: key,
					status: mode === "live" ? "pending" : "unknown",
					solver: null,
					wall_ms: 0,
					objective_value: null,
					cvar_within_limit: null,
				}
			);
		});
	});

	const winningPhaseKey = $derived.by(() => {
		for (let i = orderedPhases.length - 1; i >= 0; i--) {
			if (normalizeStatus(orderedPhases[i]!.status) === "succeeded") {
				return orderedPhases[i]!.phase;
			}
		}
		return null;
	});

	function coverageTone(pct: number | null | undefined): "success" | "warn" | "critical" {
		if (pct === null || pct === undefined) return "success";
		if (pct < 0.2) return "critical";
		if (pct < 0.5) return "warn";
		return "success";
	}

	const coveragePct = $derived(coverage?.pct_covered ?? null);
	const coverageToneClass = $derived(coverageTone(coveragePct));
	const coverageWidth = $derived(
		coveragePct !== null ? `${Math.max(0, Math.min(1, coveragePct)) * 100}%` : "0%",
	);
</script>

<div class="cascade-timeline {className ?? ''}" data-mode={mode}>
	<ol class="cascade-timeline__row" aria-label="Cascade phase timeline">
		{#each orderedPhases as phase, idx (phase.phase)}
			{@const status = normalizeStatus(phase.status)}
			{@const isWinner = winningPhaseKey === phase.phase}
			<li
				class="cascade-timeline__phase"
				data-status={status}
				class:cascade-timeline__phase--winner={isWinner}
			>
				<span class="cascade-timeline__phase-index">{idx + 1}</span>
				<span class="cascade-timeline__phase-label"
					>{PHASE_LABELS[phase.phase] ?? phase.phase}</span
				>
				<span class="cascade-timeline__phase-status">{status}</span>
			</li>
		{/each}
	</ol>

	{#if coverage && coveragePct !== null}
		<div class="cascade-timeline__coverage" data-tone={coverageToneClass}>
			<div class="cascade-timeline__coverage-bar">
				<div
					class="cascade-timeline__coverage-fill"
					style="width: {coverageWidth}"
					role="progressbar"
					aria-valuenow={Math.round(coveragePct * 100)}
					aria-valuemin="0"
					aria-valuemax="100"
					aria-label="Universe coverage"
				></div>
			</div>
			<span class="cascade-timeline__coverage-label">
				UNIVERSE COVERAGE ·
				<span class="cascade-timeline__coverage-value"
					>{Math.round(coveragePct * 100)}%</span
				>
				{#if coverage.missing_blocks?.length}
					· {coverage.missing_blocks.length} block{coverage.missing_blocks.length === 1 ? "" : "s"} pending
				{/if}
			</span>
		</div>
	{/if}

	{#if winnerSignal && mode === "settled"}
		<p class="cascade-timeline__winner-signal">
			WINNER SIGNAL: <strong>{winnerSignal}</strong>
		</p>
	{/if}
</div>

<style>
	.cascade-timeline {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-secondary);
	}

	.cascade-timeline__row {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--terminal-space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.cascade-timeline__phase {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
		padding: var(--terminal-space-2) var(--terminal-space-3);
		border: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel-raised);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	[data-mode="live"] .cascade-timeline__phase[data-status="pending"] {
		border-style: dashed;
	}
	[data-mode="live"] .cascade-timeline__phase[data-status="running"] {
		border-color: var(--terminal-accent-cyan);
		color: var(--terminal-accent-cyan);
	}

	.cascade-timeline__phase[data-status="succeeded"] {
		color: var(--terminal-status-success);
		border-color: var(--terminal-status-success);
	}
	.cascade-timeline__phase[data-status="failed"] {
		color: var(--terminal-status-error);
		border-color: var(--terminal-status-error);
	}
	.cascade-timeline__phase[data-status="skipped"] {
		color: var(--terminal-fg-tertiary);
		border-color: var(--terminal-fg-muted);
	}
	.cascade-timeline__phase[data-status="unknown"] {
		color: var(--terminal-fg-tertiary);
		border-style: dashed;
	}

	.cascade-timeline__phase--winner {
		background: var(--terminal-bg-panel-sunken);
		box-shadow: inset 0 0 0 1px var(--terminal-accent-amber);
	}
	.cascade-timeline__phase--winner .cascade-timeline__phase-label {
		color: var(--terminal-accent-amber);
	}

	.cascade-timeline__phase-index {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
	}
	.cascade-timeline__phase-label {
		font-size: var(--terminal-text-12);
		color: var(--terminal-fg-primary);
		line-height: var(--terminal-leading-tight);
	}
	.cascade-timeline__phase-status {
		font-size: var(--terminal-text-10);
	}

	.cascade-timeline__coverage {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
	}
	.cascade-timeline__coverage-bar {
		height: 3px;
		background: var(--terminal-fg-muted);
		overflow: hidden;
	}
	.cascade-timeline__coverage-fill {
		height: 100%;
		transition: width var(--terminal-motion-update) var(--terminal-motion-easing-out);
	}
	[data-tone="success"] .cascade-timeline__coverage-fill {
		background: var(--terminal-status-success);
	}
	[data-tone="warn"] .cascade-timeline__coverage-fill {
		background: var(--sev-warn);
	}
	[data-tone="critical"] .cascade-timeline__coverage-fill {
		background: var(--sev-critical);
	}
	.cascade-timeline__coverage-label {
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}
	.cascade-timeline__coverage-value {
		color: var(--terminal-fg-primary);
	}

	.cascade-timeline__winner-signal {
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
		margin: 0;
	}
	.cascade-timeline__winner-signal strong {
		color: var(--terminal-fg-primary);
		font-weight: inherit;
	}
</style>
