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
			"border border-(--netz-border-accent) bg-(--netz-brand-primary) text-(--netz-primary-foreground) shadow-(--netz-shadow-1) hover:-translate-y-px hover:shadow-(--netz-shadow-2) active:translate-y-0 active:shadow-(--netz-shadow-1)",
		secondary:
			"border border-(--netz-border-subtle) bg-(--netz-surface-panel) text-(--netz-text-primary) shadow-(--netz-shadow-1) hover:-translate-y-px hover:bg-(--netz-surface-highlight) hover:shadow-(--netz-shadow-2) active:translate-y-0 active:shadow-(--netz-shadow-1)",
		destructive:
			"border border-transparent bg-(--netz-danger) text-white shadow-(--netz-shadow-1) hover:-translate-y-px hover:shadow-(--netz-shadow-2) active:translate-y-0 active:shadow-(--netz-shadow-1)",
		outline:
			"border border-(--netz-border-subtle) bg-(--netz-surface-elevated) text-(--netz-text-primary) hover:border-(--netz-border) hover:bg-(--netz-surface-highlight)",
		ghost:
			"border border-transparent bg-transparent text-(--netz-text-primary) hover:bg-(--netz-accent-soft)",
		link: "h-auto border-none bg-transparent p-0 text-(--netz-brand-secondary) underline-offset-4 hover:text-(--netz-brand-primary) hover:underline",
	};

	const sizeStyles: Record<Size, string> = {
		sm: "h-(--netz-space-control-height-sm) rounded-(--netz-radius-md) px-3 text-xs",
		default: "h-(--netz-space-control-height-md) rounded-(--netz-radius-md) px-4 text-sm",
		lg: "h-(--netz-space-control-height-lg) rounded-(--netz-radius-lg) px-6 text-base",
	};
</script>

<button
	class={cn(
		"inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium tracking-[-0.01em] transition-[color,background-color,border-color,box-shadow,transform] duration-(--netz-duration-fast) ease-(--netz-ease-out) focus-visible:outline-none focus-visible:shadow-(--netz-shadow-focus) disabled:pointer-events-none disabled:translate-y-0 disabled:shadow-none disabled:opacity-50",
		variantStyles[variant],
		sizeStyles[size],
		className,
	)}
	{...rest}
>
	{@render children?.()}
</button>
