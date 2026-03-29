<script lang="ts">
	import SimpleDialog from "./SimpleDialog.svelte";
	import { Button } from "$lib/components/ui/button";

	interface Props {
		open?: boolean;
		title: string;
		message: string;
		confirmLabel?: string;
		confirmVariant?: "default" | "destructive";
		cancelLabel?: string;
		onConfirm: () => void | Promise<void>;
		onCancel?: () => void;
	}

	let {
		open = $bindable(false),
		title,
		message,
		confirmLabel = "Confirm",
		confirmVariant = "default",
		cancelLabel = "Cancel",
		onConfirm,
		onCancel,
	}: Props = $props();

	let loading = $state(false);

	async function handleConfirm() {
		loading = true;
		try {
			await onConfirm();
			open = false;
		} finally {
			loading = false;
		}
	}

	function handleCancel() {
		onCancel?.();
		open = false;
	}
</script>

<SimpleDialog bind:open>
	<div class="space-y-4">
		<h2 class="text-lg font-semibold text-(--ii-text-primary)">{title}</h2>
		<p class="text-sm text-(--ii-text-secondary)">{message}</p>
		<div class="flex justify-end gap-3">
			<Button variant="outline" onclick={handleCancel} disabled={loading}>
				{cancelLabel}
			</Button>
			<Button variant={confirmVariant} onclick={handleConfirm} disabled={loading}>
				{#if loading}
					<svg class="mr-2 h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
						<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
						<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
					</svg>
				{/if}
				{confirmLabel}
			</Button>
		</div>
	</div>
</SimpleDialog>
