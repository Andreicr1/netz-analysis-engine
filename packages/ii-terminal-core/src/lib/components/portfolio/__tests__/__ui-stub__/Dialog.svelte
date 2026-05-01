<!--
  Test-only Dialog stub. Renders children inline (no Portal) when
  `open` is truthy. Mirrors the real `@investintell/ui` Dialog
  contract just enough for NewPortfolioDialog tests.
-->
<script lang="ts">
	import type { Snippet } from "svelte";

	interface Props {
		open?: boolean;
		onOpenChange?: (open: boolean) => void;
		title?: string;
		children?: Snippet;
	}

	let { open = false, title, children }: Props = $props();
</script>

{#if open}
	<div role="dialog" aria-label={title ?? "dialog"}>
		{#if title}<h2>{title}</h2>{/if}
		{@render children?.()}
	</div>
{/if}
