<!--
  DiscoveryFundsTable — renders funds for the selected manager with inline
  action buttons (DD / FS / Analysis →) in the last column.

  Actions column uses a custom cell snippet to render the three buttons.
  Clicking DD or FS opens Col3 with the respective view; Analysis → navigates
  to the standalone full-width Analysis page.
-->
<script lang="ts">
	import { EnterpriseTable, formatAUM, formatPercent } from "@investintell/ui";
	import type { ColumnDef } from "@investintell/ui";
	import type { FundRowView } from "./columns";

	interface Props {
		rows: FundRowView[];
		selectedFundId: string | null;
		activeView: "dd" | "factsheet" | null;
		onSelectCol3: (id: string, view: "dd" | "factsheet") => void;
		onOpenAnalysis: (id: string) => void;
	}

	let {
		rows,
		selectedFundId,
		activeView,
		onSelectCol3,
		onOpenAnalysis,
	}: Props = $props();

	const columns: ColumnDef<FundRowView>[] = [
		{
			id: "ticker",
			header: "Ticker",
			width: "90px",
			accessor: (r) => r.ticker ?? "—",
		},
		{
			id: "name",
			header: "Name",
			width: "minmax(220px, 2fr)",
			accessor: (r) => r.name,
		},
		{
			id: "type",
			header: "Type",
			width: "110px",
			hideBelow: 1200,
			accessor: (r) => r.fund_type ?? "—",
		},
		{
			id: "strategy",
			header: "Strategy",
			width: "minmax(140px, 1fr)",
			hideBelow: 1400,
			accessor: (r) => r.strategy_label ?? "—",
		},
		{
			id: "aum",
			header: "AUM",
			numeric: true,
			width: "110px",
			accessor: (r) => r.aum_usd,
			format: (v) => (v == null ? "—" : formatAUM(v as number)),
		},
		{
			id: "er",
			header: "ER",
			numeric: true,
			width: "70px",
			hideBelow: 1200,
			accessor: (r) => r.expense_ratio_pct,
			format: (v) => (v == null ? "—" : formatPercent((v as number) / 100, 2)),
		},
		{
			id: "ret1y",
			header: "1Y",
			numeric: true,
			width: "80px",
			accessor: (r) => r.avg_annual_return_1y,
			format: (v) => (v == null ? "—" : formatPercent((v as number) / 100, 1)),
		},
		{
			id: "ret10y",
			header: "10Y",
			numeric: true,
			width: "80px",
			hideBelow: 1400,
			accessor: (r) => r.avg_annual_return_10y,
			format: (v) => (v == null ? "—" : formatPercent((v as number) / 100, 1)),
		},
		{
			id: "actions",
			header: "",
			width: "140px",
			align: "right",
			accessor: (r) => r.external_id,
		},
	];
</script>

{#snippet cellSnippet(row: FundRowView, col: ColumnDef<FundRowView>)}
	{#if col.id === "actions"}
		<div class="action-row">
			<button
				type="button"
				class="act-btn"
				class:active={row.external_id === selectedFundId && activeView === "dd"}
				onclick={(e) => {
					e.stopPropagation();
					onSelectCol3(row.external_id, "dd");
				}}
				title="DD Review (opens in col3)"
			>
				DD
			</button>
			<button
				type="button"
				class="act-btn"
				class:active={row.external_id === selectedFundId && activeView === "factsheet"}
				onclick={(e) => {
					e.stopPropagation();
					onSelectCol3(row.external_id, "factsheet");
				}}
				title="Fact Sheet (opens in col3)"
			>
				FS
			</button>
			<button
				type="button"
				class="act-btn act-btn--primary"
				onclick={(e) => {
					e.stopPropagation();
					onOpenAnalysis(row.external_id);
				}}
				title="Open full-width Analysis page"
			>
				Analysis →
			</button>
		</div>
	{:else if col.format}
		{col.format(col.accessor(row), row)}
	{:else}
		{col.accessor(row) ?? ""}
	{/if}
{/snippet}

<EnterpriseTable
	{rows}
	{columns}
	rowKey={(r) => r.external_id}
	cell={cellSnippet}
	rowAttrs={(r) => ({
		"data-selected": r.external_id === selectedFundId ? "true" : undefined,
	})}
/>

<style>
	.action-row {
		display: inline-flex;
		gap: 4px;
		justify-content: flex-end;
	}
	.act-btn {
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		font-weight: 600;
		padding: 4px 8px;
		border-radius: 4px;
		background: transparent;
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		color: var(--ii-text-muted, #85a0bd);
		cursor: pointer;
		transition: all 150ms;
	}
	.act-btn:hover {
		border-color: var(--ii-brand-accent, #0066ff);
		color: var(--ii-brand-accent, #0066ff);
	}
	.act-btn.active {
		background: var(--ii-brand-accent, #0066ff);
		color: white;
		border-color: var(--ii-brand-accent, #0066ff);
	}
	.act-btn--primary {
		background: var(--ii-border-accent, rgba(0, 102, 255, 0.08));
		color: var(--ii-brand-accent, #0066ff);
		border-color: var(--ii-brand-accent, #0066ff);
	}
	.act-btn--primary:hover {
		background: var(--ii-brand-accent, #0066ff);
		color: white;
	}
</style>
