<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";
	import type { HTMLButtonAttributes } from "svelte/elements";

	type Variant = "default" | "secondary" | "destructive" | "outline" | "ghost" | "link";
	type Size = "sm" | "default" | "lg";

	interface Props extends HTMLButtonAttributes {
		variant?: Variant;
		size?: Size;
		children?: Snippet;
	}

	let {
		variant = "default",
		size = "default",
		class: className,
		children,
		...rest
	}: Props = $props();

	const variantStyles: Record<Variant, string> = {
		default:
			"bg-[var(--netz-brand-primary)] text-white hover:bg-[var(--netz-brand-primary)]/90",
		secondary:
			"bg-[var(--netz-brand-secondary)] text-white hover:bg-[var(--netz-brand-secondary)]/90",
		destructive:
			"bg-[var(--netz-danger)] text-white hover:bg-[var(--netz-danger)]/90",
		outline:
			"border border-[var(--netz-border)] bg-transparent text-[var(--netz-text-primary)] hover:bg-[var(--netz-surface-alt)]",
		ghost:
			"bg-transparent text-[var(--netz-text-primary)] hover:bg-[var(--netz-surface-alt)]",
		link: "bg-transparent text-[var(--netz-brand-secondary)] underline-offset-4 hover:underline p-0 h-auto",
	};

	const sizeStyles: Record<Size, string> = {
		sm: "h-8 px-3 text-xs rounded-md",
		default: "h-9 px-4 text-sm rounded-md",
		lg: "h-11 px-6 text-base rounded-md",
	};
</script>

<button
	class={cn(
		"inline-flex items-center justify-center font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--netz-brand-secondary)] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
		variantStyles[variant],
		sizeStyles[size],
		className,
	)}
	{...rest}
>
	{@render children?.()}
</button>
