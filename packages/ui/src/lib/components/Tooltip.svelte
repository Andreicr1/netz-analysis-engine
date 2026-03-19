<script lang="ts">
	import { Tooltip } from "bits-ui";
	import type { Snippet } from "svelte";

	interface Props {
		content: string;
		class?: string;
		children?: Snippet;
	}

	let { content, children }: Props = $props();
</script>

<Tooltip.Root delayDuration={200}>
	<Tooltip.Trigger>
		{#snippet child({ props })}
			<span {...props} class="inline-flex">
				{@render children?.()}
			</span>
		{/snippet}
	</Tooltip.Trigger>
	<Tooltip.Content
		class="z-50 overflow-hidden rounded-md border border-(--netz-border) bg-(--netz-brand-primary) px-3 py-1.5 text-xs text-white shadow-md netz-animate-fade-in"
		sideOffset={4}
	>
		{content}
	</Tooltip.Content>
</Tooltip.Root>
