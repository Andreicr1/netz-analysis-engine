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
			"bg-[var(--netz-brand-primary)] text-white",
		secondary:
			"bg-[var(--netz-brand-accent)]/20 text-[var(--netz-text-secondary)]",
		destructive:
			"bg-[var(--netz-danger)] text-white",
		outline:
			"border border-[var(--netz-border)] bg-transparent text-[var(--netz-text-secondary)]",
	};
</script>

<span
	class={cn(
		"inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors",
		variantStyles[variant],
		className,
	)}
>
	{@render children?.()}
</span>
