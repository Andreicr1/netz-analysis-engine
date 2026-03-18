<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";
	import {
		createTable,
		FlexRender,
		getCoreRowModel,
		getExpandedRowModel,
		getFilteredRowModel,
		getPaginationRowModel,
		getSortedRowModel,
		type ColumnDef,
		type ColumnFiltersState,
		type ExpandedState,
		type SortingState,
	} from "@tanstack/svelte-table";

	type RowData = Record<string, unknown>;

	function clampPageSize(value: number): number {
		return Math.min(Math.max(value, 1), 100);
	}

	let {
		data,
		columns,
		class: className,
		pageSize = 10,
		filterColumn,
		filterPlaceholder = "Filter...",
		filterBar,
		toolbar,
		emptyState,
		expandedRow,
	}: {
		data: RowData[];
		columns: ColumnDef<RowData, unknown>[];
		class?: string;
		pageSize?: number;
		filterColumn?: string;
		filterPlaceholder?: string;
		filterBar?: Snippet<[unknown]>;
		toolbar?: Snippet<[unknown]>;
		emptyState?: Snippet;
		expandedRow?: Snippet<[RowData]>;
	} = $props();

	let sorting = $state<SortingState>([]);
	let columnFilters = $state<ColumnFiltersState>([]);
	let expanded = $state<ExpandedState>({});
	let pagination = $state({
		pageIndex: 0,
		pageSize: 10,
	});
	let effectivePageSize = $derived(clampPageSize(pageSize));

	let table = createTable({
		get data() {
			return data;
		},
		get columns() {
			return columns;
		},
		state: {
			get sorting() {
				return sorting;
			},
			get columnFilters() {
				return columnFilters;
			},
			get expanded() {
				return expanded;
			},
			get pagination() {
				return pagination;
			},
		},
		enableMultiSort: true,
		getRowCanExpand: () => Boolean(expandedRow),
		onSortingChange: (updater) => {
			sorting = typeof updater === "function" ? updater(sorting) : updater;
		},
		onColumnFiltersChange: (updater) => {
			columnFilters = typeof updater === "function" ? updater(columnFilters) : updater;
		},
		onExpandedChange: (updater) => {
			expanded = typeof updater === "function" ? updater(expanded) : updater;
		},
		onPaginationChange: (updater) => {
			pagination = typeof updater === "function" ? updater(pagination) : updater;
		},
		getCoreRowModel: getCoreRowModel(),
		getSortedRowModel: getSortedRowModel(),
		getFilteredRowModel: getFilteredRowModel(),
		getExpandedRowModel: getExpandedRowModel(),
		getPaginationRowModel: getPaginationRowModel(),
	});

	$effect(() => {
		if (pagination.pageSize !== effectivePageSize) {
			pagination = {
				...pagination,
				pageIndex: 0,
				pageSize: effectivePageSize,
			};
		}
	});
</script>

<div class={cn("w-full", className)}>
	{#if filterBar || toolbar || filterColumn}
		<div class="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
			<div class="flex flex-1 items-center gap-3">
				{#if filterBar}
					{@render filterBar(table)}
				{:else if filterColumn}
					<input
						class="flex h-9 w-full max-w-sm rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-1 text-sm text-[var(--netz-text-primary)] placeholder:text-[var(--netz-text-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--netz-brand-secondary)]"
						placeholder={filterPlaceholder}
						value={(table.getColumn(filterColumn)?.getFilterValue() as string) ?? ""}
						oninput={(event) => {
							table
								.getColumn(filterColumn!)
								?.setFilterValue((event.target as HTMLInputElement).value);
						}}
					/>
				{/if}
			</div>

			{#if toolbar}
				<div class="flex items-center gap-3">
					{@render toolbar(table)}
				</div>
			{/if}
		</div>
	{/if}

	<div class="rounded-md border border-[var(--netz-border)]">
		<table class="w-full caption-bottom text-sm">
			<thead class="bg-[var(--netz-brand-primary)]">
				{#each table.getHeaderGroups() as headerGroup}
					<tr>
						{#each headerGroup.headers as header}
							<th class="h-10 px-4 text-left align-middle text-xs font-medium text-white">
								{#if !header.isPlaceholder}
									{#if header.column.getCanSort()}
										<button
											class="flex items-center gap-1 hover:opacity-80"
											onclick={(event) =>
												header.column.toggleSorting(
													header.column.getIsSorted() === "asc",
													event.shiftKey,
												)}
										>
											<FlexRender content={header.column.columnDef.header} context={header.getContext()} />
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
													><path d="m7 15 5 5 5-5" /><path d="m7 9 5-5 5 5" /></svg
												>
											{/if}
										</button>
									{:else}
										<FlexRender content={header.column.columnDef.header} context={header.getContext()} />
									{/if}
								{/if}
							</th>
						{/each}
					</tr>
				{/each}
			</thead>
			<tbody>
				{#each table.getRowModel().rows as row}
					<tr class="border-b border-[var(--netz-border)] transition-colors hover:bg-[var(--netz-surface-alt)]">
						{#each row.getVisibleCells() as cell}
							<td class="px-4 py-3 align-middle text-[var(--netz-text-primary)]">
								<FlexRender content={cell.column.columnDef.cell} context={cell.getContext()} />
							</td>
						{/each}
					</tr>
					{#if expandedRow && row.getIsExpanded()}
						<tr class="border-b border-[var(--netz-border)] bg-[var(--netz-surface-alt)]/60">
							<td colspan={columns.length} class="px-4 py-3">
								{@render expandedRow(row.original)}
							</td>
						</tr>
					{/if}
				{:else}
					<tr>
						<td colspan={columns.length} class="h-24 text-center text-[var(--netz-text-muted)]">
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

	{#if table.getPageCount() > 1}
		<div class="flex items-center justify-between px-2 py-4 text-sm text-[var(--netz-text-secondary)]">
			<span>
				Showing {table.getState().pagination.pageIndex * table.getState().pagination.pageSize + 1}-{Math.min(
					(table.getState().pagination.pageIndex + 1) * table.getState().pagination.pageSize,
					table.getFilteredRowModel().rows.length,
				)} of {table.getFilteredRowModel().rows.length}
			</span>
			<div class="flex items-center gap-2">
				<select
					class="h-8 rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-2 text-xs"
					value={table.getState().pagination.pageSize}
					onchange={(event) =>
						table.setPageSize(clampPageSize(Number((event.target as HTMLSelectElement).value)))}
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
				<span class="text-xs">{table.getState().pagination.pageIndex + 1} / {table.getPageCount()}</span>
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
