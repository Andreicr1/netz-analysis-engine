<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";
	import type { HTMLAttributes } from "svelte/elements";

	interface Props extends HTMLAttributes<HTMLDivElement> {
		class?: string;
		children?: Snippet;
	}

	let { class: className, children, ...rest }: Props = $props();
</script>

<div
	class={cn(
		"netz-ui-surface overflow-hidden rounded-(--netz-radius-lg)",
		className,
	)}
	{...rest}
>
	{@render children?.()}
</div>
