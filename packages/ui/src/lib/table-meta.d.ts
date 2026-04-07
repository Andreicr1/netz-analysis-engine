import "@tanstack/svelte-table";

declare module "@tanstack/svelte-table" {
	interface ColumnMeta<TData, TValue> {
		/** Right-align cell + tabular-nums + font-semibold */
		numeric?: boolean;
		/** Muted text color + font-medium */
		muted?: boolean;
		/** Center-align cell */
		centered?: boolean;
	}
}
