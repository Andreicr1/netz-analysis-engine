<script lang="ts">
	import type { Snippet } from 'svelte';
	import * as Alert from "$lib/components/ui/alert";
	import { X } from 'lucide-svelte';

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
			border: 'var(--ii-info, var(--ii-brand-secondary))',
			bg: 'var(--ii-info, var(--ii-brand-secondary))'
		},
		warning: {
			border: 'var(--ii-warning)',
			bg: 'var(--ii-warning)'
		},
		error: {
			border: 'var(--ii-danger, var(--ii-status-error))',
			bg: 'var(--ii-danger, var(--ii-status-error))'
		},
		success: {
			border: 'var(--ii-success)',
			bg: 'var(--ii-success)'
		}
	};

	const style = $derived(variantStyles[variant]);
</script>

<Alert.Root
	variant={variant === 'error' ? 'destructive' : 'default'}
	class="rounded-lg border px-4 py-3"
	style="border-color: {style.border}; background-color: color-mix(in srgb, {style.bg} 12%, var(--ii-surface)); color: var(--ii-text-primary);"
>
	<div class="flex items-start justify-between gap-3">
		<div class="flex-1">
			{#if message}
				<Alert.Description>{message}</Alert.Description>
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
				<X class="h-4 w-4" />
			</button>
		{/if}
	</div>
</Alert.Root>
