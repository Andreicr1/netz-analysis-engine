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
			"z-50 min-w-[8rem] overflow-hidden rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] p-1 shadow-md netz-animate-scale-in",
			className,
		)}
		sideOffset={4}
	>
		{#each items as item}
			<DropdownMenu.Item
				class={cn(
					"relative flex cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-sm outline-none transition-colors hover:bg-[var(--netz-surface-alt)] focus:bg-[var(--netz-surface-alt)]",
					item.destructive
						? "text-[var(--netz-danger)] hover:bg-[var(--netz-danger)]/10 focus:bg-[var(--netz-danger)]/10"
						: "text-[var(--netz-text-primary)]",
				)}
				onSelect={item.onclick}
			>
				{item.label}
			</DropdownMenu.Item>
		{/each}
	</DropdownMenu.Content>
</DropdownMenu.Root>
