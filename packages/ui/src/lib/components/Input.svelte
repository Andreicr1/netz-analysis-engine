<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { HTMLInputAttributes } from "svelte/elements";

	interface Props extends HTMLInputAttributes {
		value?: string;
		class?: string;
	}

	let { value = $bindable(""), class: className, ...rest }: Props = $props();
</script>

<input
	class={cn(
		"netz-ui-field flex h-(--netz-space-control-height-md) w-full rounded-(--netz-radius-md) px-3.5 py-2 text-sm tracking-[-0.005em] text-(--netz-text-primary) placeholder:text-(--netz-text-muted) disabled:cursor-not-allowed disabled:bg-(--netz-surface-inset) disabled:opacity-50",
		className,
	)}
	{value}
	{...rest}
/>
