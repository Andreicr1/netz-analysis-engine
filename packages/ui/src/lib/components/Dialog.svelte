<script lang="ts">
	import { cn } from "../utils/cn.js";
	import { Dialog } from "bits-ui";
	import type { Snippet } from "svelte";

	interface Props {
		open?: boolean;
		onOpenChange?: (open: boolean) => void;
		class?: string;
		children?: Snippet;
	}

	let {
		open = $bindable(false),
		onOpenChange,
		class: className,
		children,
	}: Props = $props();

	function handleOpenChange(value: boolean) {
		open = value;
		onOpenChange?.(value);
	}
</script>

<Dialog.Root bind:open onOpenChange={handleOpenChange}>
	<Dialog.Portal>
		<Dialog.Overlay
			class="fixed inset-0 z-50 bg-[var(--netz-surface-overlay)] backdrop-blur-sm netz-animate-fade-in data-[state=closed]:netz-animate-fade-out"
		/>
		<Dialog.Content
			class={cn(
				"fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-[var(--netz-radius-xl)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-panel)] p-6 shadow-[var(--netz-shadow-floating)] netz-animate-scale-in data-[state=closed]:netz-animate-scale-out",
				className,
			)}
		>
			{@render children?.()}
			<Dialog.Close
				class="absolute right-4 top-4 inline-flex h-9 w-9 items-center justify-center rounded-full border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-raised)] text-[var(--netz-text-secondary)] shadow-[var(--netz-shadow-1)] transition-[color,background-color,border-color,box-shadow] duration-[var(--netz-duration-fast)] ease-[var(--netz-ease-out)] hover:bg-[var(--netz-accent-soft)] hover:text-[var(--netz-text-primary)] focus:outline-none focus:shadow-[var(--netz-shadow-focus)]"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="16"
					height="16"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<path d="M18 6 6 18" />
					<path d="m6 6 12 12" />
				</svg>
				<span class="sr-only">Close</span>
			</Dialog.Close>
		</Dialog.Content>
	</Dialog.Portal>
</Dialog.Root>
