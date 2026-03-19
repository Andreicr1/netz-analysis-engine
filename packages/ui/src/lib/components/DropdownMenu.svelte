<script lang="ts">
	import { cn } from "../utils/cn.js";
	import { DropdownMenu } from "bits-ui";
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

<DropdownMenu.Root>
	<DropdownMenu.Trigger>
		{#snippet child({ props })}
			<span {...props} class="inline-flex">
				{@render children?.()}
			</span>
		{/snippet}
	</DropdownMenu.Trigger>
	<DropdownMenu.Content
		class={cn(
			"z-50 min-w-[10rem] overflow-hidden rounded-[var(--netz-radius-lg)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-panel)] p-1.5 shadow-[var(--netz-shadow-floating)] netz-animate-scale-in",
			className,
		)}
		sideOffset={4}
	>
		{#each items as item}
			<DropdownMenu.Item
				class={cn(
					"relative flex min-h-9 cursor-pointer select-none items-center rounded-[var(--netz-radius-md)] px-3 py-2 text-[13px] font-medium outline-none transition-[color,background-color] duration-[var(--netz-duration-fast)] hover:bg-[var(--netz-accent-soft)] focus:bg-[var(--netz-accent-soft)]",
					item.destructive
						? "text-[var(--netz-danger)] hover:bg-[var(--netz-danger-subtle)] focus:bg-[var(--netz-danger-subtle)]"
						: "text-[var(--netz-text-secondary)] hover:text-[var(--netz-text-primary)] focus:text-[var(--netz-text-primary)]",
				)}
				onSelect={item.onclick}
			>
				{item.label}
			</DropdownMenu.Item>
		{/each}
	</DropdownMenu.Content>
</DropdownMenu.Root>
