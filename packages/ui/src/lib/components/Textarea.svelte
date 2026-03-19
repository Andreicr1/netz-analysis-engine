<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { HTMLTextareaAttributes } from "svelte/elements";

	interface Props extends HTMLTextareaAttributes {
		class?: string;
	}

	let { class: className, ...rest }: Props = $props();
</script>

<textarea
	class={cn(
		"netz-ui-field flex min-h-28 w-full rounded-(--netz-radius-md) px-3.5 py-2.5 text-sm leading-6 tracking-[-0.005em] text-(--netz-text-primary) placeholder:text-(--netz-text-muted) disabled:cursor-not-allowed disabled:bg-(--netz-surface-inset) disabled:opacity-50",
		className,
	)}
	{...rest}
></textarea>
