<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import type { Snippet } from "svelte";
	import type { HTMLButtonAttributes, HTMLAnchorAttributes } from "svelte/elements";

	type Variant = "default" | "secondary" | "destructive" | "outline" | "ghost" | "link";
	type Size = "sm" | "default" | "lg";

	interface Props extends HTMLButtonAttributes {
		variant?: Variant;
		size?: Size;
		href?: HTMLAnchorAttributes["href"];
		children?: Snippet;
	}

	let {
		variant = "default",
		size = "default",
		href,
		class: className,
		children,
		...rest
	}: Props = $props();

	const variantStyles: Record<Variant, string> = {
		default:
			"border border-(--ii-border-accent) bg-(--ii-brand-primary) text-(--ii-primary-foreground) shadow-(--ii-shadow-1) hover:-translate-y-px hover:shadow-(--ii-shadow-2) active:translate-y-0 active:shadow-(--ii-shadow-1)",
		secondary:
			"border border-(--ii-border-subtle) bg-(--ii-surface-panel) text-(--ii-text-primary) shadow-(--ii-shadow-1) hover:-translate-y-px hover:bg-(--ii-surface-highlight) hover:shadow-(--ii-shadow-2) active:translate-y-0 active:shadow-(--ii-shadow-1)",
		destructive:
			"border border-transparent bg-(--ii-danger) text-white shadow-(--ii-shadow-1) hover:-translate-y-px hover:shadow-(--ii-shadow-2) active:translate-y-0 active:shadow-(--ii-shadow-1)",
		outline:
			"border border-(--ii-border-subtle) bg-(--ii-surface-elevated) text-(--ii-text-primary) hover:border-(--ii-border) hover:bg-(--ii-surface-highlight)",
		ghost:
			"border border-transparent bg-transparent text-(--ii-text-primary) hover:bg-(--ii-accent-soft)",
		link: "h-auto border-none bg-transparent p-0 text-(--ii-brand-secondary) underline-offset-4 hover:text-(--ii-brand-primary) hover:underline",
	};

	const sizeStyles: Record<Size, string> = {
		sm: "h-(--ii-space-control-height-sm) rounded-(--ii-radius-md) px-3 text-xs",
		default: "h-(--ii-space-control-height-md) rounded-(--ii-radius-md) px-4 text-sm",
		lg: "h-(--ii-space-control-height-lg) rounded-(--ii-radius-lg) px-6 text-base",
	};
</script>

{#if href}
<a
	{href}
	class={cn(
		"inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium tracking-[-0.01em] [font-feature-settings:var(--ii-font-features)] transition-[color,background-color,border-color,box-shadow,transform] duration-(--ii-duration-fast) ease-(--ii-ease-out) focus-visible:outline-none focus-visible:shadow-(--ii-shadow-focus)",
		variantStyles[variant],
		sizeStyles[size],
		className,
	)}
>
	{@render children?.()}
</a>
{:else}
<button
	class={cn(
		"inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium tracking-[-0.01em] [font-feature-settings:var(--ii-font-features)] transition-[color,background-color,border-color,box-shadow,transform] duration-(--ii-duration-fast) ease-(--ii-ease-out) focus-visible:outline-none focus-visible:shadow-(--ii-shadow-focus) disabled:pointer-events-none disabled:translate-y-0 disabled:shadow-none disabled:opacity-50",
		variantStyles[variant],
		sizeStyles[size],
		className,
	)}
	{...rest}
>
	{@render children?.()}
</button>
{/if}
