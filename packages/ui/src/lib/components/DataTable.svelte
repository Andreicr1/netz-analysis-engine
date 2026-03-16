<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";
	import {
		createSvelteTable,
		getCoreRowModel,
		getSortedRowModel,
		getFilteredRowModel,
		getPaginationRowModel,
		flexRender,
		type ColumnDef,
		type SortingState,
		type ColumnFiltersState,
		type TableOptions,
	} from "@tanstack/svelte-table";

	let {
		data,
		columns,
		class: className,
		pageSize = 10,
		filterColumn,
		filterPlaceholder = "Filter...",
		toolbar,
		emptyState,
	}: {
		data: Record<string, unknown>[];
		columns: ColumnDef<Record<string, unknown>, unknown>[];
		class?: string;
		pageSize?: number;
		filterColumn?: string;
		filterPlaceholder?: string;
		toolbar?: Snippet<[unknown]>;
		emptyState?: Snippet;
	} = $props();

	let sorting = $state<SortingState>([]);
	let columnFilters = $state<ColumnFiltersState>([]);

	let options = $derived<TableOptions<Record<string, unknown>>>({
		data,
		columns,
		state: {
			sorting,
			columnFilters,
		},
		onSortingChange: (updater) => {
			sorting = typeof updater === "function" ? updater(sorting) : updater;
		},
		onColumnFiltersChange: (updater) => {
			columnFilters =
				typeof updater === "function" ? updater(columnFilters) : updater;
		},
		getCoreRowModel: getCoreRowModel(),
		getSortedRowModel: getSortedRowModel(),
		getFilteredRowModel: getFilteredRowModel(),
		getPaginationRowModel: getPaginationRowModel(),
		initialState: {
			pagination: { pageSize },
		},
	});

	let tableStore = $derived(createSvelteTable(options));

	/* Unwrap the Readable store via Svelte 5 $derived + subscribe */
	let tableInstance = $state<ReturnType<typeof unwrapStore> | null>(null);

	function unwrapStore(store: typeof tableStore) {
		let value: any;
		const unsub = store.subscribe((v: any) => { value = v; });
		unsub();
		return value;
	}

	$effect(() => {
		const unsub = tableStore.subscribe((v: any) => {
			tableInstance = v;
		});
		return unsub;
	});
</script>

{#if tableInstance}
	{@const table = tableInstance}
	<div class={cn("w-full", className)}>
		<!-- Toolbar -->
		{#if toolbar}
			{@render toolbar(table)}
		{:else if filterColumn}
			<div class="flex items-center py-4">
				<input
					class="flex h-9 w-full max-w-sm rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-1 text-sm text-[var(--netz-text-primary)] placeholder:text-[var(--netz-text-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--netz-brand-secondary)]"
					placeholder={filterPlaceholder}
					value={(table.getColumn(filterColumn)?.getFilterValue() as string) ?? ""}
					oninput={(e) => {
						table
							.getColumn(filterColumn!)
							?.setFilterValue((e.target as HTMLInputElement).value);
					}}
				/>
			</div>
		{/if}

		<!-- Table -->
		<div class="rounded-md border border-[var(--netz-border)]">
			<table class="w-full caption-bottom text-sm">
				<thead class="bg-[var(--netz-brand-primary)]">
					{#each table.getHeaderGroups() as headerGroup}
						<tr>
							{#each headerGroup.headers as header}
								<th
									class="h-10 px-4 text-left align-middle text-xs font-medium text-white"
								>
									{#if !header.isPlaceholder}
										{#if header.column.getCanSort()}
											<button
												class="flex items-center gap-1 hover:opacity-80"
												onclick={() =>
													header.column.toggleSorting(
														header.column.getIsSorted() === "asc",
													)}
											>
												<svelte:component
													this={flexRender(
														header.column.columnDef.header,
														header.getContext(),
													)}
												/>
												{#if header.column.getIsSorted() === "asc"}
													<svg
														xmlns="http://www.w3.org/2000/svg"
														width="12"
														height="12"
														viewBox="0 0 24 24"
														fill="none"
														stroke="currentColor"
														stroke-width="2"
														><path d="m5 15 7-7 7 7" /></svg
													>
												{:else if header.column.getIsSorted() === "desc"}
													<svg
														xmlns="http://www.w3.org/2000/svg"
														width="12"
														height="12"
														viewBox="0 0 24 24"
														fill="none"
														stroke="currentColor"
														stroke-width="2"
														><path d="m19 9-7 7-7-7" /></svg
													>
												{:else}
													<svg
														xmlns="http://www.w3.org/2000/svg"
														width="12"
														height="12"
														viewBox="0 0 24 24"
														fill="none"
														stroke="currentColor"
														stroke-width="2"
														opacity="0.4"
														><path d="m7 15 5 5 5-5" /><path
															d="m7 9 5-5 5 5"
														/></svg
													>
												{/if}
											</button>
										{:else}
											<svelte:component
												this={flexRender(
													header.column.columnDef.header,
													header.getContext(),
												)}
											/>
										{/if}
									{/if}
								</th>
							{/each}
						</tr>
					{/each}
				</thead>
				<tbody>
					{#each table.getRowModel().rows as row}
						<tr
							class="border-b border-[var(--netz-border)] transition-colors hover:bg-[var(--netz-surface-alt)]"
						>
							{#each row.getVisibleCells() as cell}
								<td class="px-4 py-3 align-middle text-[var(--netz-text-primary)]">
									<svelte:component
										this={flexRender(
											cell.column.columnDef.cell,
											cell.getContext(),
										)}
									/>
								</td>
							{/each}
						</tr>
					{:else}
						<tr>
							<td
								colspan={columns.length}
								class="h-24 text-center text-[var(--netz-text-muted)]"
							>
								{#if emptyState}
									{@render emptyState()}
								{:else}
									No results.
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- Pagination -->
		{#if table.getPageCount() > 1}
			<div
				class="flex items-center justify-between px-2 py-4 text-sm text-[var(--netz-text-secondary)]"
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
		{/if}
	</div>
{/if}
