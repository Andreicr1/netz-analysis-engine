<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";

	interface Props {
		onRetry?: () => void;
		class?: string;
		children?: Snippet;
	}

	let { onRetry, class: className, children }: Props = $props();

	let error = $state<Error | null>(null);

	function handleError(e: unknown) {
		error = e instanceof Error ? e : new Error(String(e));
	}

	function retry() {
		error = null;
		onRetry?.();
	}
</script>

<svelte:boundary onerror={handleError}>
	{#if error}
		<div
			class={cn(
				"flex flex-col items-center justify-center rounded-lg border border-(--netz-danger)/30 bg-(--netz-danger)/5 p-6 text-center",
				className,
			)}
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="32"
				height="32"
				viewBox="0 0 24 24"
				fill="none"
				stroke="var(--netz-danger)"
				stroke-width="2"
			>
				<circle cx="12" cy="12" r="10" />
				<line x1="12" y1="8" x2="12" y2="12" />
				<line x1="12" y1="16" x2="12.01" y2="16" />
			</svg>
			<p class="mt-3 text-sm font-medium text-(--netz-danger)">
				Something went wrong
			</p>
			<p class="mt-1 text-xs text-(--netz-text-muted)">{error.message}</p>
			<button
				class="mt-4 inline-flex h-8 items-center rounded-md border border-(--netz-border) bg-(--netz-surface) px-3 text-sm font-medium text-(--netz-text-primary) transition-colors hover:bg-(--netz-surface-alt)"
				onclick={retry}
			>
				Retry
			</button>
		</div>
	{:else}
		{@render children?.()}
	{/if}
</svelte:boundary>
