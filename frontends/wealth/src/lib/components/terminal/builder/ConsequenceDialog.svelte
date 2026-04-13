<!--
  ConsequenceDialog — typed ACTIVATE confirmation modal.

  Terminal styling: dark bg, hairline border, no radius.
  Type "ACTIVATE" to enable the confirm button.
  Focus trap: Tab cycling within dialog. ESC closes.
-->
<script lang="ts">
	import { workspace } from "$lib/state/portfolio-workspace.svelte";

	interface Props {
		onclose: () => void;
		onsuccess: () => void;
	}

	let { onclose, onsuccess }: Props = $props();

	let confirmText = $state("");
	let errorMessage = $state<string | null>(null);
	let isSubmitting = $state(false);

	const canConfirm = $derived(confirmText === "ACTIVATE");

	let dialogEl: HTMLDivElement | undefined = $state();
	let inputEl: HTMLInputElement | undefined = $state();

	// Auto-focus input on mount
	$effect(() => {
		if (inputEl) inputEl.focus();
	});

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Escape") {
			e.preventDefault();
			onclose();
			return;
		}
		if (e.key === "Enter" && canConfirm && !isSubmitting) {
			e.preventDefault();
			handleConfirm();
			return;
		}
		// Focus trap
		if (e.key === "Tab" && dialogEl) {
			const focusable = dialogEl.querySelectorAll<HTMLElement>(
				'input, button:not([disabled]), [tabindex]:not([tabindex="-1"])',
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

	async function handleConfirm() {
		if (!canConfirm || isSubmitting) return;
		isSubmitting = true;
		errorMessage = null;

		try {
			await workspace.activatePortfolio();
			onsuccess();
		} catch (err) {
			errorMessage = err instanceof Error ? err.message : "Activation failed";
		} finally {
			isSubmitting = false;
		}
	}
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
	class="cd-overlay"
	role="dialog"
	aria-modal="true"
	aria-label="Activate Portfolio"
	onkeydown={handleKeydown}
	bind:this={dialogEl}
>
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="cd-backdrop" onclick={onclose}></div>
	<div class="cd-panel">
		<h2 class="cd-title">Activate Portfolio</h2>

		<p class="cd-warning">
			This will move the portfolio to LIVE status. Active portfolios
			are monitored daily for drift and trigger alerts.
		</p>

		<label class="cd-label" for="cd-confirm-input">
			Type ACTIVATE to confirm
		</label>
		<input
			id="cd-confirm-input"
			type="text"
			class="cd-input"
			bind:value={confirmText}
			bind:this={inputEl}
			placeholder="ACTIVATE"
			autocomplete="off"
			spellcheck="false"
		/>

		{#if errorMessage}
			<div class="cd-error">{errorMessage}</div>
		{/if}

		<div class="cd-actions">
			<button type="button" class="cd-btn cd-btn--cancel" onclick={onclose} disabled={isSubmitting}>
				Cancel
			</button>
			<button
				type="button"
				class="cd-btn cd-btn--confirm"
				onclick={handleConfirm}
				disabled={!canConfirm || isSubmitting}
			>
				{isSubmitting ? "Activating..." : "Activate"}
			</button>
		</div>
	</div>
</div>

<style>
	.cd-overlay {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: var(--terminal-z-overlay, 1000);
	}

	.cd-backdrop {
		position: absolute;
		inset: 0;
		background: var(--terminal-bg-void);
		opacity: 0.85;
	}

	.cd-panel {
		position: relative;
		width: 420px;
		max-width: 90vw;
		padding: var(--terminal-space-6);
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-primary);
	}

	.cd-title {
		font-size: 16px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
		margin: 0 0 var(--terminal-space-4);
		color: var(--terminal-accent-amber);
	}

	.cd-warning {
		font-size: var(--terminal-text-12);
		color: var(--terminal-fg-secondary);
		line-height: 1.6;
		margin: 0 0 var(--terminal-space-4);
	}

	.cd-label {
		display: block;
		font-size: var(--terminal-text-10);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		margin-bottom: var(--terminal-space-1);
	}

	.cd-input {
		width: 100%;
		height: 32px;
		background: var(--terminal-bg-panel-sunken, var(--terminal-bg-void));
		color: var(--terminal-fg-primary);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-12);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		padding: 0 var(--terminal-space-2);
		box-sizing: border-box;
	}

	.cd-input:focus {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}

	.cd-input::placeholder {
		color: var(--terminal-fg-muted);
		font-weight: 400;
	}

	.cd-error {
		margin-top: var(--terminal-space-2);
		padding: var(--terminal-space-1) var(--terminal-space-2);
		background: var(--terminal-bg-panel-raised);
		border-left: 2px solid var(--terminal-status-error);
		color: var(--terminal-status-error);
		font-size: var(--terminal-text-11);
	}

	.cd-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--terminal-space-2);
		margin-top: var(--terminal-space-4);
	}

	.cd-btn {
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
			opacity var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.cd-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.cd-btn--cancel {
		background: transparent;
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-secondary);
	}

	.cd-btn--cancel:hover:not(:disabled) {
		color: var(--terminal-fg-primary);
	}

	.cd-btn--confirm {
		background: var(--terminal-accent-amber);
		border: 1px solid var(--terminal-accent-amber);
		color: var(--terminal-bg-void);
	}

	.cd-btn--confirm:hover:not(:disabled) {
		opacity: 0.9;
	}

	.cd-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}
</style>
