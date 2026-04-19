<!--
  DDApprovalDialog — terminal-native confirmation dialog for DD approve/reject.

  Renders a scrim overlay with a centered dialog box. Textarea requires
  minimum 10 characters. Terminal tokens only — no shadcn, no hex values.
-->
<script lang="ts">
	interface DDApprovalDialogProps {
		mode: "approve" | "reject";
		isOpen: boolean;
		isSubmitting: boolean;
		error: string | null;
		onSubmit: (text: string) => void;
		onCancel: () => void;
	}

	let {
		mode,
		isOpen,
		isSubmitting,
		error,
		onSubmit,
		onCancel,
	}: DDApprovalDialogProps = $props();

	let text = $state("");

	const isApprove = $derived(mode === "approve");
	const title = $derived(isApprove ? "Approve DD Report" : "Reject DD Report");
	const body = $derived(
		isApprove
			? "Approving this report will add the fund to the Approved Universe."
			: "This report will be returned to draft status.",
	);
	const confirmLabel = $derived(isApprove ? "CONFIRM APPROVAL" : "CONFIRM REJECTION");
	const confirmColor = $derived(
		isApprove ? "var(--terminal-status-success)" : "var(--terminal-status-error)",
	);
	const placeholder = $derived(
		isApprove ? "Rationale for approval (min 10 chars)" : "Reason for rejection (min 10 chars)",
	);
	const isValid = $derived(text.trim().length >= 10);

	function handleSubmit() {
		if (!isValid || isSubmitting) return;
		onSubmit(text.trim());
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Escape") {
			e.preventDefault();
			onCancel();
		}
	}

	// Reset text when dialog opens
	$effect(() => {
		if (isOpen) {
			text = "";
		}
	});
</script>

{#if isOpen}
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div
		class="dad-scrim"
		role="dialog"
		aria-modal="true"
		aria-label={title}
		onkeydown={handleKeydown}
	>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="dad-backdrop" onclick={onCancel} onkeydown={handleKeydown}></div>
		<div class="dad-dialog">
			<div class="dad-title">{title}</div>
			<div class="dad-body">{body}</div>

			<textarea
				class="dad-textarea"
				bind:value={text}
				{placeholder}
				rows={4}
				disabled={isSubmitting}
			></textarea>

			{#if !isValid && text.length > 0}
				<div class="dad-hint">Minimum 10 characters required ({text.trim().length}/10)</div>
			{/if}

			{#if error}
				<div class="dad-error">{error}</div>
			{/if}

			<div class="dad-actions">
				<button
					class="dad-btn dad-btn--confirm"
					style:border-color={confirmColor}
					style:color={confirmColor}
					type="button"
					disabled={!isValid || isSubmitting}
					onclick={handleSubmit}
				>
					{#if isSubmitting}
						SUBMITTING...
					{:else}
						{confirmLabel}
					{/if}
				</button>
				<button
					class="dad-btn dad-btn--cancel"
					type="button"
					disabled={isSubmitting}
					onclick={onCancel}
				>
					CANCEL
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.dad-scrim {
		position: fixed;
		inset: 0;
		z-index: 9000;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.dad-backdrop {
		position: absolute;
		inset: 0;
		background: rgba(0, 0, 0, 0.7);
	}

	.dad-dialog {
		position: relative;
		z-index: 1;
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-3);
		width: 480px;
		max-width: 90vw;
		padding: var(--terminal-space-4);
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		font-family: var(--terminal-font-mono);
	}

	.dad-title {
		font-size: var(--terminal-text-13);
		font-weight: 700;
		color: var(--terminal-fg-primary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.dad-body {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-secondary);
		line-height: 1.5;
	}

	.dad-textarea {
		width: 100%;
		min-height: 80px;
		padding: var(--terminal-space-2);
		background: var(--terminal-bg-surface);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-primary);
		resize: vertical;
	}

	.dad-textarea:focus {
		outline: var(--terminal-border-focus);
		outline-offset: -1px;
	}

	.dad-textarea:disabled {
		opacity: 0.5;
	}

	.dad-hint {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
	}

	.dad-error {
		font-size: var(--terminal-text-10);
		color: var(--terminal-status-error);
		font-weight: 600;
	}

	.dad-actions {
		display: flex;
		gap: var(--terminal-space-2);
		justify-content: flex-end;
	}

	.dad-btn {
		padding: var(--terminal-space-2) var(--terminal-space-3);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		background: transparent;
		border: 1px solid;
		border-radius: var(--terminal-radius-none);
		cursor: pointer;
		transition: opacity var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.dad-btn:disabled {
		opacity: 0.35;
		cursor: not-allowed;
	}

	.dad-btn--cancel {
		border-color: var(--terminal-fg-secondary);
		color: var(--terminal-fg-secondary);
	}

	.dad-btn--confirm:hover:not(:disabled) {
		opacity: 0.8;
	}

	.dad-btn--cancel:hover:not(:disabled) {
		opacity: 0.8;
	}
</style>
