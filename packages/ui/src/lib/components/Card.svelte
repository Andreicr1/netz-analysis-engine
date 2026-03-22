<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";
	import type { HTMLAttributes } from "svelte/elements";

	interface Props extends HTMLAttributes<HTMLDivElement> {
		class?: string;
		children?: Snippet;
		elevation?: 1 | 2 | 3;
		accent?: string;
	}

	let { class: className, children, elevation, accent, ...rest }: Props = $props();

	const shadowClass = $derived(
		elevation === 3 ? "shadow-(--netz-shadow-3)" :
		elevation === 2 ? "shadow-(--netz-shadow-2)" :
		elevation === 1 ? "shadow-(--netz-shadow-1)" : ""
	);
</script>

<div
	class={cn(
		"netz-ui-surface overflow-hidden rounded-(--netz-radius-lg)",
		shadowClass,
		className,
	)}
	style={accent ? `border-left: 3px solid ${accent};` : undefined}
	{...rest}
>
	{@render children?.()}
</div>
