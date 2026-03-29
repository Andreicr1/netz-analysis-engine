<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import { Dialog as BitsDialog } from "bits-ui";
	import type { Snippet } from "svelte";

	interface Props {
		open?: boolean;
		onOpenChange?: (open: boolean) => void;
		title?: string;
		class?: string;
		children?: Snippet;
	}

	let {
		open = $bindable(false),
		onOpenChange,
		title,
		class: className,
		children,
	}: Props = $props();

	function handleOpenChange(value: boolean) {
		open = value;
		onOpenChange?.(value);
	}
</script>

<BitsDialog.Root bind:open onOpenChange={handleOpenChange}>
	<BitsDialog.Portal>
		<BitsDialog.Overlay
			class="fixed inset-0 z-50 bg-(--ii-surface-overlay) backdrop-blur-sm ii-animate-fade-in data-[state=closed]:ii-animate-fade-out"
		/>
		<BitsDialog.Content
			class={cn(
				"fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-(--ii-radius-xl) border border-(--ii-border-subtle) bg-(--ii-surface-panel) p-6 shadow-(--ii-shadow-floating) ii-animate-scale-in data-[state=closed]:ii-animate-scale-out",
				className,
			)}
		>
			{#if title}
				<h2 class="mb-4 text-lg font-semibold text-(--ii-text-primary)">{title}</h2>
			{/if}
			{@render children?.()}
			<BitsDialog.Close
				class="absolute right-4 top-4 inline-flex h-9 w-9 items-center justify-center rounded-full border border-(--ii-border-subtle) bg-(--ii-surface-raised) text-(--ii-text-secondary) shadow-(--ii-shadow-1) transition-[color,background-color,border-color,box-shadow] duration-(--ii-duration-fast) ease-(--ii-ease-out) hover:bg-(--ii-accent-soft) hover:text-(--ii-text-primary) focus:outline-none focus:shadow-(--ii-shadow-focus)"
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
			</BitsDialog.Close>
		</BitsDialog.Content>
	</BitsDialog.Portal>
</BitsDialog.Root>
