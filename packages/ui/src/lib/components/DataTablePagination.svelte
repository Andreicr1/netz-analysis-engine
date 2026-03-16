<script lang="ts">
	import type { Table } from "@tanstack/svelte-table";

	interface Props {
		table: Table<any>;
		class?: string;
	}

	let { table, class: className }: Props = $props();
</script>

<div
	class="flex items-center justify-between px-2 py-4 text-sm text-[var(--netz-text-secondary)] {className ??
		''}"
>
	<span>
		Showing {table.getState().pagination.pageIndex *
			table.getState().pagination.pageSize +
			1}-{Math.min(
			(table.getState().pagination.pageIndex + 1) *
				table.getState().pagination.pageSize,
			table.getFilteredRowModel().rows.length,
		)} of {table.getFilteredRowModel().rows.length}
	</span>
	<div class="flex items-center gap-2">
		<select
			class="h-8 rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-2 text-xs"
			value={table.getState().pagination.pageSize}
			onchange={(e) =>
				table.setPageSize(Number((e.target as HTMLSelectElement).value))}
		>
			{#each [10, 20, 50, 100] as size}
				<option value={size}>{size} / page</option>
			{/each}
		</select>
		<button
			class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--netz-border)] disabled:opacity-50"
			onclick={() => table.previousPage()}
			disabled={!table.getCanPreviousPage()}
			aria-label="Previous page"
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="14"
				height="14"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"><path d="m15 18-6-6 6-6" /></svg
			>
		</button>
		<span class="text-xs">
			{table.getState().pagination.pageIndex + 1} / {table.getPageCount()}
		</span>
		<button
			class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--netz-border)] disabled:opacity-50"
			onclick={() => table.nextPage()}
			disabled={!table.getCanNextPage()}
			aria-label="Next page"
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="14"
				height="14"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"><path d="m9 18 6-6-6-6" /></svg
			>
		</button>
	</div>
</div>
