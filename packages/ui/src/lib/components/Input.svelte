<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { HTMLInputAttributes } from "svelte/elements";

	interface Props extends HTMLInputAttributes {
		class?: string;
	}

	let { class: className, ...rest }: Props = $props();
</script>

<input
	class={cn(
		"netz-ui-field flex h-[var(--netz-space-control-height-md)] w-full rounded-[var(--netz-radius-md)] px-3.5 py-2 text-sm tracking-[-0.005em] text-[var(--netz-text-primary)] placeholder:text-[var(--netz-text-muted)] disabled:cursor-not-allowed disabled:bg-[var(--netz-surface-inset)] disabled:opacity-50",
		className,
	)}
	{...rest}
/>
