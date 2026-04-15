<!--
  RunControls — Zone C of the Builder command panel.

  "Run Construction" button with state machine driven by
  workspace.runPhase. Compare dropdown stub for Session 3.
-->
<script lang="ts">
	import { workspace } from "$lib/state/portfolio-workspace.svelte";

	interface Props {
		onRunComplete?: () => void;
	}

	let { onRunComplete }: Props = $props();

	const phase = $derived(workspace.runPhase);
	const hasPortfolio = $derived(workspace.portfolioId !== null);
	const runError = $derived(workspace.runError);
	const dedupedNotice = $derived(workspace.buildDedupedNotice);

	/**
	 * PR-A5 A.11 — Error UX matrix, rendered inline in the RunControls
	 * footer. The backend already sanitises ``message`` server-side; we
	 * just map HTTP-level failures (captured as Error.message by the
	 * api client) onto the spec's verbatim strings. SSE ERROR/CANCELLED
	 * are already driven by _applyBuildEvent so runError carries the
	 * sanitised sentence directly.
	 */
	const errorLine = $derived.by((): { text: string; cta: string | null } | null => {
		if (phase === "cancelled") {
			return { text: "Construction cancelled.", cta: null };
		}
		if (phase !== "error") return null;
		const msg = runError ?? "";
		// HTTP 400 invalid UUID
		if (/\b400\b/.test(msg) && /uuid|invalid/i.test(msg)) {
			return {
				text: "Portfolio identifier is invalid. Refresh and re-select.",
				cta: "Refresh",
			};
		}
		// HTTP 403 — cross-tenant stream vs RBAC distinction
		if (/\b403\b/.test(msg)) {
			if (/stream/i.test(msg)) {
				return { text: "Build stream unavailable. Please re-open the Builder.", cta: "Reopen" };
			}
			return {
				text: "You are not authorised to run a construction. Contact an IC member.",
				cta: null,
			};
		}
		// HTTP 504 / 120s client-timeout surfaces as AbortError → "Construction exceeded 120s"
		if (/\b504\b/.test(msg) || /timeout|exceeded/i.test(msg)) {
			return {
				text:
					"Construction exceeded 120s. Review your calibration (regime override, shrinkage, turnover cap) and try again.",
				cta: "Re-run",
			};
		}
		// Stream disconnect
		if (/stream closed|lost connection|reconnect/i.test(msg)) {
			return {
				text: "Lost connection to the build stream. Reconnecting\u2026",
				cta: "Reopen",
			};
		}
		// Default: render sanitised backend message verbatim (never re-format).
		return { text: msg || "Construction failed.", cta: "Re-run" };
	});

	function handleErrorCta() {
		if (!errorLine?.cta) return;
		if (errorLine.cta === "Refresh" || errorLine.cta === "Reopen") {
			window.location.reload();
			return;
		}
		void handleRun();
	}

	const buttonLabel = $derived.by(() => {
		switch (phase) {
			case "running":
			case "factor_modeling":
			case "shrinkage":
			case "optimizer":
			case "stress":
			case "deduped":
				return "Building\u2026";
			case "done":
				return "Complete";
			case "error":
				return "Re-run";
			case "cancelled":
				// A.6 — cancelled uses neutral wording + neutral style.
				return "Run again";
			default:
				return "Run Construction";
		}
	});

	const inFlight = $derived(
		phase === "running" ||
			phase === "factor_modeling" ||
			phase === "shrinkage" ||
			phase === "optimizer" ||
			phase === "stress" ||
			phase === "deduped",
	);

	const isDisabled = $derived(!hasPortfolio || inFlight);

	// PR-A5 D.2 — belt-and-suspenders: we also key the disabled attribute
	// on the same set so synchronous double-clicks within a frame become
	// a no-op even before the async runBuildJob resolves.
	const showCancel = $derived(inFlight);
	let cancelRequested = $state(false);
	let cancelWarningTimerId: ReturnType<typeof setTimeout> | null = null;
	let cancelWarningActive = $state(false);

	async function handleCancel() {
		if (!inFlight || cancelRequested) return;
		cancelRequested = true;
		// D.5 — if no CANCELLED event within 30s, surface a soft warning.
		if (cancelWarningTimerId !== null) clearTimeout(cancelWarningTimerId);
		cancelWarningTimerId = setTimeout(() => {
			cancelWarningActive = true;
		}, 30_000);
		await workspace.cancelActiveBuild();
	}

	$effect(() => {
		// Reset cancel guards when we leave an in-flight state.
		if (!inFlight) {
			cancelRequested = false;
			cancelWarningActive = false;
			if (cancelWarningTimerId !== null) {
				clearTimeout(cancelWarningTimerId);
				cancelWarningTimerId = null;
			}
		}
	});

	const statusClass = $derived.by(() => {
		switch (phase) {
			case "running":
			case "factor_modeling":
			case "shrinkage":
			case "optimizer":
			case "stress":
			case "deduped":
				return "rc-btn--running";
			case "done":
				return "rc-btn--done";
			case "error":
				return "rc-btn--error";
			case "cancelled":
				// A.6 — neutral, NOT red.
				return "rc-btn--cancelled";
			default:
				return "";
		}
	});

	async function handleRun() {
		if (isDisabled) return;
		const result = await workspace.runBuildJob();
		if (result && onRunComplete) {
			onRunComplete();
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Enter" && !isDisabled) {
			e.preventDefault();
			handleRun();
		}
	}
