<script lang="ts" module>
	let consequenceDialogId = 0;
</script>

<script lang="ts">
	import { AlertDialog } from "bits-ui";
	import type { Snippet } from "svelte";

	export interface ConsequenceDialogMetadataItem {
		label: string;
		value: string;
		emphasis?: boolean;
	}

	export interface ConsequenceDialogPayload {
		rationale?: string;
		typedConfirmation?: string;
	}

	interface Props {
		open?: boolean;
		title: string;
		impactSummary: string;
		scopeText?: string;
		destructive?: boolean;
		requireRationale?: boolean;
		rationaleLabel?: string;
		rationalePlaceholder?: string;
		rationaleMinLength?: number;
		typedConfirmationText?: string;
		typedConfirmation?: string;
		typedConfirmationLabel?: string;
		confirmLabel?: string;
		cancelLabel?: string;
		metadata?: ConsequenceDialogMetadataItem[];
		consequenceList?: Snippet;
		children?: Snippet;
		/** Inject custom footer content (e.g., scope warnings). Receives { canConfirm, submitting }. */
		footer?: Snippet<[{ canConfirm: boolean; submitting: boolean }]>;
		onConfirm: (payload: ConsequenceDialogPayload) => void | Promise<void>;
		onCancel?: () => void;
	}

	let {
		open = $bindable(false),
		title,
		impactSummary,
		scopeText,
		destructive = false,
		requireRationale = false,
		rationaleLabel = "Rationale",
		rationalePlaceholder = "Record the operational or policy basis for this action.",
		rationaleMinLength = 12,
		typedConfirmationText,
		typedConfirmation: typedConfirmationPrompt,
		typedConfirmationLabel = "Typed confirmation",
		confirmLabel = "Confirm action",
		cancelLabel = "Cancel",
		metadata = [],
		consequenceList,
		children,
		footer,
		onConfirm,
		onCancel,
	}: Props = $props();

	let rationale = $state("");
	let typedConfirmation = $state("");
	let submitting = $state(false);
	let cancelRef = $state<HTMLButtonElement | null>(null);

	const instanceId = ++consequenceDialogId;
	const rationaleId = `consequence-rationale-${instanceId}`;
	const rationaleHintId = `consequence-rationale-hint-${instanceId}`;
	const typedConfirmationId = `consequence-typed-${instanceId}`;

	function resetForm() {
		rationale = "";
		typedConfirmation = "";
	}

	function handleOpenChange(nextOpen: boolean) {
		if (submitting && !nextOpen) {
			open = true;
			return;
		}

		const wasOpen = open;
		open = nextOpen;

		if (!nextOpen && wasOpen) {
			resetForm();
			onCancel?.();
		}
	}

	function handleOpenAutoFocus(event: Event) {
		if (!destructive || !cancelRef) {
			return;
		}

		event.preventDefault();
		cancelRef.focus();
	}

	function handleEscapeKeyDown(event: KeyboardEvent) {
		if (submitting) {
			event.preventDefault();
		}
	}

	let rationaleValue = $derived(rationale.trim());
	let typedConfirmationValue = $derived(typedConfirmation.trim());
	let rationaleSatisfied = $derived(!requireRationale || rationaleValue.length >= rationaleMinLength);
	let confirmationPrompt = $derived(typedConfirmationText ?? typedConfirmationPrompt);
	let typedConfirmationSatisfied = $derived(
		!confirmationPrompt || typedConfirmationValue === confirmationPrompt,
	);
	let canConfirm = $derived(rationaleSatisfied && typedConfirmationSatisfied);

	async function handleConfirm() {
		if (!canConfirm || submitting) {
			return;
		}

		submitting = true;

		try {
			await onConfirm({
				rationale: rationaleValue || undefined,
				typedConfirmation: typedConfirmationValue || undefined,
			});
			resetForm();
			open = false;
		} finally {
			submitting = false;
		}
	}
</script>

