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

	const borderStyles: Record<Side, string> = {
		right: "border-l",
		left: "border-r",
	};

	const radiusStyles: Record<Side, string> = {
		right: "rounded-l-[var(--netz-radius-xl)]",
		left: "rounded-r-[var(--netz-radius-xl)]",
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
			class="fixed inset-0 bg-[var(--netz-surface-overlay)] backdrop-blur-sm netz-animate-fade-in"
			onclick={close}
			aria-label="Close sheet"
			tabindex="-1"
		></button>
		<!-- Panel -->
		<div
			class={cn(
				"fixed z-50 w-[min(100vw,420px)] border-[var(--netz-border-subtle)] bg-[var(--netz-surface-panel)] shadow-[var(--netz-shadow-floating)] transition-transform duration-[var(--netz-duration-normal)] ease-[var(--netz-ease-out)]",
				sideStyles[side],
				borderStyles[side],
				radiusStyles[side],
				open ? slideIn[side] : slideOut[side],
				className,
			)}
			role="dialog"
			aria-modal="true"
		>
			<button
				class="absolute right-5 top-5 inline-flex h-9 w-9 items-center justify-center rounded-full border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-raised)] text-[var(--netz-text-secondary)] shadow-[var(--netz-shadow-1)] transition-[color,background-color,border-color,box-shadow] duration-[var(--netz-duration-fast)] ease-[var(--netz-ease-out)] hover:bg-[var(--netz-accent-soft)] hover:text-[var(--netz-text-primary)] focus:outline-none focus:shadow-[var(--netz-shadow-focus)]"
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
			<div class="h-full overflow-y-auto p-[var(--netz-space-panel-padding)]">
				{@render children?.()}
			</div>
		</div>
	</div>
{/if}
