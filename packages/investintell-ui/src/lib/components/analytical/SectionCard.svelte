<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import type { Snippet } from "svelte";
	import * as Card from "$lib/components/ui/card";
	import * as Collapsible from "$lib/components/ui/collapsible";

	interface Props {
		title: string;
		subtitle?: string;
		collapsible?: boolean;
		collapsed?: boolean;
		loading?: boolean;
		class?: string;
		actions?: Snippet;
		children: Snippet;
	}

	let {
		title,
		subtitle,
		collapsible = false,
		collapsed = $bindable(false),
		loading = false,
		class: className,
		actions,
		children,
	}: Props = $props();
</script>

{#snippet headerContent()}
	<div class="min-w-0 flex-1">
		<h3 class="text-[0.95rem] font-semibold tracking-[-0.012em] text-(--ii-text-primary)">
			{title}
		</h3>
		{#if subtitle}
			<p class="mt-1 text-[0.7rem] font-semibold uppercase tracking-[0.08em] text-(--ii-text-muted)">
				{subtitle}
			</p>
		{/if}
	</div>

	<div class="flex shrink-0 items-center gap-2">
		{#if actions}
			<!-- svelte-ignore a11y_interactive_supports_focus -->
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<div role="presentation" onclick={(e) => e.stopPropagation()}>
				{@render actions()}
			</div>
		{/if}

		{#if collapsible}
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="16"
				height="16"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				class="shrink-0 text-(--ii-text-tertiary) transition-transform duration-(--ii-duration-fast)"
				style={collapsed ? "transform: rotate(-90deg);" : "transform: rotate(0deg);"}
				aria-hidden="true"
			>
				<path d="m6 9 6 6 6-6" />
			</svg>
		{/if}
	</div>
{/snippet}

{#snippet bodyContent()}
	<Card.Content
		class="relative border-t border-(--ii-border-subtle) bg-(--ii-surface-panel) px-(--ii-space-card-padding-lg) py-(--ii-space-card-padding)"
	>
		{#if loading}
			<div
				class="absolute inset-0 z-10 flex flex-col gap-3 rounded-b-(--ii-radius-lg) bg-(--ii-surface-panel) p-(--ii-space-card-padding-lg)"
				aria-busy="true"
				aria-label="Loading..."
			>
				<div class="h-4 w-3/4 animate-pulse rounded bg-(--ii-surface-inset)"></div>
				<div class="h-4 w-1/2 animate-pulse rounded bg-(--ii-surface-inset)"></div>
				<div class="h-4 w-2/3 animate-pulse rounded bg-(--ii-surface-inset)"></div>
			</div>
		{/if}

		{@render children()}
	</Card.Content>
{/snippet}

<Card.Root
	class={cn(
		"ii-ui-surface overflow-hidden rounded-(--ii-radius-lg) p-0 gap-0 ring-0 bg-transparent",
		className,
	)}
>
	{#if collapsible}
		<Collapsible.Root open={!collapsed} onOpenChange={(v) => { collapsed = !v; }}>
			<Collapsible.Trigger
				class={cn(
					"flex w-full items-center justify-between gap-4 bg-(--ii-surface-highlight) px-(--ii-space-card-padding-lg) py-[18px] transition-[background-color,box-shadow]",
					"cursor-pointer select-none hover:bg-(--ii-accent-soft)",
				)}
			>
				{@render headerContent()}
			</Collapsible.Trigger>
			<Collapsible.Content>
				{@render bodyContent()}
			</Collapsible.Content>
		</Collapsible.Root>
	{:else}
		<Card.Header
			class="flex items-center justify-between gap-4 bg-(--ii-surface-highlight) px-(--ii-space-card-padding-lg) py-[18px]"
		>
			{@render headerContent()}
		</Card.Header>
		{@render bodyContent()}
	{/if}
</Card.Root>
