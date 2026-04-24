<!--
  CascadeTimelineCore.svelte — pure render of cascade telemetry.

  Accepts phase_attempts, coverage, winner_signal, operator_message
  as individual props. Both allocation wrappers (ProposalReviewPanel,
  ProposeButton) and the PORTFOLIO tab wrapper
  (ConstructionCascadeTimeline) compose this component with their
  own data mapping.

  No workspace import. No fetch logic. No $effect.
-->
<script lang="ts">
	import { translateCascadePhaseName, translateWinnerSignal, translateOperatorSignalBinding } from "../../utils/metric-translators";

	interface PhaseEntry {
		phase: string;
		status: string;
		solver?: string | null;
		wall_ms?: number;
		objective_value?: number | null;
		cvar_within_limit?: boolean | null;
	}

	interface CoverageEntry {
		pct_covered: number | null;
		hard_fail?: boolean;
		missing_blocks?: string[];
		n_total_blocks?: number | null;
		n_covered_blocks?: number | null;
	}

	interface OperatorMessageEntry {
		title: string;
		body: string;
		severity: string;
		action_hint?: string;
	}

	export type CascadeTimelineCoreMode = "live" | "settled";

	interface Props {
		phases: PhaseEntry[];
		winnerSignal?: string | null;
		coverage?: CoverageEntry | null;
		operatorMessage?: OperatorMessageEntry | null;
		signalBinding?: string | null;
		mode?: CascadeTimelineCoreMode;
		class?: string;
	}

	let {
		phases,
		winnerSignal = null,
		coverage = null,
		operatorMessage = null,
		signalBinding = null,
		mode = "settled",
		class: className,
	}: Props = $props();

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
		infeasible: "failed",
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

	const winnerTranslation = $derived(
		winnerSignal ? translateWinnerSignal(winnerSignal) : null,
	);
</script>

