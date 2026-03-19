<script lang="ts">
	import Button from "./Button.svelte";
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";

	interface Props {
		title: string;
		message?: string;
		/** Alias for message — accepts either prop name. */
		description?: string;
		actionLabel?: string;
		onAction?: () => void;
		class?: string;
		icon?: Snippet;
	}

	let {
		title,
		message,
		description,
		actionLabel,
		onAction,
		class: className,
		icon,
	}: Props = $props();

	let displayMessage = $derived(message ?? description);
</script>

<div
	class={cn(
		"flex flex-col items-center justify-center rounded-[var(--netz-radius-lg)] border border-dashed border-[var(--netz-border-subtle)] bg-[var(--netz-surface-panel)] px-6 py-12 text-center",
		className,
	)}
>
	{#if icon}
		<div class="mb-5 flex h-16 w-16 items-center justify-center rounded-[var(--netz-radius-lg)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] text-[var(--netz-text-muted)] shadow-[var(--netz-shadow-1)]">
			{@render icon()}
		</div>
	{:else}
		<!-- Default empty icon -->
		<div class="mb-5 flex h-16 w-16 items-center justify-center rounded-[var(--netz-radius-lg)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] text-[var(--netz-text-muted)] shadow-[var(--netz-shadow-1)]">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="28"
				height="28"
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
	<h3 class="text-base font-semibold tracking-[-0.015em] text-[var(--netz-text-primary)]">
		{title}
	</h3>
	{#if displayMessage}
		<p class="mt-2 max-w-[36ch] text-sm leading-6 text-[var(--netz-text-secondary)]">
			{displayMessage}
		</p>
	{/if}
	{#if actionLabel && onAction}
		<Button class="mt-5" onclick={onAction}>
			{actionLabel}
		</Button>
	{/if}
</div>
