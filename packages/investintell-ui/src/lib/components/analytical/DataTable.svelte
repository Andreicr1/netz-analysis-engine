<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import SimpleSelect from "./SimpleSelect.svelte";
	import type { Snippet } from "svelte";
	import * as Table from "$lib/components/ui/table";
	import { ArrowUp, ArrowDown, ArrowUpDown, ChevronLeft, ChevronRight, Search } from "lucide-svelte";
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
		pageSize = 20,
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
		/** When provided, enables server-side pagination mode. */
		totalCount?: number;
		filterBar?: Snippet<[unknown]>;
		toolbar?: Snippet<[unknown]>;
		emptyState?: Snippet;
		expandedRow?: Snippet<[RowData]>;
		onRowClick?: (row: RowData) => void;
	} = $props();

	let sorting = $state<SortingState>([]);
	let columnFilters = $state<ColumnFiltersState>([]);
	let expanded = $state<ExpandedState>({});
	let pagination = $state({
		pageIndex: 0,
		pageSize: 20,
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
		<div class="flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between">
			<div class="flex flex-1 items-center gap-3">
				{#if filterBar}
					{@render filterBar(table)}
				{:else if filterColumn}
					<input
						class="flex h-8 w-full max-w-sm rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
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

	<div class="overflow-hidden rounded-lg border shadow-sm">
		<Table.Root>
			<Table.Header>
				{#each table.getHeaderGroups() as headerGroup (headerGroup.id)}
					<Table.Row class="bg-muted hover:bg-muted">
						{#each headerGroup.headers as header (header.id)}
							<Table.Head
								class={cn(
									"h-10 px-2 text-xs font-semibold uppercase tracking-wide",
									(header.column.columnDef.meta as Record<string, unknown>)?.numeric && "text-right",
								)}
							>
								{#if !header.isPlaceholder}
									{#if header.column.getCanSort()}
										<button
											class="inline-flex items-center gap-1 text-muted-foreground transition-colors hover:text-foreground"
											onclick={(event) =>
												header.column.toggleSorting(
													header.column.getIsSorted() === "asc",
													event.shiftKey,
												)}
										>
											<FlexRender content={header.column.columnDef.header} context={header.getContext()} />
											{#if header.column.getIsSorted() === "asc"}
												<ArrowUp class="size-3" />
											{:else if header.column.getIsSorted() === "desc"}
												<ArrowDown class="size-3" />
											{:else}
												<ArrowUpDown class="size-3 opacity-40" />
											{/if}
										</button>
									{:else}
										<FlexRender content={header.column.columnDef.header} context={header.getContext()} />
									{/if}
								{/if}
							</Table.Head>
						{/each}
					</Table.Row>
				{/each}
			</Table.Header>
			<Table.Body>
				{#each table.getRowModel().rows as row, i (row.id)}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
					<Table.Row
						class={cn(
							"h-10 border-b last:border-b-0",
							i % 2 === 0 ? "bg-background" : "bg-muted/50",
							onRowClick && "cursor-pointer",
						)}
						onclick={() => onRowClick?.(row.original)}
					>
						{#each row.getVisibleCells() as cell (cell.id)}
							<Table.Cell
								class={cn(
									"py-2 px-2 text-sm",
									(cell.column.columnDef.meta as Record<string, unknown>)?.numeric &&
										"text-right tabular-nums font-[var(--ii-font-mono,ui-monospace)]",
								)}
							>
								<FlexRender content={cell.column.columnDef.cell} context={cell.getContext()} />
							</Table.Cell>
						{/each}
					</Table.Row>
					{#if expandedRow && row.getIsExpanded()}
						<Table.Row class="border-b bg-muted/30 last:border-b-0">
							<Table.Cell colspan={columns.length} class="px-4 py-3">
								{@render expandedRow(row.original)}
							</Table.Cell>
						</Table.Row>
					{/if}
				{:else}
					<Table.Row>
						<Table.Cell colspan={columns.length} class="h-24 text-center">
							{#if emptyState}
								{@render emptyState()}
							{:else}
								<div class="flex flex-col items-center gap-2 py-6">
									<Search class="size-8 text-muted-foreground" />
									<p class="text-sm font-medium">No results</p>
									<p class="text-xs text-muted-foreground">Try adjusting your filters or broadening your search.</p>
								</div>
							{/if}
						</Table.Cell>
					</Table.Row>
				{/each}
			</Table.Body>
		</Table.Root>
	</div>

	{#if pageCount > 1}
		<div class="mt-3 flex flex-col gap-3 rounded-lg border bg-muted/50 px-4 py-2.5 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
			<span>
				Showing {table.getState().pagination.pageIndex * table.getState().pagination.pageSize + 1}–{Math.min(
					(table.getState().pagination.pageIndex + 1) * table.getState().pagination.pageSize,
					rowTotal,
				)} of {rowTotal}
			</span>
			<div class="flex items-center gap-2">
				<SimpleSelect
					value={String(table.getState().pagination.pageSize)}
					onValueChange={(v) => table.setPageSize(clampPageSize(Number(v)))}
					options={[
						{ value: "20", label: "20 / page" },
						{ value: "50", label: "50 / page" },
						{ value: "100", label: "100 / page" },
					]}
					class="h-8 text-xs"
				/>
				<button
					class="inline-flex h-8 w-8 items-center justify-center rounded-md border bg-background text-muted-foreground shadow-sm transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
					onclick={() => table.previousPage()}
					disabled={!table.getCanPreviousPage()}
					aria-label="Previous page"
				>
					<ChevronLeft class="size-4" />
				</button>
				<span class="min-w-14 text-center text-xs font-semibold">
					{table.getState().pagination.pageIndex + 1} / {pageCount}
				</span>
				<button
					class="inline-flex h-8 w-8 items-center justify-center rounded-md border bg-background text-muted-foreground shadow-sm transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
					onclick={() => table.nextPage()}
					disabled={!table.getCanNextPage()}
					aria-label="Next page"
				>
					<ChevronRight class="size-4" />
				</button>
			</div>
		</div>
	{/if}
</div>