<div class="ctc {className ?? ''}" data-mode={mode}>
	<ol class="ctc__row" aria-label="Cascade phase timeline">
		{#each orderedPhases as phase, idx (phase.phase)}
			{@const status = normalizeStatus(phase.status)}
			{@const isWinner = winningPhaseKey === phase.phase}
			<li
				class="ctc__phase"
				data-status={status}
				class:ctc__phase--winner={isWinner}
			>
				<span class="ctc__phase-index">{idx + 1}</span>
				<span class="ctc__phase-label">{translateCascadePhaseName(phase.phase)}</span>
				<span class="ctc__phase-status">{status}</span>
				{#if status === "succeeded" && phase.objective_value != null}
					<span class="ctc__phase-obj">{phase.objective_value.toFixed(4)}</span>
				{/if}
				{#if phase.cvar_within_limit != null && status === "succeeded"}
					<span class="ctc__phase-cvar" data-within={phase.cvar_within_limit}>
						CVaR {phase.cvar_within_limit ? "OK" : "BREACH"}
					</span>
				{/if}
			</li>
		{/each}
	</ol>

	{#if coverage && coveragePct !== null}
		<div class="ctc__coverage" data-tone={coverageToneClass}>
			<div class="ctc__coverage-bar">
				<div
					class="ctc__coverage-fill"
					style="width: {coverageWidth}"
					role="progressbar"
					aria-valuenow={Math.round(coveragePct * 100)}
					aria-valuemin="0"
					aria-valuemax="100"
					aria-label="Universe coverage"
				></div>
			</div>
			<span class="ctc__coverage-label">
				UNIVERSE COVERAGE ·
				<span class="ctc__coverage-value">{Math.round(coveragePct * 100)}%</span>
				{#if coverage.missing_blocks?.length}
					· {coverage.missing_blocks.length} block{coverage.missing_blocks.length === 1 ? "" : "s"} pending
				{/if}
			</span>
		</div>
	{/if}

	{#if winnerTranslation && mode === "settled"}
		<p class="ctc__winner" data-tone={winnerTranslation.tone}>
			<strong>{winnerTranslation.label}</strong>
		</p>
	{/if}

	{#if operatorMessage && mode === "settled"}
		<div class="ctc__operator-msg" data-severity={operatorMessage.severity}>
			<p class="ctc__operator-title">{operatorMessage.title}</p>
			<p class="ctc__operator-body">{operatorMessage.body}</p>
			{#if signalBinding}
				{@const bindingTranslation = translateOperatorSignalBinding(signalBinding)}
				{#if bindingTranslation}
					<span class="ctc__binding-badge" data-tone={bindingTranslation.tone}>
						{bindingTranslation.label}
					</span>
				{/if}
			{/if}
		</div>
	{/if}
</div>

<style>
	.ctc {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-secondary);
	}

	.ctc__row {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--terminal-space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.ctc__phase {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
		padding: var(--terminal-space-2) var(--terminal-space-3);
		border: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel-raised);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	[data-mode="live"] .ctc__phase[data-status="pending"] {
		border-style: dashed;
	}
	[data-mode="live"] .ctc__phase[data-status="running"] {
		border-color: var(--terminal-accent-cyan);
		color: var(--terminal-accent-cyan);
		animation: ctc-pulse 1.5s ease-in-out infinite;
	}

	.ctc__phase[data-status="succeeded"] {
		color: var(--terminal-status-success);
		border-color: var(--terminal-status-success);
	}
	.ctc__phase[data-status="failed"] {
		color: var(--terminal-status-error);
		border-color: var(--terminal-status-error);
	}
	.ctc__phase[data-status="skipped"] {
		color: var(--terminal-fg-tertiary);
		border-color: var(--terminal-fg-muted);
	}
	.ctc__phase[data-status="unknown"] {
		color: var(--terminal-fg-tertiary);
		border-style: dashed;
	}

	.ctc__phase--winner {
		background: var(--terminal-bg-panel-sunken);
		box-shadow: inset 0 0 0 1px var(--terminal-accent-amber);
	}
	.ctc__phase--winner .ctc__phase-label {
		color: var(--terminal-accent-amber);
	}

	.ctc__phase-index {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
	}
	.ctc__phase-label {
		font-size: var(--terminal-text-12);
		color: var(--terminal-fg-primary);
		line-height: var(--terminal-leading-tight);
	}
	.ctc__phase-status {
		font-size: var(--terminal-text-10);
	}
	.ctc__phase-obj {
		font-size: var(--terminal-text-10);
		font-variant-numeric: tabular-nums;
		color: var(--terminal-fg-secondary);
	}
	.ctc__phase-cvar {
		font-size: var(--terminal-text-10);
	}
	.ctc__phase-cvar[data-within="true"] {
		color: var(--terminal-status-success);
	}
	.ctc__phase-cvar[data-within="false"] {
		color: var(--terminal-status-error);
	}

	/* ── Coverage bar ──────────────────────────── */

	.ctc__coverage {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
	}
	.ctc__coverage-bar {
		height: 3px;
		background: var(--terminal-fg-muted);
		overflow: hidden;
	}
	.ctc__coverage-fill {
		height: 100%;
		transition: width var(--terminal-motion-update) var(--terminal-motion-easing-out);
	}
	[data-tone="success"] .ctc__coverage-fill {
		background: var(--terminal-status-success);
	}
	[data-tone="warn"] .ctc__coverage-fill {
		background: var(--sev-warn);
	}
	[data-tone="critical"] .ctc__coverage-fill {
		background: var(--sev-critical);
	}
	.ctc__coverage-label {
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}
	.ctc__coverage-value {
		color: var(--terminal-fg-primary);
	}

	/* ── Winner signal ─────────────────────────── */

	.ctc__winner {
		font-size: var(--terminal-text-11);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		margin: 0;
		padding: var(--terminal-space-1) var(--terminal-space-2);
	}
	.ctc__winner[data-tone="success"] {
		color: var(--terminal-status-success);
		border-left: 2px solid var(--terminal-status-success);
	}
	.ctc__winner[data-tone="warning"] {
		color: var(--sev-warn, var(--terminal-accent-amber));
		border-left: 2px solid var(--sev-warn, var(--terminal-accent-amber));
	}
	.ctc__winner[data-tone="danger"] {
		color: var(--terminal-status-error);
		border-left: 2px solid var(--terminal-status-error);
	}
	.ctc__winner[data-tone="neutral"] {
		color: var(--terminal-fg-secondary);
		border-left: 2px solid var(--terminal-fg-muted);
	}
	.ctc__winner strong {
		font-weight: inherit;
	}

	/* ── Operator message ──────────────────────── */

	.ctc__operator-msg {
		font-size: var(--terminal-text-11);
		padding: var(--terminal-space-2);
		border: var(--terminal-border-hairline);
	}
	.ctc__operator-msg[data-severity="info"] {
		border-color: var(--terminal-fg-muted);
		color: var(--terminal-fg-secondary);
	}
	.ctc__operator-msg[data-severity="warning"] {
		border-color: var(--sev-warn, var(--terminal-accent-amber));
		color: var(--sev-warn, var(--terminal-accent-amber));
	}
	.ctc__operator-msg[data-severity="error"] {
		border-color: var(--terminal-status-error);
		color: var(--terminal-status-error);
	}
	.ctc__operator-title {
		margin: 0;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
	}
	.ctc__operator-body {
		margin: var(--terminal-space-1) 0 0;
		color: var(--terminal-fg-secondary);
	}

	/* ── Binding badge ─────────────────────────── */

	.ctc__binding-badge {
		display: inline-block;
		margin-top: var(--terminal-space-1);
		padding: 1px 6px;
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		border: var(--terminal-border-hairline);
	}
	.ctc__binding-badge[data-tone="warning"] {
		color: var(--sev-warn, var(--terminal-accent-amber));
		border-color: var(--sev-warn, var(--terminal-accent-amber));
	}
	.ctc__binding-badge[data-tone="danger"] {
		color: var(--terminal-status-error);
		border-color: var(--terminal-status-error);
	}
	.ctc__binding-badge[data-tone="neutral"] {
		color: var(--terminal-fg-tertiary);
		border-color: var(--terminal-fg-muted);
	}
	.ctc__binding-badge[data-tone="success"] {
		color: var(--terminal-status-success);
		border-color: var(--terminal-status-success);
	}

	@keyframes ctc-pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.5; }
	}
</style>
