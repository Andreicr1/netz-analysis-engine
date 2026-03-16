<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";

	interface Props {
		title: string;
		message?: string;
		actionLabel?: string;
		onAction?: () => void;
		class?: string;
		icon?: Snippet;
	}

	let {
		title,
		message,
		actionLabel,
		onAction,
		class: className,
		icon,
	}: Props = $props();
</script>

<div
	class={cn(
		"flex flex-col items-center justify-center py-12 text-center",
		className,
	)}
>
	{#if icon}
		<div class="mb-4 text-[var(--netz-text-muted)]">
			{@render icon()}
		</div>
	{:else}
		<!-- Default empty icon -->
		<div class="mb-4 text-[var(--netz-text-muted)]">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="48"
				height="48"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="1.5"
				stroke-linecap="round"
				stroke-linejoin="round"
			>
				<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
				<polyline points="14 2 14 8 20 8" />
			</svg>
		</div>
	{/if}
	<h3 class="text-lg font-semibold text-[var(--netz-text-primary)]">{title}</h3>
	{#if message}
		<p class="mt-1 max-w-sm text-sm text-[var(--netz-text-muted)]">{message}</p>
	{/if}
	{#if actionLabel && onAction}
		<button
			class="mt-4 inline-flex h-9 items-center justify-center rounded-md bg-[var(--netz-brand-primary)] px-4 text-sm font-medium text-white transition-colors hover:bg-[var(--netz-brand-primary)]/90"
			onclick={onAction}
		>
			{actionLabel}
		</button>
	{/if}
</div>
