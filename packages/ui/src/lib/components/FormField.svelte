<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";

	interface Props {
		label: string;
		error?: string | null;
		required?: boolean;
		hint?: string;
		class?: string;
		children?: Snippet;
	}

	let {
		label,
		error,
		required = false,
		hint,
		class: className,
		children,
	}: Props = $props();
</script>

<div class={cn("space-y-1.5", className)}>
	<label class="text-sm font-medium text-[var(--netz-text-primary)]">
		{label}
		{#if required}
			<span class="text-[var(--netz-danger)]">*</span>
		{/if}
	</label>
	{@render children?.()}
	{#if error}
		<p class="text-xs text-[var(--netz-danger)]">{error}</p>
	{:else if hint}
		<p class="text-xs text-[var(--netz-text-muted)]">{hint}</p>
	{/if}
</div>
