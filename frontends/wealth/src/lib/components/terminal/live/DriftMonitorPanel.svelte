<!--
  DriftMonitorPanel -- per-fund drift table with tri-state status.

  Computes drift from actual holdings vs target weights (pure frontend
  derivation). Three states: Aligned (|drift| < 2pp), Watch (2-3pp),
  Breach (>= 3pp). Aggregate portfolio status = worst fund.

  When actual holdings come from target_fallback (no real holdings
  imported yet), shows an informational message instead of the table.
-->
<script lang="ts">
	import { formatPercent } from "@investintell/ui";

	interface DriftFund {
		instrument_id: string;
		fund_name: string;
		ticker: string;
		target_weight: number;
		actual_weight: number;
	}

	type DriftState = "aligned" | "watch" | "breach";

	interface Props {
		funds: DriftFund[];
		/** Whether holdings are from target_fallback (no real data yet). */
		isFallback: boolean;
		onRebalance?: () => void;
	}

	let { funds, isFallback, onRebalance }: Props = $props();

	function getDriftState(drift: number): DriftState {
		const abs = Math.abs(drift);
		if (abs >= 0.03) return "breach";
		if (abs >= 0.02) return "watch";
		return "aligned";
	}

	function stateLabel(s: DriftState): string {
		switch (s) {
			case "aligned": return "Aligned";
			case "watch": return "Watch";
			case "breach": return "Breach";
		}
	}

	const driftRows = $derived(
		funds.map((f) => {
			const drift = f.actual_weight - f.target_weight;
			const state = getDriftState(drift);
			return { ...f, drift, state };
		}),
	);

	const watchCount = $derived(driftRows.filter((r) => r.state === "watch").length);
	const breachCount = $derived(driftRows.filter((r) => r.state === "breach").length);

	const aggregateState = $derived.by((): DriftState => {
		if (breachCount > 0) return "breach";
		if (watchCount > 0) return "watch";
		return "aligned";
	});

	const aggregateLabel = $derived.by(() => {
		const parts: string[] = [];
		if (watchCount > 0) parts.push(`${watchCount} Watch`);
		if (breachCount > 0) parts.push(`${breachCount} Breach`);
		if (parts.length === 0) return "All Aligned";
		return parts.join(", ");
	});

	function handleRebalance() {
		onRebalance?.();
	}
</script>

