<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";

	type Side = "left" | "right";

	interface Props {
		open?: boolean;
		onOpenChange?: (open: boolean) => void;
		side?: Side;
		class?: string;
		children?: Snippet;
	}

	let {
		open = $bindable(false),
		onOpenChange,
		side = "right",
		class: className,
		children,
	}: Props = $props();

	function close() {
		open = false;
		onOpenChange?.(false);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Escape") close();
	}

	const sideStyles: Record<Side, string> = {
		right: "right-0 top-0 h-full",
		left: "left-0 top-0 h-full",
	};

	const slideIn: Record<Side, string> = {
		right: "translate-x-0",
		left: "translate-x-0",
	};

	const slideOut: Record<Side, string> = {
		right: "translate-x-full",
		left: "-translate-x-full",
	};
</script>

{#if open}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 z-50" onkeydown={handleKeydown}>
		<!-- Backdrop -->
		<button
			class="fixed inset-0 bg-black/50 backdrop-blur-sm netz-animate-fade-in"
			onclick={close}
			aria-label="Close sheet"
			tabindex="-1"
		></button>
		<!-- Panel -->
		<div
			class={cn(
				"fixed z-50 w-[400px] border-l border-[var(--netz-border)] bg-[var(--netz-surface)] shadow-xl transition-transform duration-[var(--netz-duration-normal)] ease-[var(--netz-ease-out)]",
				sideStyles[side],
				open ? slideIn[side] : slideOut[side],
				className,
			)}
			role="dialog"
			aria-modal="true"
		>
			<button
				class="absolute right-4 top-4 rounded-sm opacity-70 transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
				onclick={close}
				aria-label="Close"
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
			</button>
			<div class="h-full overflow-y-auto p-6">
				{@render children?.()}
			</div>
		</div>
	</div>
{/if}
