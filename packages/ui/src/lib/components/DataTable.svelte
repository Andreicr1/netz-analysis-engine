<script lang="ts">
	import { cn } from "../utils/cn.js";
	import Select from "./Select.svelte";
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

	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	type RowData = Record<string, any>;

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
		onRowClick,
	}: {
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		data: RowData[] | any[];
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		columns: ColumnDef<any, any>[];
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
		/** Called when a table row is clicked. */
		onRowClick?: (row: RowData) => void;
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
						class="netz-ui-field flex h-(--netz-space-control-height-md) w-full max-w-sm rounded-(--netz-radius-md) px-3.5 py-2 text-sm tracking-[-0.005em] text-(--netz-text-primary) placeholder:text-(--netz-text-muted)"
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

	<div class="overflow-hidden rounded-lg border border-border bg-card shadow-sm">
		<table class="w-full caption-bottom text-sm">
			<thead class="border-b border-border bg-muted/50">
				{#each table.getHeaderGroups() as headerGroup (headerGroup.id)}
					<tr>
						{#each headerGroup.headers as header (header.id)}
							<th class="h-9 px-3 text-left align-middle text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground {header.column.columnDef.meta?.numeric ? 'text-right' : ''} {header.column.columnDef.meta?.centered ? 'text-center' : ''}">
								{#if !header.isPlaceholder}
									{#if header.column.getCanSort()}
										<button
											class="-ml-3 inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
											onclick={(event) =>
												header.column.toggleSorting(
													header.column.getIsSorted() === "asc",
													event.shiftKey,
												)}
										>
											<FlexRender content={header.column.columnDef.header} context={header.getContext()} />
											{#if header.column.getIsSorted() === "asc"}
												<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 15 7-7 7 7" /></svg>
											{:else if header.column.getIsSorted() === "desc"}
												<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m19 9-7 7-7-7" /></svg>
											{:else}
												<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity="0.4"><path d="m7 15 5 5 5-5" /><path d="m7 9 5-5 5 5" /></svg>
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
				{#each table.getRowModel().rows as row, i (row.id)}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
					<tr
						class="h-10 border-0 transition-colors {i % 2 === 0 ? 'bg-background' : 'bg-slate-50/80'} hover:bg-muted/50 {onRowClick ? 'cursor-pointer' : ''}"
						onclick={() => onRowClick?.(row.original)}
					>
						{#each row.getVisibleCells() as cell (cell.id)}
							<td class="px-3 py-1 align-middle text-sm text-foreground {cell.column.columnDef.meta?.numeric ? 'text-right tabular-nums font-semibold' : ''} {cell.column.columnDef.meta?.muted ? 'text-muted-foreground font-medium' : ''} {cell.column.columnDef.meta?.centered ? 'text-center' : ''}">
								<FlexRender content={cell.column.columnDef.cell} context={cell.getContext()} />
							</td>
						{/each}
					</tr>
					{#if expandedRow && row.getIsExpanded()}
						<tr class="border-b border-border bg-muted/30 last:border-b-0">
							<td colspan={columns.length} class="px-4 py-3">
								{@render expandedRow(row.original)}
							</td>
						</tr>
					{/if}
				{:else}
					<tr>
						<td colspan={columns.length} class="h-24 bg-background text-center text-muted-foreground">
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
		<div class="mt-3 flex flex-col gap-3 rounded-lg border border-border bg-muted/50 px-4 py-3 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
			<span>
				Showing {table.getState().pagination.pageIndex * table.getState().pagination.pageSize + 1}-{Math.min(
					(table.getState().pagination.pageIndex + 1) * table.getState().pagination.pageSize,
					rowTotal,
				)} of {rowTotal}
			</span>
			<div class="flex items-center gap-2">
				<Select
					value={String(table.getState().pagination.pageSize)}
					onValueChange={(v) => table.setPageSize(clampPageSize(Number(v)))}
					options={[
						{ value: "10", label: "10 / page" },
						{ value: "20", label: "20 / page" },
						{ value: "50", label: "50 / page" },
						{ value: "100", label: "100 / page" },
					]}
					class="h-8 text-xs"
				/>
				<button
					class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-muted-foreground shadow-sm transition-colors hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50"
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
				<span class="min-w-14 text-center text-xs font-semibold tracking-[0.02em] text-foreground">
					{table.getState().pagination.pageIndex + 1} / {pageCount}
				</span>
				<button
					class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-muted-foreground shadow-sm transition-colors hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50"
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
