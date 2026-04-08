<!--
  EnterpriseFilterBar — institutional "chip" rail above the Screener grid.

  Renders one chip per active column filter. Each chip shows:
    [<label> <operator symbol> <value>] [× remove]

  Clicking the chip body emits `onEdit(columnId)` so the parent can re-open
  the owning column's popover in the table header. Clicking the × emits
  `onRemove(columnId)`.

  Display only — owns no filter state. The parent passes the current
  ColumnFiltersState plus a columns metadata array so we can render
  operator labels and enum counts without importing column definitions.
-->
<script lang="ts">
	import { formatAUM } from "@investintell/ui";
	import { X } from "lucide-svelte";
	import type { ColumnFiltersState } from "@investintell/ui/components/ui/data-table";
	import {
		isActiveFilterValue,
		isEnumFilter,
		isNumericFilter,
		isTextFilter,
		type ColumnFilterMeta,
		type ColumnFilterValue,
	} from "./filter-types.js";

	interface Props {
		filters: ColumnFiltersState;
		columns: readonly ColumnFilterMeta[];
		onRemove: (columnId: string) => void;
		onEdit: (columnId: string) => void;
		onClearAll: () => void;
	}

	let { filters, columns, onRemove, onEdit, onClearAll }: Props = $props();

	type FilterEntry = ColumnFiltersState[number];
	interface Chip {
		id: string;
		label: string;
		summary: string;
	}

	const columnMap = $derived(
		new Map<string, ColumnFilterMeta>(
			columns.map((c: ColumnFilterMeta) => [c.id, c]),
		),
	);

	const activeChips = $derived(
		filters
			.map((f: FilterEntry): Chip | null => {
				const meta = columnMap.get(f.id);
				if (!meta) return null;
				const value = f.value as ColumnFilterValue;
				if (!isActiveFilterValue(value)) return null;
				return {
					id: f.id,
					label: meta.label,
					summary: summarize(meta, value),
				};
			})
			.filter((c: Chip | null): c is Chip => c !== null),
	);

	function summarize(
		meta: ColumnFilterMeta,
		value: ColumnFilterValue,
	): string {
		if (isTextFilter(value)) {
			const op = value.op === "contains" ? "contains" : "is";
			return `${op} "${truncate(value.value.trim(), 28)}"`;
		}
		if (isNumericFilter(value)) {
			const fmt = (n: number | null | undefined): string => {
				if (n == null) return "—";
				if (meta.unit === "currency") return formatAUM(n);
				return n.toLocaleString("en-US");
			};
			if (value.op === "between") {
				return `between ${fmt(value.value)} and ${fmt(value.valueMax ?? null)}`;
			}
			const sym = value.op === "gt" ? ">" : "<";
			return `${sym} ${fmt(value.value)}`;
		}
		if (isEnumFilter(value)) {
			if (value.values.length === 1) {
				const only = value.values[0];
				const label =
					meta.options?.find((o) => o.value === only)?.label ?? only;
				return `is ${label}`;
			}
			return `${value.values.length} selected`;
		}
		return "";
	}

	function truncate(s: string, max: number): string {
		return s.length > max ? s.slice(0, max - 1) + "…" : s;
	}
</script>

{#if activeChips.length > 0}
	<div class="efb-root" role="group" aria-label="Active filters">
		<span class="efb-leading">Filters</span>
		<ul class="efb-chips">
			{#each activeChips as chip (chip.id)}
				<li class="efb-chip-wrap">
					<button
						type="button"
						class="efb-chip"
						title="Edit filter — {chip.label}"
						onclick={() => onEdit(chip.id)}
					>
						<span class="efb-chip-label">{chip.label}</span>
						<span class="efb-chip-sep">·</span>
						<span class="efb-chip-value">{chip.summary}</span>
					</button>
					<button
						type="button"
						class="efb-chip-close"
						aria-label="Remove filter {chip.label}"
						title="Remove filter"
						onclick={() => onRemove(chip.id)}
					>
						<X size={12} strokeWidth={2.5} />
					</button>
				</li>
			{/each}
		</ul>
		<button type="button" class="efb-clear-all" onclick={onClearAll}>
			Clear all
		</button>
	</div>
{/if}

<style>
	.efb-root {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
		padding: 10px 16px;
		background: rgba(24, 24, 28, 0.65);
		border: 1px solid rgba(255, 255, 255, 0.08);
		border-radius: 10px;
		font-family: "Urbanist", system-ui, sans-serif;
		color: #e5e7eb;
	}
	.efb-leading {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: #6b7280;
		padding-right: 6px;
		border-right: 1px solid rgba(255, 255, 255, 0.08);
	}
	.efb-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		padding: 0;
		margin: 0;
		list-style: none;
		flex: 1;
		min-width: 0;
	}
	.efb-chip-wrap {
		display: inline-flex;
		align-items: stretch;
		background: rgba(59, 130, 246, 0.12);
		border: 1px solid rgba(59, 130, 246, 0.35);
		border-radius: 999px;
		overflow: hidden;
	}
	.efb-chip {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 5px 10px;
		background: transparent;
		border: none;
		font-family: inherit;
		font-size: 11px;
		color: #dbeafe;
		cursor: pointer;
		font-variant-numeric: tabular-nums;
	}
	.efb-chip:hover {
		background: rgba(59, 130, 246, 0.18);
	}
	.efb-chip-label {
		font-weight: 600;
		color: #93c5fd;
	}
	.efb-chip-sep {
		color: rgba(147, 197, 253, 0.5);
	}
	.efb-chip-value {
		color: #f3f4f6;
	}
	.efb-chip-close {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 0 8px;
		background: transparent;
		border: none;
		border-left: 1px solid rgba(59, 130, 246, 0.35);
		color: #93c5fd;
		cursor: pointer;
	}
	.efb-chip-close:hover {
		background: rgba(239, 68, 68, 0.2);
		color: #fecaca;
	}
	.efb-clear-all {
		padding: 5px 10px;
		background: transparent;
		border: 1px solid rgba(255, 255, 255, 0.16);
		border-radius: 6px;
		color: #9ca3af;
		font-family: inherit;
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		cursor: pointer;
	}
	.efb-clear-all:hover {
		color: #f3f4f6;
		border-color: rgba(255, 255, 255, 0.32);
	}
</style>
