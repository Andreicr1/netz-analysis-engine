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
			"border border-[var(--netz-border-accent)] bg-[var(--netz-accent-muted)] text-[var(--netz-brand-primary)]",
		secondary:
			"border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-panel)] text-[var(--netz-text-secondary)]",
		destructive:
			"border border-transparent bg-[var(--netz-danger-subtle)] text-[var(--netz-danger)]",
		outline:
			"border border-[var(--netz-border-subtle)] bg-transparent text-[var(--netz-text-secondary)]",
	};
</script>

<span
	class={cn(
		"inline-flex items-center rounded-[var(--netz-radius-pill)] px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.08em] transition-[color,background-color,border-color]",
		variantStyles[variant],
		className,
	)}
>
	{@render children?.()}
</span>
