<!--
  Peer Group Panel — eVestment Section IV.
  Quartile ranking table + peer comparison for strategy-matched funds.
-->
<script lang="ts">
	import { formatNumber, formatPercent } from "@investintell/ui";
	import type { PeerGroupResult } from "$lib/types/analytics";

	interface Props {
		peerGroup: PeerGroupResult;
	}

	let { peerGroup }: Props = $props();

	function fmtNum(v: number | null, decimals = 2): string {
		if (v == null) return "\u2014";
		return formatNumber(v, decimals, "en-US");
	}

	function fmtPctl(v: number): string {
		return formatNumber(v, 1, "en-US") + "%";
	}

	function quartileClass(q: number): string {
		switch (q) {
			case 1: return "pg-q pg-q1";
			case 2: return "pg-q pg-q2";
			case 3: return "pg-q pg-q3";
			default: return "pg-q pg-q4";
		}
	}

	function metricLabel(name: string): string {
		const labels: Record<string, string> = {
			sharpe_1y: "Sharpe (1Y)",
			sortino_1y: "Sortino (1Y)",
			return_1y: "Return (1Y)",
			max_drawdown_1y: "Max DD (1Y)",
			volatility_1y: "Volatility (1Y)",
			alpha_1y: "Alpha (1Y)",
			manager_score: "Manager Score",
			return_3y_ann: "Return (3Y Ann)",
			information_ratio_1y: "Info Ratio (1Y)",
		};
		return labels[name] ?? name;
	}
</script>

<section class="ea-panel">
	<h2 class="ea-panel-title">Peer Group Analysis</h2>
	<p class="ea-panel-sub">
		Strategy: {peerGroup.strategy_label} &middot; {peerGroup.peer_count} peers
		{#if peerGroup.as_of_date}
			&middot; As of {peerGroup.as_of_date}
		{/if}
	</p>

	{#if peerGroup.rankings.length === 0}
		<p class="pg-empty">No peer data available.</p>
	{:else}
		<div class="pg-table-wrap">
			<table class="pg-table">
				<thead>
					<tr>
						<th>Metric</th>
						<th>Value</th>
						<th>Percentile</th>
						<th>Quartile</th>
						<th>Peers</th>
						<th>P25</th>
						<th>Median</th>
						<th>P75</th>
					</tr>
				</thead>
				<tbody>
					{#each peerGroup.rankings as r (r.metric_name)}
						<tr>
							<td class="pg-metric">{metricLabel(r.metric_name)}</td>
							<td class="pg-val">{fmtNum(r.value, 4)}</td>
							<td class="pg-pctl">{fmtPctl(r.percentile)}</td>
							<td><span class={quartileClass(r.quartile)}>Q{r.quartile}</span></td>
							<td class="pg-peers">{r.peer_count}</td>
							<td class="pg-val">{fmtNum(r.peer_p25, 4)}</td>
							<td class="pg-val">{fmtNum(r.peer_median, 4)}</td>
							<td class="pg-val">{fmtNum(r.peer_p75, 4)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</section>

<style>
	.ea-panel {
		background: var(--ii-surface-elevated);
		border: 1px solid var(--ii-border);
		border-radius: 12px;
		padding: clamp(16px, 1rem + 0.5vw, 28px);
		margin-bottom: 16px;
	}

	.ea-panel-title {
		font-size: 0.9rem;
		font-weight: 700;
		color: var(--ii-text-primary);
		margin: 0 0 4px;
	}

	.ea-panel-sub {
		font-size: 0.75rem;
		color: var(--ii-text-muted);
		margin: 0 0 16px;
	}

	.pg-empty {
		color: var(--ii-text-muted);
		font-size: 0.85rem;
		text-align: center;
		padding: 24px;
	}

	.pg-table-wrap {
		overflow-x: auto;
	}

	.pg-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.8rem;
	}

	.pg-table th {
		font-size: 0.7rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ii-text-secondary);
		padding: 8px 10px;
		text-align: left;
		border-bottom: 1px solid var(--ii-border);
	}

	.pg-table td {
		padding: 8px 10px;
		border-bottom: 1px solid color-mix(in srgb, var(--ii-border) 50%, transparent);
	}

	.pg-metric {
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.pg-val {
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
	}

	.pg-pctl {
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
	}

	.pg-peers {
		color: var(--ii-text-muted);
		text-align: center;
	}

	.pg-q {
		font-size: 0.7rem;
		font-weight: 700;
		padding: 2px 8px;
		border-radius: 4px;
		letter-spacing: 0.03em;
	}

	.pg-q1 {
		color: var(--ii-success);
		background: color-mix(in srgb, var(--ii-success) 12%, transparent);
	}

	.pg-q2 {
		color: var(--ii-brand-primary);
		background: color-mix(in srgb, var(--ii-brand-primary) 12%, transparent);
	}

	.pg-q3 {
		color: var(--ii-warning);
		background: color-mix(in srgb, var(--ii-warning) 12%, transparent);
	}

	.pg-q4 {
		color: var(--ii-danger);
		background: color-mix(in srgb, var(--ii-danger) 12%, transparent);
	}
</style>
