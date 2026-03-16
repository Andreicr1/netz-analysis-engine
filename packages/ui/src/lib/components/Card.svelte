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
		"rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface)] shadow-sm",
		className,
	)}
>
	{@render children?.()}
</div>
