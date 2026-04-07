<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import type { Snippet } from "svelte";
	import { Label } from "$lib/components/ui/label";

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
	<Label class="text-[13px] font-semibold tracking-[-0.01em] text-(--ii-text-secondary)">
		{label}
		{#if required}
			<span class="ml-1 text-(--ii-danger)">*</span>
		{/if}
	</Label>
	{@render children?.()}
	{#if error}
		<p class="text-xs font-medium text-(--ii-danger)">{error}</p>
	{:else if hint}
		<p class="text-xs text-(--ii-text-muted)">{hint}</p>
	{/if}
</div>
