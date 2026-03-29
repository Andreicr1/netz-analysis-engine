<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import type { HTMLInputAttributes } from "svelte/elements";

	interface Props extends HTMLInputAttributes {
		value?: string | number;
		class?: string;
		error?: string;
	}

	let { value = $bindable(""), class: className, error, ...rest }: Props = $props();
</script>

<div class="w-full">
	<input
		class={cn(
			"ii-ui-field flex h-(--ii-space-control-height-md) w-full rounded-(--ii-radius-md) px-3.5 py-2 text-sm tracking-[-0.005em] text-(--ii-text-primary) placeholder:text-(--ii-text-muted) disabled:cursor-not-allowed disabled:bg-(--ii-surface-inset) disabled:opacity-50",
			error && "border-(--ii-danger)",
			className,
		)}
		{value}
		{...rest}
	/>
	{#if error}
		<p class="mt-1 text-xs text-(--ii-danger)">{error}</p>
	{/if}
</div>
