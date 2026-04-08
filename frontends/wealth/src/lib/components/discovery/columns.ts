/**
 * Column definitions for Discovery tables (managers + funds).
 *
 * Uses formatters from @investintell/ui (formatAUM for compact symbol-less
 * AUM, formatNumber for counts). Never uses toFixed / toLocaleString / Intl.
 */
import type { ColumnDef } from "@investintell/ui";
import { formatAUM, formatNumber } from "@investintell/ui";

export interface ManagerRow {
	manager_id: string;
	manager_name: string;
	firm_name: string | null;
	cik: string | null;
	aum_total: number | null;
	fund_count: number;
	fund_types: string[];
	strategy_label_top: string | null;
}

export function managerColumns(compact: boolean): ColumnDef<ManagerRow>[] {
	const cols: ColumnDef<ManagerRow>[] = [
		{
			id: "name",
			header: "Manager",
			width: "minmax(220px, 2fr)",
			accessor: (r) => r.firm_name ?? r.manager_name,
		},
		{
			id: "aum",
			header: "AUM",
			numeric: true,
			width: "120px",
			accessor: (r) => r.aum_total,
			format: (v) => (v == null ? "—" : formatAUM(v as number)),
		},
	];
	if (!compact) {
		cols.push(
			{
				id: "funds",
				header: "Funds",
				numeric: true,
				width: "80px",
				accessor: (r) => r.fund_count,
				format: (v) => (v == null ? "—" : formatNumber(v as number, 0)),
			},
			{
				id: "strategy",
				header: "Top Strategy",
				width: "minmax(140px, 1fr)",
				hideBelow: 1200,
				accessor: (r) => r.strategy_label_top ?? "—",
			},
			{
				id: "crd",
				header: "CRD",
				width: "90px",
				hideBelow: 900,
				accessor: (r) => r.manager_id,
			},
		);
	}
	return cols;
}

export interface FundRowView {
	external_id: string;
	universe: string;
	name: string;
	ticker: string | null;
	aum_usd: number | null;
	fund_type: string | null;
	strategy_label: string | null;
	expense_ratio_pct: number | null;
	avg_annual_return_1y: number | null;
	avg_annual_return_10y: number | null;
	has_nav: boolean;
	has_holdings: boolean;
}