<AlertDialog.Root bind:open onOpenChange={handleOpenChange}>
	<AlertDialog.Portal>
		<AlertDialog.Overlay
			class="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm ii-animate-fade-in data-[state=closed]:ii-animate-fade-out"
		/>
		<AlertDialog.Content
			class="fixed left-1/2 top-1/2 z-50 w-full max-w-2xl -translate-x-1/2 -translate-y-1/2 rounded-lg border border-(--ii-border) bg-(--ii-surface) p-6 shadow-lg ii-animate-scale-in data-[state=closed]:ii-animate-scale-out"
			onOpenAutoFocus={handleOpenAutoFocus}
			onEscapeKeydown={handleEscapeKeyDown}
		>
			<div class="space-y-5">
				<div class="space-y-2 pr-8">
					<p
						class={`text-xs font-semibold uppercase tracking-[0.18em] ${
							destructive ? "text-(--ii-danger)" : "text-(--ii-text-secondary)"
						}`}
					>
						{destructive ? "Destructive action" : "Consequence-aware confirmation"}
					</p>
					<AlertDialog.Title class="text-xl font-semibold text-(--ii-text-primary)">
						{title}
					</AlertDialog.Title>
					<AlertDialog.Description class="text-sm leading-6 text-(--ii-text-secondary)">
						{impactSummary}
					</AlertDialog.Description>
				</div>

				{#if scopeText}
					<section class="rounded-lg border border-(--ii-border) bg-(--ii-surface-alt) p-4">
						<h3 class="text-sm font-semibold text-(--ii-text-primary)">Scope</h3>
						<p class="mt-2 text-sm leading-6 text-(--ii-text-secondary)">{scopeText}</p>
					</section>
				{/if}

				{#if consequenceList}
					<section class="rounded-lg border border-(--ii-border) bg-(--ii-surface-alt) p-4">
						<h3 class="text-sm font-semibold text-(--ii-text-primary)">Consequences</h3>
						<div class="mt-3 text-sm leading-6 text-(--ii-text-secondary)">
							{@render consequenceList()}
						</div>
					</section>
				{/if}

				{#if metadata.length > 0}
					<section class="rounded-lg border border-(--ii-border) bg-(--ii-surface) p-4">
						<div class="grid gap-3 sm:grid-cols-2">
							{#each metadata as item (item.label)}
								<div class="space-y-1">
									<p class="text-xs font-medium uppercase tracking-[0.16em] text-(--ii-text-secondary)">
										{item.label}
									</p>
									<p class={item.emphasis
										? "text-sm font-semibold text-(--ii-text-primary)"
										: "text-sm text-(--ii-text-primary)"}>
										{item.value}
									</p>
								</div>
							{/each}
						</div>
					</section>
				{/if}

				{#if requireRationale}
					<div class="space-y-2">
						<label for={rationaleId} class="text-sm font-medium text-(--ii-text-primary)">
							{rationaleLabel}
						</label>
						<textarea
							id={rationaleId}
							bind:value={rationale}
							rows="4"
							class="w-full rounded-md border border-(--ii-border) bg-(--ii-surface) px-3 py-2 text-sm text-(--ii-text-primary) outline-none transition focus:border-(--ii-brand-secondary) focus:ring-2 focus:ring-(--ii-brand-secondary)/20"
							placeholder={rationalePlaceholder}
							aria-invalid={rationale.length > 0 && !rationaleSatisfied}
							aria-required={requireRationale}
							aria-describedby={rationaleHintId}
						></textarea>
						<p id={rationaleHintId} class="text-xs text-(--ii-text-secondary)">
							Provide at least {rationaleMinLength} characters before continuing.
						</p>
					</div>
				{/if}

				{#if confirmationPrompt}
					<div class="space-y-2">
						<label for={typedConfirmationId} class="text-sm font-medium text-(--ii-text-primary)">
							{typedConfirmationLabel}
						</label>
						<p class="text-sm text-(--ii-text-secondary)">
							Type <span class="font-semibold text-(--ii-text-primary)">{confirmationPrompt}</span>
							to continue.
						</p>
						<input
							id={typedConfirmationId}
							bind:value={typedConfirmation}
							type="text"
							class="w-full rounded-md border border-(--ii-border) bg-(--ii-surface) px-3 py-2 text-sm text-(--ii-text-primary) outline-none transition focus:border-(--ii-brand-secondary) focus:ring-2 focus:ring-(--ii-brand-secondary)/20"
							aria-invalid={typedConfirmation.length > 0 && !typedConfirmationSatisfied}
						/>
					</div>
				{/if}

				{#if children}
					<div class="space-y-3 border-t border-(--ii-border) pt-4">
						{@render children()}
					</div>
				{/if}

				{#if footer}
					<div class="space-y-3 border-t border-(--ii-border) pt-4">
						{@render footer({ canConfirm, submitting })}
					</div>
				{/if}

				<div class="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
					<AlertDialog.Cancel
						bind:ref={cancelRef}
						disabled={submitting}
						class="inline-flex h-9 items-center justify-center rounded-md border border-(--ii-border) bg-transparent px-4 text-sm font-medium text-(--ii-text-primary) transition-colors hover:bg-(--ii-surface-alt) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--ii-brand-secondary) focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50"
					>
						{cancelLabel}
					</AlertDialog.Cancel>
					<AlertDialog.Action
						disabled={!canConfirm || submitting}
						onclick={handleConfirm}
						class={`inline-flex h-9 items-center justify-center rounded-md px-4 text-sm font-medium text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--ii-brand-secondary) focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 ${
							destructive
								? "bg-(--ii-danger) hover:bg-(--ii-danger)/90"
								: "bg-(--ii-brand-primary) hover:bg-(--ii-brand-primary)/90"
						}`}
					>
						{#if submitting}
							<svg class="mr-2 h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
								<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
								<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
							</svg>
						{/if}
						{confirmLabel}
					</AlertDialog.Action>
				</div>
			</div>
		</AlertDialog.Content>
	</AlertDialog.Portal>
</AlertDialog.Root>
