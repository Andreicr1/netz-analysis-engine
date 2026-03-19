<script lang="ts">
	import { Tooltip as BitsTooltip } from "bits-ui";
	import type { Snippet } from "svelte";

	interface Props {
		content: string;
		class?: string;
		children?: Snippet;
	}

	let { content, children }: Props = $props();
</script>

<BitsTooltip.Root delayDuration={200}>
	<BitsTooltip.Trigger>
		{#snippet child({ props })}
			<span {...props} class="inline-flex">
				{@render children?.()}
			</span>
		{/snippet}
	</BitsTooltip.Trigger>
	<BitsTooltip.Content
		class="z-50 overflow-hidden rounded-md border border-(--netz-border) bg-(--netz-brand-primary) px-3 py-1.5 text-xs text-white shadow-md netz-animate-fade-in"
		sideOffset={4}
	>
		{content}
	</BitsTooltip.Content>
</BitsTooltip.Root>
