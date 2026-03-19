<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";

	interface Props {
		class?: string;
		children?: Snippet;
	}

	let { class: className, children }: Props = $props();
</script>

<div
	class={cn(
		"netz-ui-surface overflow-hidden rounded-[var(--netz-radius-lg)]",
		className,
	)}
>
	{@render children?.()}
</div>
