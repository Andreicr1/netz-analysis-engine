<script lang="ts">
	import { cn } from "../utils/cn.js";
	import { DropdownMenu as BitsDropdownMenu } from "bits-ui";
	import type { Snippet } from "svelte";

	interface MenuItem {
		label: string;
		onclick: () => void;
		destructive?: boolean;
	}

	interface Props {
		items: MenuItem[];
		class?: string;
		children?: Snippet;
	}

	let { items, class: className, children }: Props = $props();
</script>

<BitsDropdownMenu.Root>
	<BitsDropdownMenu.Trigger>
		{#snippet child({ props })}
			<span {...props} class="inline-flex">
				{@render children?.()}
			</span>
		{/snippet}
	</BitsDropdownMenu.Trigger>
	<BitsDropdownMenu.Content
		class={cn(
			"z-50 min-w-[10rem] overflow-hidden rounded-(--netz-radius-lg) border border-(--netz-border-subtle) bg-(--netz-surface-panel) p-1.5 shadow-(--netz-shadow-floating) netz-animate-scale-in",
			className,
		)}
		sideOffset={4}
	>
		{#each items as item}
			<BitsDropdownMenu.Item
				class={cn(
					"relative flex min-h-9 cursor-pointer select-none items-center rounded-(--netz-radius-md) px-3 py-2 text-[13px] font-medium outline-none transition-[color,background-color] duration-(--netz-duration-fast) hover:bg-(--netz-accent-soft) focus:bg-(--netz-accent-soft)",
					item.destructive
						? "text-(--netz-danger) hover:bg-(--netz-danger-subtle) focus:bg-(--netz-danger-subtle)"
						: "text-(--netz-text-secondary) hover:text-(--netz-text-primary) focus:text-(--netz-text-primary)",
				)}
				onSelect={item.onclick}
			>
				{item.label}
			</BitsDropdownMenu.Item>
		{/each}
	</BitsDropdownMenu.Content>
</BitsDropdownMenu.Root>
