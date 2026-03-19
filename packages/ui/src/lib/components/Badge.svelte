<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";

	type Variant = "default" | "secondary" | "destructive" | "outline";

	interface Props {
		variant?: Variant;
		class?: string;
		children?: Snippet;
	}

	let { variant = "default", class: className, children }: Props = $props();

	const variantStyles: Record<Variant, string> = {
		default:
			"border border-(--netz-border-accent) bg-(--netz-accent-muted) text-(--netz-brand-primary)",
		secondary:
			"border border-(--netz-border-subtle) bg-(--netz-surface-panel) text-(--netz-text-secondary)",
		destructive:
			"border border-transparent bg-(--netz-danger-subtle) text-(--netz-danger)",
		outline:
			"border border-(--netz-border-subtle) bg-transparent text-(--netz-text-secondary)",
	};
</script>

<span
	class={cn(
		"inline-flex items-center whitespace-nowrap rounded-(--netz-radius-pill) px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.08em] transition-[color,background-color,border-color]",
		variantStyles[variant],
		className,
	)}
>
	{@render children?.()}
</span>
