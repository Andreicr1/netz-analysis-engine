<!--
  TransitionConfirmDialog — Phase 5 Task 5.2 confirmation surface for
  destructive or irreversible state-machine transitions.

  Wraps the @investintell/ui Dialog primitive with an optional reason
  textarea (DL14 — every approve / archive / reject move writes a
  reason into the ``portfolio_state_transitions`` audit row so the IC
  feed can replay why a portfolio landed in its current state).

  When ``reasonRequired`` is true, Confirm is disabled until the user
  types at least one non-whitespace character.
-->
<script lang="ts">
	import { Dialog, Button } from "@investintell/ui";

	interface Props {
		open: boolean;
		onOpenChange: (open: boolean) => void;
		title: string;
		message: string;
		confirmLabel?: string;
		cancelLabel?: string;
		confirmVariant?: "default" | "destructive";
		reasonRequired?: boolean;
		onConfirm: (reason: string) => void | Promise<void>;
	}

	let {
		open,
		onOpenChange,
		title,
		message,
		confirmLabel = "Confirm",
		cancelLabel = "Cancel",
		confirmVariant = "default",
		reasonRequired = false,
		onConfirm,
	}: Props = $props();

	let reason = $state("");
	let isSubmitting = $state(false);

	const canConfirm = $derived(
		!isSubmitting && (!reasonRequired || reason.trim().length > 0),
	);

	async function handleConfirm() {
		if (!canConfirm) return;
		isSubmitting = true;
		try {
			await onConfirm(reason.trim());
			reason = "";
			onOpenChange(false);
		} finally {
			isSubmitting = false;
		}
	}

	function handleCancel() {
		if (isSubmitting) return;
		reason = "";
		onOpenChange(false);
	}

	// Reset reason on dialog close so a re-opened dialog starts blank.
	$effect(() => {
		if (!open) reason = "";
	});
</script>

<Dialog {open} {onOpenChange} {title}>
	<div class="tcd-body">
		<p class="tcd-message">{message}</p>

		<label class="tcd-reason-label" for="tcd-reason">
			Reason {#if reasonRequired}<span class="tcd-required">*</span>{/if}
		</label>
		<textarea
			id="tcd-reason"
			class="tcd-reason"
			rows="3"
			placeholder={reasonRequired
				? "Required — captured in the audit trail"
				: "Optional — captured in the audit trail"}
			disabled={isSubmitting}
			bind:value={reason}
		></textarea>

		<footer class="tcd-footer">
			<Button variant="ghost" onclick={handleCancel} disabled={isSubmitting}>
				{cancelLabel}
			</Button>
			<Button
				variant={confirmVariant === "destructive" ? "destructive" : "default"}
				onclick={handleConfirm}
				disabled={!canConfirm}
			>
				{isSubmitting ? "Working…" : confirmLabel}
			</Button>
		</footer>
	</div>
</Dialog>

<style>
	.tcd-body {
		display: flex;
		flex-direction: column;
		gap: 12px;
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.tcd-message {
		margin: 0;
		font-size: 13px;
		line-height: 1.5;
		color: var(--ii-text-secondary, #cbccd1);
	}
	.tcd-reason-label {
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--ii-text-muted, #85a0bd);
	}
	.tcd-required {
		color: var(--ii-danger, #fc1a1a);
		margin-left: 2px;
	}
	.tcd-reason {
		resize: vertical;
		min-height: 64px;
		padding: 8px 10px;
		font-size: 12px;
		font-family: inherit;
		color: var(--ii-text-primary, #ffffff);
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.6));
		border-radius: 6px;
	}
	.tcd-reason:focus {
		outline: none;
		border-color: var(--ii-primary, #0177fb);
	}
	.tcd-footer {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding-top: 8px;
		border-top: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
	}
</style>
