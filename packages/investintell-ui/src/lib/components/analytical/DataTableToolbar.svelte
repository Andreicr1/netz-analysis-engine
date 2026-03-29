<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import type { Table } from "@tanstack/svelte-table";
	import type { Snippet } from "svelte";

	interface Props {
		table: Table<any>;
		filterColumn?: string;
		filterPlaceholder?: string;
		class?: string;
		actions?: Snippet;
	}

	let {
		table,
		filterColumn,
		filterPlaceholder = "Filter...",
		class: className,
		actions,
	}: Props = $props();
</script>

<div class={cn("flex items-center justify-between py-4", className)}>
	<div class="flex flex-1 items-center gap-2">
		{#if filterColumn}
			<input
				class="flex h-9 w-full max-w-sm rounded-md border border-(--ii-border) bg-(--ii-surface) px-3 py-1 text-sm text-(--ii-text-primary) placeholder:text-(--ii-text-muted) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--ii-brand-secondary)"
				placeholder={filterPlaceholder}
				value={table.getColumn(filterColumn)?.getFilterValue() ?? ""}
				oninput={(e) => {
					table
						.getColumn(filterColumn)
						?.setFilterValue((e.target as HTMLInputElement).value);
				}}
			/>
		{/if}
	</div>
	{#if actions}
		<div class="flex items-center gap-2">
			{@render actions()}
		</div>
	{/if}
</div>
