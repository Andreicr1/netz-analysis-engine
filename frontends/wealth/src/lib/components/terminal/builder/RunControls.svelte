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

	const isDisabled = $derived(
		!hasPortfolio ||
			phase === "running" ||
			phase === "factor_modeling" ||
			phase === "shrinkage" ||
			phase === "optimizer" ||
			phase === "stress" ||
			phase === "deduped",
	);

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

	<select class="rc-compare" aria-label="Compare with previous run">
		<option value="last">Compare with: Last run</option>
	</select>
</div>

<style>
	.rc-root {
		height: 80px;
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-2);
		border-top: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		box-sizing: border-box;
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
