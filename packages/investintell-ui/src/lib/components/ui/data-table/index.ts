export { default as FlexRender } from "./flex-render.svelte";
export { renderComponent, renderSnippet } from "./render-helpers.js";
export { createSvelteTable } from "./data-table.svelte.js";

// Re-export the row-model builders and core types from @tanstack/table-core
// so consumers can wire a table without adding table-core as a direct dep.
// Keeping this surface narrow on purpose: add more helpers only when a
// consumer demonstrably needs them (YAGNI).
export {
	getCoreRowModel,
	getFilteredRowModel,
	getSortedRowModel,
	type ColumnDef,
	type ColumnFilter,
	type ColumnFiltersState,
	type Row,
	type Table,
} from "@tanstack/table-core";
