/**
 * Enterprise Filter Bar — URL ↔ ColumnFiltersState encoder/decoder.
 *
 * Format (one `filter` query param per active column):
 *
 *   ?filter=manager_name:contains:Apollo
 *   ?filter=total_aum:gt:1000000000
 *   ?filter=total_aum:between:1000000000~50000000000
 *   ?filter=fund_types:in:mutual_fund~etf~closed_end
 *
 * Separator for multi-value operators (`in`, `between`) is `~` — picked
 * because it is URL-safe without escaping and unlikely to collide with
 * manager names or fund type slugs.
 */

import type { ColumnFiltersState } from "@investintell/ui/components/ui/data-table";
import {
	isEnumFilter,
	isNumericFilter,
	isTextFilter,
	type ColumnFilterValue,
} from "./filter-types.js";

const PARAM = "filter";
const LIST_SEP = "~";

export interface ParsedFilter {
	id: string;
	value: ColumnFilterValue;
}

export function encodeFilters(filters: ColumnFiltersState): string[] {
	const out: string[] = [];
	for (const f of filters) {
		const encoded = encodeOne(f.id, f.value as ColumnFilterValue);
		if (encoded) out.push(encoded);
	}
	return out;
}

function encodeOne(id: string, value: ColumnFilterValue): string | null {
	if (isEnumFilter(value)) {
		if (value.values.length === 0) return null;
		return `${id}:in:${value.values.map(encodeURIComponent).join(LIST_SEP)}`;
	}
	if (isNumericFilter(value)) {
		if (value.op === "between") {
			const lo = value.value ?? "";
			const hi = value.valueMax ?? "";
			if (lo === "" && hi === "") return null;
			return `${id}:between:${lo}${LIST_SEP}${hi}`;
		}
		if (value.value == null) return null;
		return `${id}:${value.op}:${value.value}`;
	}
	if (isTextFilter(value)) {
		const trimmed = value.value.trim();
		if (!trimmed) return null;
		return `${id}:${value.op}:${encodeURIComponent(trimmed)}`;
	}
	return null;
}

export function decodeFilters(params: URLSearchParams): ParsedFilter[] {
	const out: ParsedFilter[] = [];
	for (const raw of params.getAll(PARAM)) {
		const parsed = decodeOne(raw);
		if (parsed) out.push(parsed);
	}
	return out;
}

function decodeOne(raw: string): ParsedFilter | null {
	const firstColon = raw.indexOf(":");
	if (firstColon < 0) return null;
	const secondColon = raw.indexOf(":", firstColon + 1);
	if (secondColon < 0) return null;
	const id = raw.slice(0, firstColon);
	const op = raw.slice(firstColon + 1, secondColon);
	const rhs = raw.slice(secondColon + 1);
	if (!id || !op) return null;

	if (op === "in") {
		const values = rhs
			.split(LIST_SEP)
			.map((s) => decodeURIComponent(s))
			.filter(Boolean);
		if (values.length === 0) return null;
		return { id, value: { op: "in", values } };
	}
	if (op === "between") {
		const [loStr, hiStr] = rhs.split(LIST_SEP);
		const lo = loStr === "" || loStr == null ? null : Number(loStr);
		const hi = hiStr === "" || hiStr == null ? null : Number(hiStr);
		if (lo == null && hi == null) return null;
		return {
			id,
			value: {
				op: "between",
				value: Number.isFinite(lo as number) ? (lo as number) : null,
				valueMax: Number.isFinite(hi as number) ? (hi as number) : null,
			},
		};
	}
	if (op === "gt" || op === "lt") {
		const n = Number(rhs);
		if (!Number.isFinite(n)) return null;
		return { id, value: { op, value: n } };
	}
	if (op === "contains" || op === "equals") {
		return { id, value: { op, value: decodeURIComponent(rhs) } };
	}
	return null;
}

/**
 * Apply an updated filter set to an existing URLSearchParams instance:
 * drops every current `filter` entry and writes the new ones. Callers
 * should then pass the mutated params to `goto()`.
 */
export function writeFiltersToParams(
	params: URLSearchParams,
	filters: ColumnFiltersState,
): void {
	params.delete(PARAM);
	for (const encoded of encodeFilters(filters)) {
		params.append(PARAM, encoded);
	}
}
