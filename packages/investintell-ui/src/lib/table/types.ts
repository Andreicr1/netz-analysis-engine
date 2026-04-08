export interface ColumnDef<TRow> {
	id: string;
	header: string;
	width?: string;
	align?: "left" | "right" | "center";
	numeric?: boolean;
	freezable?: boolean;
	hideBelow?: number; // container query px breakpoint
	accessor: (row: TRow) => unknown;
	format?: (value: unknown, row: TRow) => string;
}
