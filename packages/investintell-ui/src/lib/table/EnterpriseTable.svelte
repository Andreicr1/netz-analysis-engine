<script lang="ts" generics="TRow">
	import type { Snippet } from "svelte";
	import type { ColumnDef } from "./types";

	let {
		rows,
		columns,
		rowKey,
		headerCell,
		cell,
		rowAttrs,
		stickyHeader = true,
		freezeFirstColumn = false,
		density = "compact",
		emptyState,
		onRowClick,
	}: {
		rows: TRow[];
		columns: ColumnDef<TRow>[];
		rowKey: (row: TRow) => string;
		headerCell?: Snippet<[ColumnDef<TRow>]>;
		cell?: Snippet<[TRow, ColumnDef<TRow>]>;
		rowAttrs?: (row: TRow) => Record<string, unknown>;
		stickyHeader?: boolean;
		freezeFirstColumn?: boolean;
		density?: "compact" | "comfortable";
		emptyState?: Snippet;
		onRowClick?: (row: TRow) => void;
	} = $props();

	function formatCell(row: TRow, col: ColumnDef<TRow>): string {
		const value = col.accessor(row);
		if (col.format) return col.format(value, row);
		return value == null ? "" : String(value);
	}
</script>

<div class="et-wrap" data-density={density}>
	{#if rows.length === 0 && emptyState}
		{@render emptyState()}
	{:else}
		<table
			class="et-table"
			class:et-sticky={stickyHeader}
			class:et-freeze={freezeFirstColumn}
		>
			<thead>
				<tr>
					{#each columns as col (col.id)}
						<th
							class:et-num={col.numeric}
							class:et-center={col.align === "center"}
							style:width={col.width}
							style:text-align={col.align}
							data-hide-below={col.hideBelow}
						>
							{#if headerCell}{@render headerCell(col)}{:else}{col.header}{/if}
						</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#each rows as row (rowKey(row))}
					{@const extra = rowAttrs?.(row) ?? {}}
					<tr
						{...extra}
						onclick={onRowClick ? () => onRowClick(row) : undefined}
						class:et-clickable={!!onRowClick}
					>
						{#each columns as col (col.id)}
							<td
								class:et-num={col.numeric}
								class:et-center={col.align === "center"}
								style:text-align={col.align}
								data-hide-below={col.hideBelow}
							>
								{#if cell}
									{@render cell(row, col)}
								{:else}
									{formatCell(row, col)}
								{/if}
							</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<style>
	.et-wrap {
		width: 100%;
		height: 100%;
		overflow: auto;
		container-type: inline-size;
	}
	.et-table {
		width: 100%;
		border-collapse: separate;
		border-spacing: 0;
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 13px;
		color: var(--ii-text-primary, #e6e8ec);
	}
	.et-table thead th {
		background: var(--ii-surface-alt, #1a1c22);
		color: var(--ii-text-muted, #85a0bd);
		font-weight: 600;
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 10px 12px;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		text-align: left;
		white-space: nowrap;
	}
	.et-sticky thead th {
		position: sticky;
		top: 0;
		z-index: 2;
	}
	.et-freeze thead th:first-child,
	.et-freeze tbody td:first-child {
		position: sticky;
		left: 0;
		background: var(--ii-surface, #141519);
		z-index: 1;
	}
	.et-freeze thead th:first-child {
		z-index: 3;
	}
	.et-table tbody tr:nth-child(even) td {
		background: var(--ii-surface-alt, rgba(255, 255, 255, 0.015));
	}
	.et-table tbody td {
		padding: 8px 12px;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.2));
		white-space: nowrap;
	}
	[data-density="comfortable"] .et-table tbody td {
		padding: 12px 14px;
	}
	[data-density="comfortable"] .et-table thead th {
		padding: 14px 14px;
	}
	.et-num {
		font-variant-numeric: tabular-nums;
		text-align: right;
	}
	.et-center {
		text-align: center;
	}
	.et-clickable {
		cursor: pointer;
	}
	.et-clickable:hover td {
		background: var(--ii-surface-highlight, rgba(80, 140, 255, 0.06));
	}

	@container (max-width: 900px) {
		[data-hide-below="900"] {
			display: none;
		}
	}
	@container (max-width: 1200px) {
		[data-hide-below="1200"] {
			display: none;
		}
	}
</style>
