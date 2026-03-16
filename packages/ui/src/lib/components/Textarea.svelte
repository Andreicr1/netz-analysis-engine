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
		"flex min-h-[80px] w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] shadow-sm transition-colors placeholder:text-[var(--netz-text-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--netz-brand-secondary)] focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50",
		className,
	)}
	{...rest}
></textarea>
