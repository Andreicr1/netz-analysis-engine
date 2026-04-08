/**
 * Enterprise Filter Bar — shared types and filter kernels.
 *
 * Used by ColumnFilterPopover, EnterpriseFilterBar, CatalogTableV2 and the
 * Screener page's URL-sync effect. Kept framework-free so it can be unit
 * tested without a Svelte runtime.
 *
 * Filter values are stashed inside the TanStack `ColumnFiltersState` as the
 * `value` field of each entry. Our custom `filterFn` implementations below
 * read those values and decide whether a row passes.
 */

import type { Row } from "@investintell/ui/components/ui/data-table";

// ─────────────────────────────────────────────────────────────
// Column metadata
// ─────────────────────────────────────────────────────────────

export type ColumnFilterType = "text" | "numeric" | "enum";

export interface EnumOption {
	value: string;
	label: string;
}

export interface ColumnFilterMeta {
	/** Must match the TanStack column id exactly. */
	id: string;
	/** Display label shown in chip and popover header. */
	label: string;
	type: ColumnFilterType;
	/** For numeric columns — controls chip formatting only. */
	unit?: "currency" | "count" | "percent" | "plain";
	/** For enum columns — the full set of selectable options. */
	options?: readonly EnumOption[];
	/**
	 * When true, the accessor produces an array cell (e.g. `fund_types:
	 * string[]`). The enum filter then matches a row when ANY item in the
	 * cell array is present in the filter's selected values.
	 */
	arrayCell?: boolean;
}

// ─────────────────────────────────────────────────────────────
// Filter value shapes (what gets stored as `ColumnFilter.value`)
// ─────────────────────────────────────────────────────────────

export type TextOperator = "contains" | "equals";
export type NumericOperator = "gt" | "lt" | "between";
export type EnumOperator = "in";

export interface TextFilterValue {
	op: TextOperator;
	value: string;
}

export interface NumericFilterValue {
	op: NumericOperator;
	value: number | null;
	valueMax?: number | null;
}

export interface EnumFilterValue {
	op: EnumOperator;
	values: string[];
}

export type ColumnFilterValue =
	| TextFilterValue
	| NumericFilterValue
	| EnumFilterValue;

// ─────────────────────────────────────────────────────────────
// Operator option catalogues (rendered by the popover dropdown)
// ─────────────────────────────────────────────────────────────

export const TEXT_OPERATORS: readonly { value: TextOperator; label: string }[] = [
	{ value: "contains", label: "Contains" },
	{ value: "equals", label: "Equals" },
];

export const NUMERIC_OPERATORS: readonly {
	value: NumericOperator;
	label: string;
}[] = [
	{ value: "gt", label: "Greater than" },
	{ value: "lt", label: "Less than" },
	{ value: "between", label: "Between" },
];

export function defaultValueFor(type: ColumnFilterType): ColumnFilterValue {
	if (type === "numeric") return { op: "gt", value: null };
	if (type === "enum") return { op: "in", values: [] };
	return { op: "contains", value: "" };
}

// ─────────────────────────────────────────────────────────────
// Filter kernels (custom TanStack `filterFn`s)
// ─────────────────────────────────────────────────────────────
//
// TanStack expects `(row, columnId, filterValue) => boolean`. We rely on
// the column's `meta.type` to know which kernel to run — every column we
// register uses one of these three.

type FilterFn<TData> = (
	row: Row<TData>,
	columnId: string,
	filterValue: unknown,
) => boolean;

export function isTextFilter(v: unknown): v is TextFilterValue {
	return (
		typeof v === "object" &&
		v !== null &&
		"op" in v &&
		(v.op === "contains" || v.op === "equals") &&
		"value" in v &&
		typeof (v as TextFilterValue).value === "string"
	);
}

export function isNumericFilter(v: unknown): v is NumericFilterValue {
	if (typeof v !== "object" || v === null || !("op" in v)) return false;
	const op = (v as { op: unknown }).op;
	return op === "gt" || op === "lt" || op === "between";
}

export function isEnumFilter(v: unknown): v is EnumFilterValue {
	return (
		typeof v === "object" &&
		v !== null &&
		"op" in v &&
		(v as { op: unknown }).op === "in" &&
		"values" in v &&
		Array.isArray((v as EnumFilterValue).values)
	);
}

export function makeTextFilterFn<TData>(): FilterFn<TData> {
	return (row, columnId, filterValue) => {
		if (!isTextFilter(filterValue)) return true;
		const needle = filterValue.value.trim().toLowerCase();
		if (!needle) return true;
		const raw = row.getValue(columnId);
		const hay = String(raw ?? "").toLowerCase();
		return filterValue.op === "contains"
			? hay.includes(needle)
			: hay === needle;
	};
}

export function makeNumericFilterFn<TData>(): FilterFn<TData> {
	return (row, columnId, filterValue) => {
		if (!isNumericFilter(filterValue)) return true;
		const raw = row.getValue(columnId);
		if (raw == null) return false;
		const cell = Number(raw);
		if (!Number.isFinite(cell)) return false;
		const v = filterValue.value;
		if (v == null) return true;
		if (filterValue.op === "gt") return cell > v;
		if (filterValue.op === "lt") return cell < v;
		// between
		const lo = v;
		const hi = filterValue.valueMax ?? Number.POSITIVE_INFINITY;
		return cell >= lo && cell <= hi;
	};
}

export function makeEnumFilterFn<TData>(opts: {
	arrayCell?: boolean;
} = {}): FilterFn<TData> {
	return (row, columnId, filterValue) => {
		if (!isEnumFilter(filterValue)) return true;
		if (filterValue.values.length === 0) return true;
		const raw = row.getValue(columnId);
		if (opts.arrayCell && Array.isArray(raw)) {
			return (raw as unknown[]).some((v) =>
				filterValue.values.includes(String(v)),
			);
		}
		return filterValue.values.includes(String(raw ?? ""));
	};
}

// ─────────────────────────────────────────────────────────────
// Predicate: is a filter value "active"? (used to hide empty chips)
// ─────────────────────────────────────────────────────────────

export function isActiveFilterValue(v: ColumnFilterValue | null | undefined): boolean {
	if (!v) return false;
	if (isTextFilter(v)) return v.value.trim().length > 0;
	if (isNumericFilter(v)) {
		if (v.op === "between") {
			return v.value != null || v.valueMax != null;
		}
		return v.value != null;
	}
	if (isEnumFilter(v)) return v.values.length > 0;
	return false;
}
