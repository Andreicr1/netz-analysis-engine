<!--
  TradeConfirmation — simple confirmation dialog before trade execution.

  Lighter than ConsequenceDialog (no typed ACTIVATE). ESC closes,
  Enter confirms. Amber "Execute" button.
-->
<script lang="ts">
	import { formatPercent } from "@investintell/ui";

	interface Props {
		tradeCount: number;
		buyCount: number;
		sellCount: number;
		turnoverPct: number;
		executing: boolean;
		errorMessage: string | null;
		onClose: () => void;
		onConfirm: () => void;
	}

	let {
		tradeCount,
		buyCount,
		sellCount,
		turnoverPct,
		executing,
		errorMessage,
		onClose,
		onConfirm,
	}: Props = $props();

	let dialogEl: HTMLDivElement | undefined = $state();

	// Auto-focus the dialog on mount
	$effect(() => {
		if (dialogEl) dialogEl.focus();
	});

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Escape") {
			e.preventDefault();
			onClose();
			return;
		}
		if (e.key === "Enter" && !executing) {
			e.preventDefault();
			onConfirm();
			return;
		}
		// Focus trap
		if (e.key === "Tab" && dialogEl) {
			const focusable = dialogEl.querySelectorAll<HTMLElement>(
				"button:not([disabled])",
			);
			if (focusable.length === 0) return;
			const first = focusable[0] as HTMLElement | undefined;
			const last = focusable[focusable.length - 1] as HTMLElement | undefined;
			if (!first || !last) return;
			if (e.shiftKey && document.activeElement === first) {
				e.preventDefault();
				last.focus();
			} else if (!e.shiftKey && document.activeElement === last) {
				e.preventDefault();
				first.focus();
			}
		}
	}
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
	class="tc-overlay"
	role="dialog"
	aria-modal="true"
	aria-label="Confirm trade execution"
	onkeydown={handleKeydown}
	bind:this={dialogEl}
	tabindex="-1"
>
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="tc-backdrop" onclick={onClose}></div>
	<div class="tc-panel">
		<h2 class="tc-title">Execute {tradeCount} trades?</h2>

		<div class="tc-details">
			<div class="tc-row">
				<span class="tc-key">{buyCount} BUY orders, {sellCount} SELL orders</span>
			</div>
			<div class="tc-row">
				<span class="tc-key">Estimated turnover:</span>
				<span class="tc-val">{formatPercent(turnoverPct, 1)}</span>
			</div>
			<div class="tc-row">
				<span class="tc-key">Execution:</span>
				<span class="tc-val tc-val--muted">Simulated</span>
			</div>
		</div>

		{#if errorMessage}
			<div class="tc-error">{errorMessage}</div>
		{/if}

		<div class="tc-actions">
			<button type="button" class="tc-btn tc-btn--cancel" onclick={onClose} disabled={executing}>
				Cancel
			</button>
			<button
				type="button"
				class="tc-btn tc-btn--execute"
				onclick={onConfirm}
				disabled={executing}
			>
				{executing ? "Executing..." : "Execute"}
			</button>
		</div>
	</div>
</div>

<style>
	.tc-overlay {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: calc(var(--terminal-z-focusmode, 900) + 10);
		outline: none;
	}

	.tc-backdrop {
		position: absolute;
		inset: 0;
		background: var(--terminal-bg-void);
		opacity: 0.85;
	}

	.tc-panel {
		position: relative;
		width: 400px;
		max-width: 90vw;
		padding: var(--terminal-space-6);
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-primary);
	}

	.tc-title {
		font-size: 16px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
		margin: 0 0 var(--terminal-space-4);
		color: var(--terminal-accent-amber);
	}

	.tc-details {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
		margin-bottom: var(--terminal-space-4);
	}

	.tc-row {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
	}

	.tc-key {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-secondary);
	}

	.tc-val {
		font-size: var(--terminal-text-11);
		font-weight: 700;
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
	}

	.tc-val--muted {
		color: var(--terminal-fg-tertiary);
	}

	.tc-error {
		margin-bottom: var(--terminal-space-3);
		padding: var(--terminal-space-1) var(--terminal-space-2);
		border-left: 2px solid var(--terminal-status-error);
		background: var(--terminal-bg-panel-raised);
		color: var(--terminal-status-error);
		font-size: var(--terminal-text-11);
	}

	.tc-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--terminal-space-2);
	}

	.tc-btn {
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		padding: var(--terminal-space-1) var(--terminal-space-3);
		border-radius: var(--terminal-radius-none);
		cursor: pointer;
		transition:
			background var(--terminal-motion-tick),
			opacity var(--terminal-motion-tick);
	}

	.tc-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.tc-btn--cancel {
		background: transparent;
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-secondary);
	}

	.tc-btn--cancel:hover:not(:disabled) {
		color: var(--terminal-fg-primary);
	}

	.tc-btn--execute {
		background: var(--terminal-accent-amber);
		border: 1px solid var(--terminal-accent-amber);
		color: var(--terminal-bg-void);
	}

	.tc-btn--execute:hover:not(:disabled) {
		opacity: 0.9;
	}

	.tc-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}
</style>
