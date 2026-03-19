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
		totalCount,
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
		/** When provided, enables server-side pagination mode. Used instead of getFilteredRowModel().rows.length for totals and page count. */
		totalCount?: number;
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
	let manualPagination = $derived(totalCount !== undefined);

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
	let rowTotal = $derived(manualPagination ? (totalCount ?? 0) : table.getFilteredRowModel().rows.length);
	let pageCount = $derived(manualPagination ? Math.ceil(rowTotal / effectivePageSize) : table.getPageCount());

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
						class="netz-ui-field flex h-[var(--netz-space-control-height-md)] w-full max-w-sm rounded-[var(--netz-radius-md)] px-3.5 py-2 text-sm tracking-[-0.005em] text-[var(--netz-text-primary)] placeholder:text-[var(--netz-text-muted)]"
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

	<div class="overflow-hidden rounded-[var(--netz-radius-lg)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-panel)] shadow-[var(--netz-shadow-1)]">
		<table class="w-full caption-bottom text-sm">
			<thead class="border-b border-[var(--netz-border-subtle)] bg-[var(--netz-surface-highlight)]">
				{#each table.getHeaderGroups() as headerGroup}
					<tr>
						{#each headerGroup.headers as header}
							<th class="h-11 px-4 text-left align-middle text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--netz-text-muted)]">
								{#if !header.isPlaceholder}
									{#if header.column.getCanSort()}
										<button
											class="flex items-center gap-1.5 text-[var(--netz-text-muted)] transition-colors duration-[var(--netz-duration-fast)] hover:text-[var(--netz-text-secondary)]"
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
					<tr class="border-b border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] transition-colors last:border-b-0 hover:bg-[var(--netz-accent-soft)]">
						{#each row.getVisibleCells() as cell}
							<td class="px-4 py-3.5 align-middle text-[var(--netz-text-primary)]">
								<FlexRender content={cell.column.columnDef.cell} context={cell.getContext()} />
							</td>
						{/each}
					</tr>
					{#if expandedRow && row.getIsExpanded()}
						<tr class="border-b border-[var(--netz-border-subtle)] bg-[var(--netz-surface-inset)] last:border-b-0">
							<td colspan={columns.length} class="px-4 py-3">
								{@render expandedRow(row.original)}
							</td>
						</tr>
					{/if}
				{:else}
					<tr>
						<td colspan={columns.length} class="h-24 bg-[var(--netz-surface-elevated)] text-center text-[var(--netz-text-muted)]">
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

	{#if pageCount > 1}
		<div class="mt-3 flex flex-col gap-3 rounded-[var(--netz-radius-lg)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-highlight)] px-4 py-3 text-sm text-[var(--netz-text-secondary)] sm:flex-row sm:items-center sm:justify-between">
			<span>
				Showing {table.getState().pagination.pageIndex * table.getState().pagination.pageSize + 1}-{Math.min(
					(table.getState().pagination.pageIndex + 1) * table.getState().pagination.pageSize,
					rowTotal,
				)} of {rowTotal}
			</span>
			<div class="flex items-center gap-2">
				<select
					class="netz-ui-field h-[var(--netz-space-control-height-sm)] rounded-[var(--netz-radius-md)] bg-[var(--netz-surface-elevated)] px-2.5 text-xs text-[var(--netz-text-primary)]"
					value={table.getState().pagination.pageSize}
					onchange={(event) =>
						table.setPageSize(clampPageSize(Number((event.target as HTMLSelectElement).value)))}
				>
					{#each [10, 20, 50, 100] as size}
						<option value={size}>{size} / page</option>
					{/each}
				</select>
				<button
					class="inline-flex h-[var(--netz-space-control-height-sm)] w-[var(--netz-space-control-height-sm)] items-center justify-center rounded-[var(--netz-radius-md)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] text-[var(--netz-text-secondary)] shadow-[var(--netz-shadow-1)] transition-[color,background-color,border-color] duration-[var(--netz-duration-fast)] hover:bg-[var(--netz-accent-soft)] hover:text-[var(--netz-text-primary)] disabled:cursor-not-allowed disabled:opacity-50"
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
				<span class="min-w-14 text-center text-xs font-semibold tracking-[0.02em] text-[var(--netz-text-secondary)]">
					{table.getState().pagination.pageIndex + 1} / {pageCount}
				</span>
				<button
					class="inline-flex h-[var(--netz-space-control-height-sm)] w-[var(--netz-space-control-height-sm)] items-center justify-center rounded-[var(--netz-radius-md)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] text-[var(--netz-text-secondary)] shadow-[var(--netz-shadow-1)] transition-[color,background-color,border-color] duration-[var(--netz-duration-fast)] hover:bg-[var(--netz-accent-soft)] hover:text-[var(--netz-text-primary)] disabled:cursor-not-allowed disabled:opacity-50"
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