<div class="dm-root">
	<div class="dm-header">
		<span class="dm-title">DRIFT MONITOR</span>
	</div>

	{#if isFallback}
		<div class="dm-fallback">
			<span class="dm-fallback-text">
				All weights aligned to target — no actual holdings imported yet
			</span>
		</div>
	{:else if funds.length === 0}
		<div class="dm-fallback">
			<span class="dm-fallback-text">No holdings</span>
		</div>
	{:else}
		<div class="dm-body">
			<table class="dm-table">
				<thead>
					<tr>
						<th class="dm-th dm-th--name" scope="col">Fund</th>
						<th class="dm-th dm-th--num" scope="col">Target</th>
						<th class="dm-th dm-th--num" scope="col">Actual</th>
						<th class="dm-th dm-th--num" scope="col">Drift</th>
						<th class="dm-th dm-th--status" scope="col">Status</th>
					</tr>
				</thead>
				<tbody>
					{#each driftRows as row (row.instrument_id)}
						<tr class="dm-row">
							<td class="dm-td dm-td--name" title={row.fund_name}>
								{row.ticker}
							</td>
							<td class="dm-td dm-td--num">
								{formatPercent(row.target_weight, 1)}
							</td>
							<td class="dm-td dm-td--num">
								{formatPercent(row.actual_weight, 1)}
							</td>
							<td
								class="dm-td dm-td--num"
								class:dm-drift-aligned={row.state === "aligned"}
								class:dm-drift-watch={row.state === "watch"}
								class:dm-drift-breach={row.state === "breach"}
							>
								{row.drift >= 0 ? "+" : ""}{formatPercent(row.drift, 1)}
							</td>
							<td class="dm-td dm-td--status">
								<span
									class="dm-dot"
									class:dm-dot--aligned={row.state === "aligned"}
									class:dm-dot--watch={row.state === "watch"}
									class:dm-dot--breach={row.state === "breach"}
								></span>
								<span
									class="dm-state-label"
									class:dm-drift-aligned={row.state === "aligned"}
									class:dm-drift-watch={row.state === "watch"}
									class:dm-drift-breach={row.state === "breach"}
								>
									{stateLabel(row.state)}
								</span>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<div class="dm-footer">
			<div class="dm-aggregate">
				<span class="dm-agg-label">PORTFOLIO:</span>
				<span
					class="dm-agg-status"
					class:dm-drift-aligned={aggregateState === "aligned"}
					class:dm-drift-watch={aggregateState === "watch"}
					class:dm-drift-breach={aggregateState === "breach"}
				>
					{stateLabel(aggregateState).toUpperCase()}
				</span>
				<span class="dm-agg-detail">({aggregateLabel})</span>
			</div>
			{#if aggregateState !== "aligned"}
				<button type="button" class="dm-rebalance-btn" onclick={handleRebalance}>
					REBALANCE
				</button>
			{/if}
		</div>
	{/if}
</div>

<style>
	.dm-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}

	.dm-header {
		display: flex;
		align-items: center;
		flex-shrink: 0;
		height: 28px;
		padding: 0 var(--terminal-space-2);
		border-bottom: var(--terminal-border-hairline);
	}

	.dm-title {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}

	.dm-fallback {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--terminal-space-3);
	}

	.dm-fallback-text {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
		text-align: center;
	}

	.dm-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.dm-table {
		width: 100%;
		border-collapse: collapse;
		font-variant-numeric: tabular-nums;
	}

	.dm-th {
		position: sticky;
		top: 0;
		z-index: 2;
		padding: var(--terminal-space-1) var(--terminal-space-2);
		font-size: 9px;
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-muted);
		background: var(--terminal-bg-panel);
		border-bottom: var(--terminal-border-hairline);
		white-space: nowrap;
	}

	.dm-th--name { text-align: left; }
	.dm-th--num { text-align: right; }
	.dm-th--status { text-align: left; padding-left: var(--terminal-space-3); }

	.dm-td {
		padding: var(--terminal-space-1) var(--terminal-space-2);
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-secondary);
		border-bottom: var(--terminal-border-hairline);
		white-space: nowrap;
	}

	.dm-td--name {
		text-align: left;
		font-weight: 600;
		color: var(--terminal-fg-primary);
		max-width: 80px;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.dm-td--num { text-align: right; }

	.dm-td--status {
		text-align: left;
		padding-left: var(--terminal-space-3);
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.dm-row {
		transition: background var(--terminal-motion-tick);
	}

	.dm-row:hover {
		background: var(--terminal-bg-panel-raised);
	}

	/* Drift state dots */
	.dm-dot {
		display: inline-block;
		width: 6px;
		height: 6px;
		flex-shrink: 0;
	}

	.dm-dot--aligned {
		background: var(--terminal-status-success);
		border-radius: 50%;
	}

	.dm-dot--watch {
		background: var(--terminal-status-warn);
		border-radius: 50%;
		/* Half-circle effect via clip-path */
		clip-path: inset(0 50% 0 0);
		box-shadow: inset 0 0 0 1px var(--terminal-status-warn);
		width: 6px;
	}

	.dm-dot--breach {
		background: transparent;
		border: 1px solid var(--terminal-status-error);
		border-radius: 50%;
	}

	.dm-state-label {
		font-size: var(--terminal-text-10);
		font-weight: 600;
	}

	/* Drift colors */
	.dm-drift-aligned { color: var(--terminal-status-success); }
	.dm-drift-watch { color: var(--terminal-status-warn); }
	.dm-drift-breach { color: var(--terminal-status-error); }

	/* Footer */
	.dm-footer {
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--terminal-space-1) var(--terminal-space-2);
		border-top: var(--terminal-border-hairline);
		gap: var(--terminal-space-2);
	}

	.dm-aggregate {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-1);
	}

	.dm-agg-label {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
	}

	.dm-agg-status {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.dm-agg-detail {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
	}

	.dm-rebalance-btn {
		appearance: none;
		height: 22px;
		padding: 0 var(--terminal-space-2);
		font-family: var(--terminal-font-mono);
		font-size: 9px;
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-accent-amber);
		background: transparent;
		border: 1px solid var(--terminal-accent-amber-dim);
		cursor: pointer;
		transition: background var(--terminal-motion-tick), border-color var(--terminal-motion-tick);
	}

	.dm-rebalance-btn:hover {
		background: var(--terminal-bg-panel-raised);
		border-color: var(--terminal-accent-amber);
	}

	.dm-rebalance-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}
</style>
