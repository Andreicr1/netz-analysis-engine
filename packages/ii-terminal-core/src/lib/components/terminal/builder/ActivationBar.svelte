<!--
  ActivationBar — Zone F fixed footer in the Builder right column.

  Appears when: runPhase === "done" (no allTabsVisited gate).

  Degraded-run handling:
  - Degraded signals (cvar_infeasible_min_var, degraded_other,
    proposal_cvar_infeasible): shows acknowledgment checkbox.
    Activation blocked until checked.
  - Hard-block signals (pre_solve_failure, block_coverage_insufficient,
    template_incomplete, no_approved_allocation,
    instrument_concentration_breach): activation disabled entirely.
    Operator must fix the root cause.
  - Optimal/robustness_fallback/proposal_ready: no gate.
-->
<script lang="ts">
	import { fly } from "svelte/transition";
	import { svelteTransitionFor } from "@investintell/ui";
	import { workspace } from "../../../state/portfolio-workspace.svelte";
	import { translateWinnerSignal } from "../../../utils/metric-translators";
	import type { WinnerSignal } from "../../../types/cascade-telemetry";
	import ConsequenceDialog from "./ConsequenceDialog.svelte";

	const visible = $derived(workspace.runPhase === "done");

	const winnerSignal = $derived<WinnerSignal | null>(
		(workspace.constructionRun?.cascade_telemetry?.winner_signal as WinnerSignal | undefined) ?? null,
	);

	const HARD_BLOCK_SIGNALS: ReadonlySet<string> = new Set([
		"pre_solve_failure",
		"block_coverage_insufficient",
		"template_incomplete",
		"no_approved_allocation",
		"instrument_concentration_breach",
	]);

	const DEGRADED_SIGNALS: ReadonlySet<string> = new Set([
		"cvar_infeasible_min_var",
		"degraded_other",
		"proposal_cvar_infeasible",
	]);

	const isHardBlocked = $derived(
		winnerSignal != null && HARD_BLOCK_SIGNALS.has(winnerSignal),
	);

	const isDegraded = $derived(
		winnerSignal != null && DEGRADED_SIGNALS.has(winnerSignal),
	);

	const signalTranslation = $derived(
		winnerSignal ? translateWinnerSignal(winnerSignal) : null,
	);

	let degradedAcknowledged = $state(false);

	const canActivate = $derived(
		!isHardBlocked && (!isDegraded || degradedAcknowledged),
	);

	let showDialog = $state(false);
	let successBanner = $state(false);

	async function handleSaveDraft() {
		// Draft is the current state — no explicit save needed beyond
		// the already-persisted construction run.
	}

	function handleActivateClick() {
		showDialog = true;
	}

	function handleDialogClose() {
		showDialog = false;
	}

	function handleActivateSuccess() {
		showDialog = false;
		successBanner = true;
	}
</script>

{#if visible}
	<div class="ab-root">
		{#if isHardBlocked && signalTranslation}
			<div class="ab-block-banner ab-block-banner--error">
				<span class="ab-block-badge">BLOCKED</span>
				<span class="ab-block-text">{signalTranslation.label}</span>
			</div>
		{/if}

		{#if isDegraded && signalTranslation}
			<div class="ab-block-banner ab-block-banner--warn">
				<span class="ab-block-badge ab-block-badge--warn">DEGRADED</span>
				<span class="ab-block-text">{signalTranslation.label}</span>
			</div>
			<label class="ab-ack">
				<input
					type="checkbox"
					class="ab-ack-checkbox"
					bind:checked={degradedAcknowledged}
				/>
				<span class="ab-ack-label">
					I acknowledge the degraded construction outcome and wish to proceed
				</span>
			</label>
		{/if}

		<div class="ab-bar" in:fly={{ y: 12, ...svelteTransitionFor("tail", { duration: "update" }) }}>
			<button type="button" class="ab-btn ab-btn--secondary" onclick={handleSaveDraft}>
				Save as Draft
			</button>
			<button
				type="button"
				class="ab-btn ab-btn--activate"
				disabled={!canActivate}
				onclick={handleActivateClick}
			>
				{isHardBlocked ? "ACTIVATION BLOCKED" : "SEND TO COMPLIANCE ▸"}
			</button>
		</div>
	</div>
{/if}

{#if successBanner}
	<div class="ab-success">
		Portfolio activated &mdash;
		<a href="/live" class="ab-success-link">view in Live Workbench</a>
	</div>
{/if}

{#if showDialog}
	<ConsequenceDialog
		onclose={handleDialogClose}
		onsuccess={handleActivateSuccess}
		degradedAcknowledged={isDegraded && degradedAcknowledged}
		winnerSignal={winnerSignal}
	/>
{/if}

<style>
	.ab-root {
		flex-shrink: 0;
	}

	.ab-block-banner {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-2) var(--terminal-space-3);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
	}

	.ab-block-banner--error {
		background: color-mix(in srgb, var(--terminal-status-error) 10%, transparent);
		border-top: 1px solid var(--terminal-status-error);
	}

	.ab-block-banner--warn {
		background: color-mix(in srgb, var(--terminal-accent-amber) 10%, transparent);
		border-top: 1px solid var(--terminal-accent-amber);
	}

	.ab-block-badge {
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-status-error);
		font-size: var(--terminal-text-9);
	}

	.ab-block-badge--warn {
		color: var(--terminal-accent-amber);
	}

	.ab-block-text {
		color: var(--terminal-fg-secondary);
	}

	.ab-ack {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-1) var(--terminal-space-3);
		cursor: pointer;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-secondary);
		background: color-mix(in srgb, var(--terminal-accent-amber) 5%, transparent);
	}

	.ab-ack-checkbox {
		accent-color: var(--terminal-accent-amber);
	}

	.ab-ack-label {
		user-select: none;
	}

	.ab-bar {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: var(--terminal-space-2);
		height: 48px;
		padding: 0 var(--terminal-space-3);
		border-top: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
		flex-shrink: 0;
	}

	.ab-btn {
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		padding: var(--terminal-space-1) var(--terminal-space-3);
		border-radius: var(--terminal-radius-none);
		cursor: pointer;
		transition:
			background var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.ab-btn--secondary {
		background: transparent;
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-secondary);
	}

	.ab-btn--secondary:hover {
		color: var(--terminal-fg-primary);
		border-color: var(--terminal-fg-secondary);
	}

	.ab-btn--activate {
		border: 1px solid var(--ii-success, var(--terminal-status-success));
		background: var(--ii-success, var(--terminal-status-success));
		color: var(--ii-bg, var(--terminal-bg-void));
		font-family: var(--ii-font-mono, var(--terminal-font-mono));
		font-weight: 700;
		letter-spacing: 0.06em;
	}

	.ab-btn--activate:hover:not(:disabled) {
		filter: brightness(1.1);
	}

	.ab-btn--activate:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.ab-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}

	.ab-success {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--terminal-space-1);
		height: 36px;
		background: var(--terminal-status-success);
		color: var(--terminal-bg-void);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.ab-success-link {
		color: var(--terminal-bg-void);
		text-decoration: underline;
	}
</style>
