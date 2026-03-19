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
			"border border-[var(--netz-border-accent)] bg-[var(--netz-brand-primary)] text-[var(--netz-primary-foreground)] shadow-[var(--netz-shadow-1)] hover:-translate-y-px hover:shadow-[var(--netz-shadow-2)] active:translate-y-0 active:shadow-[var(--netz-shadow-1)]",
		secondary:
			"border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-panel)] text-[var(--netz-text-primary)] shadow-[var(--netz-shadow-1)] hover:-translate-y-px hover:bg-[var(--netz-surface-highlight)] hover:shadow-[var(--netz-shadow-2)] active:translate-y-0 active:shadow-[var(--netz-shadow-1)]",
		destructive:
			"border border-transparent bg-[var(--netz-danger)] text-white shadow-[var(--netz-shadow-1)] hover:-translate-y-px hover:shadow-[var(--netz-shadow-2)] active:translate-y-0 active:shadow-[var(--netz-shadow-1)]",
		outline:
			"border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] text-[var(--netz-text-primary)] hover:border-[var(--netz-border)] hover:bg-[var(--netz-surface-highlight)]",
		ghost:
			"border border-transparent bg-transparent text-[var(--netz-text-primary)] hover:bg-[var(--netz-accent-soft)]",
		link: "h-auto border-none bg-transparent p-0 text-[var(--netz-brand-secondary)] underline-offset-4 hover:text-[var(--netz-brand-primary)] hover:underline",
	};

	const sizeStyles: Record<Size, string> = {
		sm: "h-[var(--netz-space-control-height-sm)] rounded-[var(--netz-radius-md)] px-3 text-xs",
		default: "h-[var(--netz-space-control-height-md)] rounded-[var(--netz-radius-md)] px-4 text-sm",
		lg: "h-[var(--netz-space-control-height-lg)] rounded-[var(--netz-radius-lg)] px-6 text-base",
	};
</script>

<button
	class={cn(
		"inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium tracking-[-0.01em] transition-[color,background-color,border-color,box-shadow,transform] duration-[var(--netz-duration-fast)] ease-[var(--netz-ease-out)] focus-visible:outline-none focus-visible:shadow-[var(--netz-shadow-focus)] disabled:pointer-events-none disabled:translate-y-0 disabled:shadow-none disabled:opacity-50",
		variantStyles[variant],
		sizeStyles[size],
		className,
	)}
	{...rest}
>
	{@render children?.()}
</button>
