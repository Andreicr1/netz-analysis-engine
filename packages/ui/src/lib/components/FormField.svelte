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

<div class={cn("space-y-2", className)}>
	<!-- svelte-ignore a11y_label_has_associated_control -->
	<label class="text-[13px] font-semibold tracking-[-0.01em] text-[var(--netz-text-secondary)]">
		{label}
		{#if required}
			<span class="ml-1 text-[var(--netz-danger)]">*</span>
		{/if}
	</label>
	{@render children?.()}
	{#if error}
		<p class="text-xs font-medium text-[var(--netz-danger)]">{error}</p>
	{:else if hint}
		<p class="text-xs text-[var(--netz-text-muted)]">{hint}</p>
	{/if}
</div>
