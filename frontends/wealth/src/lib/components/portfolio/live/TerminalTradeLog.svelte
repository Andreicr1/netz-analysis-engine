<!--
  TerminalTradeLog — execution history table (grid-area: tradelog).

  Split from TerminalBlotter. Shows the append-only trade ticket
  history from GET /model-portfolios/{id}/trade-tickets.

  Typography rules:
    - Instrument name: text-align left, Urbanist 11px
    - Numeric/status columns: text-align right, JetBrains Mono 10px
-->
<script lang="ts">
	import { formatNumber } from "@investintell/ui";
	export interface TradeLogEntry {
		id: string;
		instrumentId: string;
		fundName: string;
		action: "BUY" | "SELL";
		deltaWeight: number;
		executedAt: string;
		fillStatus: string;
	}

	interface Props {
		tradeLog: TradeLogEntry[];
	}

	let { tradeLog }: Props = $props();

	function fmtPct(n: number): string {
		return formatNumber(n * 100, 2) + "%";
	}

	function fmtTime(iso: string): string {
		try {
			const d = new Date(iso);
			return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
		} catch {
			return iso;
		}
	}
</script>

<div class="tl-root">
	<div class="tl-header">
		<span class="tl-title">TRADE LOG</span>
		<span class="tl-count">{tradeLog.length}</span>
	</div>

	<div class="tl-body">
		{#if tradeLog.length === 0}
			<div class="tl-empty">No trades executed</div>
		{:else}
			<table class="tl-table">
				<thead>
					<tr>
						<th class="tl-th tl-th--name" scope="col">Instrument</th>
						<th class="tl-th tl-th--right" scope="col">Side</th>
						<th class="tl-th tl-th--right" scope="col">Delta</th>
						<th class="tl-th tl-th--right" scope="col">Status</th>
						<th class="tl-th tl-th--right" scope="col">Time</th>
					</tr>
				</thead>
				<tbody>
					{#each tradeLog as t}
						<tr class="tl-row">
							<th class="tl-td tl-td--name" scope="row" title={t.fundName}>{t.fundName}</th>
							<td class="tl-td tl-td--right">
								<span
									class="tl-side"
									class:tl-side-buy={t.action === "BUY"}
									class:tl-side-sell={t.action === "SELL"}
								>{t.action}</span>
							</td>
							<td class="tl-td tl-td--right">{fmtPct(t.deltaWeight)}</td>
							<td class="tl-td tl-td--right tl-td--status">{t.fillStatus}</td>
							<td class="tl-td tl-td--right">{fmtTime(t.executedAt)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</div>
</div>

<style>
	.tl-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.tl-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
		height: 28px;
		padding: 0 10px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
	}
	.tl-title {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.12em;
		color: #5a6577;
	}
	.tl-count {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 10px;
		font-weight: 700;
		color: #5a6577;
	}

	.tl-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.tl-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		font-size: 11px;
		color: #3d4654;
	}

	.tl-table {
		width: 100%;
		border-collapse: collapse;
		font-variant-numeric: tabular-nums;
	}

	.tl-th {
		position: sticky;
		top: 0;
		z-index: 2;
		padding: 4px 8px;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: #3d4654;
		background: #0b0f1a;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
		white-space: nowrap;
	}
	.tl-th--name { text-align: left; }
	.tl-th--right { text-align: right; }

	.tl-td {
		padding: 3px 8px;
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 10px;
		color: #8896a8;
		border-bottom: 1px solid rgba(255, 255, 255, 0.03);
		white-space: nowrap;
	}
	.tl-td--name {
		text-align: left;
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		font-weight: 500;
		color: #c8d0dc;
		max-width: 180px;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.tl-td--right { text-align: right; }
	.tl-td--status {
		font-size: 9px;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}

	.tl-row {
		transition: background 60ms;
	}
	.tl-row:hover { background: rgba(255, 255, 255, 0.02); }

	.tl-side {
		font-size: 9px;
		font-weight: 800;
		letter-spacing: 0.04em;
		padding: 1px 5px;
	}
	.tl-side-buy {
		color: #22c55e;
		background: rgba(34, 197, 94, 0.10);
	}
	.tl-side-sell {
		color: #ef4444;
		background: rgba(239, 68, 68, 0.10);
	}
</style>
