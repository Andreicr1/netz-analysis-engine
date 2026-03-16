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
		class="inline-flex h-10 items-center justify-start rounded-md bg-[var(--netz-surface-alt)] p-1"
		role="tablist"
	>
		{#each items as item}
			<button
				role="tab"
				aria-selected={activeValue === item.value}
				class={cn(
					"inline-flex items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--netz-brand-secondary)]",
					activeValue === item.value
						? "bg-[var(--netz-surface)] text-[var(--netz-text-primary)] shadow-sm"
						: "text-[var(--netz-text-muted)] hover:text-[var(--netz-text-secondary)]",
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
