<!--
  Risk Budget Table — eVestment p.43-44.
  Per-fund MCTR, PCTR, MCETL, PCETL, implied returns, and difference.
-->
<script lang="ts">
	import { formatPercent, formatNumber } from "@investintell/ui";
	import type { RiskBudgetResult } from "$lib/types/analytics";

	interface Props {
		data: RiskBudgetResult;
	}

	let { data }: Props = $props();

	function fmtBps(v: number | null): string {
		if (v == null) return "\u2014";
		return formatNumber(v * 10000, 2, "en-US");
	}

	function fmtPct(v: number | null): string {
		if (v == null) return "\u2014";
		return formatPercent(v, 1, "en-US");
	}

	function diffColor(v: number | null): string {
		if (v == null) return "var(--ii-text-muted)";
		if (v > 1e-6) return "var(--ii-success)";
		if (v < -1e-6) return "var(--ii-danger)";
		return "var(--ii-text-secondary)";
	}
</script>

<section class="rb-panel">
	<div class="rb-header">
		<h3 class="rb-title">Risk Budget Decomposition</h3>
		<div class="rb-kpis">
			<div class="rb-kpi">
				<span class="rb-kpi-label">Portfolio Vol</span>
				<span class="rb-kpi-value">{fmtBps(data.portfolio_volatility)} bps</span>
			</div>
			<div class="rb-kpi">
				<span class="rb-kpi-label">Portfolio ETL</span>
				<span class="rb-kpi-value" style:color="var(--ii-danger)">{fmtBps(data.portfolio_etl)} bps</span>
			</div>
			{#if data.portfolio_starr != null}
				<div class="rb-kpi">
					<span class="rb-kpi-label">STARR</span>
					<span class="rb-kpi-value">{formatNumber(data.portfolio_starr, 4, "en-US")}</span>
				</div>
			{/if}
		</div>
	</div>

	{#if data.funds.length === 0}
		<div class="rb-empty">No risk budget data available.</div>
	{:else}
		<div class="rb-table-wrap">
			<table class="rb-table">
				<thead>
					<tr>
						<th>Block</th>
						<th class="rb-num">Weight</th>
						<th class="rb-num">MCTR</th>
						<th class="rb-num">PCTR</th>
						<th class="rb-num">MCETL</th>
						<th class="rb-num">PCETL</th>
						<th class="rb-num">Implied (Vol)</th>
						<th class="rb-num">Diff (Vol)</th>
					</tr>
				</thead>
				<tbody>
					{#each data.funds as fund (fund.block_id)}
						<tr>
							<td class="rb-name">{fund.block_name}</td>
							<td class="rb-num">{fmtPct(fund.weight)}</td>
							<td class="rb-num">{fmtBps(fund.mctr)}</td>
							<td class="rb-num">{fmtPct(fund.pctr)}</td>
							<td class="rb-num">{fmtBps(fund.mcetl)}</td>
							<td class="rb-num">{fmtPct(fund.pcetl)}</td>
							<td class="rb-num">{fmtBps(fund.implied_return_vol)}</td>
							<td class="rb-num" style:color={diffColor(fund.difference_vol)}>
								{fmtBps(fund.difference_vol)}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</section>

<style>
	.rb-panel {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		overflow: hidden;
		margin: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px) 0;
	}

	.rb-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
		flex-wrap: wrap;
		gap: 8px;
	}

	.rb-title {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.rb-kpis {
		display: flex;
		gap: 16px;
	}

	.rb-kpi {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.rb-kpi-label {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.rb-kpi-value {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
	}

	.rb-empty {
		padding: var(--ii-space-stack-lg, 32px);
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.rb-table-wrap {
		overflow-x: auto;
	}

	.rb-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.rb-table th {
		padding: var(--ii-space-stack-2xs, 5px) var(--ii-space-inline-sm, 10px);
		text-align: left;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.02em;
		border-bottom: 1px solid var(--ii-border-subtle);
		white-space: nowrap;
	}

	.rb-table td {
		padding: var(--ii-space-stack-2xs, 5px) var(--ii-space-inline-sm, 10px);
		border-bottom: 1px solid var(--ii-border-subtle);
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-secondary);
	}

	.rb-num {
		text-align: right;
	}

	.rb-name {
		font-weight: 500;
		color: var(--ii-text-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 180px;
	}
</style>