</script>

<div class="rc-root">
	<div class="rc-row">
		<button
			type="button"
			class="rc-btn {statusClass}"
			disabled={isDisabled}
			onclick={handleRun}
			onkeydown={handleKeydown}
			aria-label={buttonLabel}
		>
			{#if phase === "done"}
				<span class="rc-check">&check;</span>
			{/if}
			{buttonLabel}
		</button>

		{#if showCancel}
			<!-- PR-A5 A.9 — secondary CANCEL, only while in-flight. -->
			<button
				type="button"
				class="rc-cancel"
				onclick={handleCancel}
				disabled={cancelRequested}
				aria-label="Cancel construction"
			>
				{cancelRequested ? "Cancelling\u2026" : "Cancel"}
			</button>
		{/if}
	</div>

	<select class="rc-compare" aria-label="Compare with previous run">
		<option value="last">Compare with: Last run</option>
	</select>

	{#if dedupedNotice}
		<!-- PR-A5 A.4.3 — transient notice while advisory-lock loser follows the primary stream. -->
		<div class="rc-notice" role="status">{dedupedNotice}</div>
	{/if}

	{#if cancelWarningActive}
		<!-- PR-A5 D.5 — 30s soft warning if no CANCELLED event arrives. -->
		<div class="rc-notice rc-notice--warn" role="status">
			Cancellation accepted but no confirmation received. Refresh to re-sync.
		</div>
	{/if}

	{#if errorLine}
		<!-- PR-A5 A.11 — inline error footer with recovery CTA. -->
		<div class="rc-error" role="alert">
			<span class="rc-error-text">{errorLine.text}</span>
			{#if errorLine.cta}
				<button type="button" class="rc-error-cta" onclick={handleErrorCta}>
					{errorLine.cta}
				</button>
			{/if}
		</div>
	{/if}
</div>

<style>
	.rc-root {
		min-height: 80px;
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-2);
		border-top: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		box-sizing: border-box;
	}

	.rc-row {
		display: flex;
		align-items: stretch;
		gap: var(--terminal-space-2);
		width: 100%;
	}

	.rc-row .rc-btn {
		flex: 1;
	}

	.rc-cancel {
		flex: 0 0 auto;
		min-width: 96px;
		padding: 0 var(--terminal-space-3);
		background: var(--terminal-bg-panel-sunken);
		color: var(--terminal-fg-primary);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		cursor: pointer;
	}

	.rc-cancel:hover:not(:disabled) {
		opacity: 0.85;
	}

	.rc-cancel:disabled {
		cursor: not-allowed;
		opacity: 0.5;
	}

	.rc-cancel:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}

	.rc-notice {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-secondary);
		line-height: var(--terminal-leading-tight);
		padding: var(--terminal-space-1) 0;
	}

	.rc-notice--warn {
		color: var(--terminal-accent-amber);
	}

	.rc-error {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		font-size: var(--terminal-text-10);
		color: var(--terminal-status-error);
		line-height: var(--terminal-leading-tight);
		padding: var(--terminal-space-1) 0;
	}

	.rc-error-text {
		flex: 1;
		min-width: 0;
	}

	.rc-error-cta {
		flex: 0 0 auto;
		padding: 0 var(--terminal-space-2);
		height: 24px;
		background: transparent;
		color: var(--terminal-status-error);
		border: 1px solid var(--terminal-status-error);
		border-radius: var(--terminal-radius-none);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		cursor: pointer;
	}

	.rc-error-cta:hover {
		opacity: 0.8;
	}

	.rc-error-cta:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}

	.rc-btn {
		height: 32px;
		width: 100%;
		background: var(--terminal-accent-amber);
		color: var(--terminal-bg-base, var(--terminal-bg-void));
		border: none;
		border-radius: var(--terminal-radius-none);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		cursor: pointer;
		transition:
			background var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			opacity var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.rc-btn:hover:not(:disabled) {
		opacity: 0.9;
	}

	.rc-btn:disabled {
		cursor: not-allowed;
		opacity: 0.5;
	}

	.rc-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}

	.rc-btn--running {
		animation: rc-pulse 1.5s ease-in-out infinite;
	}

	.rc-btn--done {
		background: var(--terminal-status-success);
	}

	.rc-btn--error {
		background: var(--terminal-status-error);
		color: var(--terminal-fg-primary);
	}

	.rc-btn--cancelled {
		background: var(--terminal-bg-panel-sunken);
		color: var(--terminal-fg-primary);
		border: var(--terminal-border-hairline);
	}

	.rc-check {
		margin-right: var(--terminal-space-1);
	}

	@keyframes rc-pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.6; }
	}

	.rc-compare {
		height: 24px;
		width: 100%;
		background: var(--terminal-bg-panel-sunken);
		color: var(--terminal-fg-secondary);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		padding: 0 var(--terminal-space-2);
		cursor: pointer;
	}

	.rc-compare:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}
</style>
