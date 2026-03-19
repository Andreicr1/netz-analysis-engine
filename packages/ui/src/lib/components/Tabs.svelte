<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";

	interface TabItem {
		value: string;
		label: string;
	}

	interface Props {
		value?: string;
		onValueChange?: (value: string) => void;
		items: TabItem[];
		class?: string;
		children?: Snippet<[string]>;
	}

	let {
		value = $bindable(""),
		onValueChange,
		items,
		class: className,
		children,
	}: Props = $props();

	let activeValue = $derived(value || items[0]?.value || "");

	function select(v: string) {
		value = v;
		onValueChange?.(v);
	}
</script>

<div class={cn("w-full", className)}>
	<!-- Tab triggers -->
	<div
		class="inline-flex min-h-[var(--netz-space-control-height-lg)] items-center justify-start rounded-[var(--netz-radius-lg)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-inset)] p-1"
		role="tablist"
	>
		{#each items as item}
			<button
				role="tab"
				aria-selected={activeValue === item.value}
				class={cn(
					"inline-flex min-h-[var(--netz-space-control-height-md)] items-center justify-center whitespace-nowrap rounded-[var(--netz-radius-md)] px-3.5 py-1.5 text-sm font-medium tracking-[-0.01em] transition-[color,background-color,box-shadow] duration-[var(--netz-duration-fast)] focus-visible:outline-none focus-visible:shadow-[var(--netz-shadow-focus)]",
					activeValue === item.value
						? "bg-[var(--netz-surface-elevated)] text-[var(--netz-text-primary)] shadow-[var(--netz-shadow-1)]"
						: "text-[var(--netz-text-muted)] hover:bg-[var(--netz-accent-soft)] hover:text-[var(--netz-text-secondary)]",
				)}
				onclick={() => select(item.value)}
			>
				{item.label}
			</button>
		{/each}
	</div>

	<!-- Tab content -->
	<div class="mt-2" role="tabpanel">
		{@render children?.(activeValue)}
	</div>
</div>
