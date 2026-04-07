<!--
  @component ContextPanel
  Slide-in panel from right side. Internally uses shadcn Sheet for portal rendering,
  focus trap, Escape key handling, and overlay.

  Actively used in:
  - wealth screener (instrument detail, run detail, history panels)
  - wealth instruments page (instrument detail)
  - wealth risk page (risk detail)
  - wealth portfolios page (portfolio detail)
  - wealth FundDetailPanel component (fund detail slide-in)
  - credit pipeline page (deal detail panel)
-->
<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import type { Snippet } from "svelte";
	import * as Sheet from "$lib/components/ui/sheet";

	let {
		open = false,
		onClose,
		title,
		width = "400px",
		class: className,
		children,
	}: {
		open?: boolean;
		onClose: () => void;
		title?: string;
		width?: string;
		class?: string;
		children?: Snippet;
	} = $props();
</script>

<Sheet.Root {open} onOpenChange={(v) => { if (!v) onClose(); }}>
	<Sheet.Content
		side="right"
		class={cn("flex flex-col p-0 sm:max-w-none", className)}
		style="width: {width};"
	>
		<Sheet.Header class="shrink-0 border-b px-5 py-4">
			{#if title}
				<Sheet.Title class="text-base font-semibold">{title}</Sheet.Title>
			{:else}
				<Sheet.Title class="sr-only">Panel</Sheet.Title>
			{/if}
		</Sheet.Header>

		<div class="flex-1 overflow-y-auto p-5">
			{@render children?.()}
		</div>
	</Sheet.Content>
</Sheet.Root>
