<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		variant = 'info',
		message,
		dismissible = false,
		ondismiss,
		children
	}: {
		variant?: 'info' | 'warning' | 'error' | 'success';
		message?: string;
		dismissible?: boolean;
		ondismiss?: () => void;
		children?: Snippet;
	} = $props();

	const variantStyles = {
		info: {
			border: 'var(--netz-info, var(--netz-brand-secondary))',
			bg: 'var(--netz-info, var(--netz-brand-secondary))'
		},
		warning: {
			border: 'var(--netz-warning)',
			bg: 'var(--netz-warning)'
		},
		error: {
			border: 'var(--netz-danger, var(--netz-status-error))',
			bg: 'var(--netz-danger, var(--netz-status-error))'
		},
		success: {
			border: 'var(--netz-success)',
			bg: 'var(--netz-success)'
		}
	};

	const style = $derived(variantStyles[variant]);
</script>

<div
	class="rounded-lg border px-4 py-3 text-sm"
	style="border-color: {style.border}; background-color: color-mix(in srgb, {style.bg} 12%, var(--netz-surface)); color: var(--netz-text-primary);"
	role="alert"
>
	<div class="flex items-start justify-between gap-3">
		<div class="flex-1">
			{#if message}
				<p>{message}</p>
			{/if}
			{#if children}
				{@render children()}
			{/if}
		</div>
		{#if dismissible && ondismiss}
			<button
				onclick={ondismiss}
				class="shrink-0 rounded p-0.5 opacity-60 transition-opacity hover:opacity-100"
				aria-label="Dismiss"
			>
				<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
				</svg>
			</button>
		{/if}
	</div>
</div>
