/**
 * CSV export utility for DataTable.
 * Triggers a browser download of the visible table data.
 */

/**
 * Escape a CSV cell value: wraps in quotes if it contains commas, quotes, or newlines.
 */
function escapeCsvCell(value: unknown): string {
	const str = value == null ? "" : String(value);

	if (str.includes(",") || str.includes('"') || str.includes("\n") || str.includes("\r")) {
		return `"${str.replace(/"/g, '""')}"`;
	}

	return str;
}

/**
 * Export tabular data to a CSV file and trigger a browser download.
 *
 * @param data    - Array of row objects (e.g. TanStack table's filtered row originals).
 * @param columns - Ordered column definitions as `{ key: string; header: string }`.
 * @param filename - Download filename (without extension). Defaults to "export".
 *
 * @example
 * exportTableToCSV(
 *   table.getFilteredRowModel().rows.map(r => r.original),
 *   [{ key: 'name', header: 'Fund Name' }, { key: 'nav', header: 'NAV' }],
 *   'fund-table',
 * );
 */
export function exportTableToCSV(
	data: Record<string, unknown>[],
	columns: { key: string; header: string }[],
	filename = "export",
): void {
	const headerRow = columns.map((col) => escapeCsvCell(col.header)).join(",");

	const dataRows = data.map((row) =>
		columns.map((col) => escapeCsvCell(row[col.key])).join(","),
	);

	const csv = [headerRow, ...dataRows].join("\r\n");
	const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
	const url = URL.createObjectURL(blob);

	const anchor = document.createElement("a");
	anchor.href = url;
	anchor.download = `${filename}.csv`;
	anchor.style.display = "none";
	document.body.appendChild(anchor);
	anchor.click();
	document.body.removeChild(anchor);
	URL.revokeObjectURL(url);
}
