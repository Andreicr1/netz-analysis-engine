<!--
  RebalanceFocusMode — full-screen overlay for rebalance trade proposals.

  Uses FocusMode primitive. Calls POST /rebalance/preview to get
  SuggestedTrade[], displays in 2-column layout (trades + impact),
  then executes via POST /execute-trades with optimistic lock.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { formatPercent, formatCurrency } from "@investintell/ui";
	import { createClientApiClient } from "$wealth/api/client";
	import FocusMode from "$wealth/components/terminal/focus-mode/FocusMode.svelte";
	import TradeConfirmation from "./TradeConfirmation.svelte";

	interface Props {
		portfolioId: string;
		portfolioName: string;
		holdings: Array<{
			instrument_id: string;
			fund_name: string;
			block_id: string;
			weight: number;
		}>;
		holdingsVersion: number;
		totalAum: number;
		onClose: () => void;
		onSuccess: () => void;
	}

	let {
		portfolioId,
		portfolioName,
		holdings,
		holdingsVersion,
		totalAum,
		onClose,
		onSuccess,
	}: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	// ---- State ----

	interface SuggestedTrade {
		instrument_id: string;
		fund_name: string;
		block_id: string;
		action: "BUY" | "SELL" | "HOLD";
		current_weight: number;
		target_weight: number;
		delta_weight: number;
		current_value: number;
		target_value: number;
		trade_value: number;
		estimated_quantity: number;
	}

	interface PreviewResponse {
		portfolio_id: string;
		portfolio_name: string;
		profile: string;
		total_aum: number;
		cash_available: number;
		total_trades: number;
		estimated_turnover_pct: number;
		trades: SuggestedTrade[];
		weight_comparison: Array<{ block_id: string; current_weight: number; target_weight: number; delta: number }>;
		cvar_95_projected: number | null;
		cvar_limit: number | null;
		cvar_warning: boolean;
	}

	let loading = $state(true);
	let error = $state<string | null>(null);
	let preview = $state<PreviewResponse | null>(null);
	let showConfirmation = $state(false);
	let executing = $state(false);
	let executionError = $state<string | null>(null);

	// ---- Instrument ticker map ----

	let instrumentMap = $state<Map<string, string>>(new Map());

	$effect(() => {
		let cancelled = false;
		api.get<Array<{ instrument_id: string; ticker: string | null; name: string }>>(
			"/instruments",
		)
			.then((instruments) => {
				if (cancelled) return;
				const m = new Map<string, string>();
				for (const inst of instruments) {
					if (inst.ticker) {
						m.set(inst.instrument_id, inst.ticker);
					}
				}
				instrumentMap = m;
			})
			.catch(() => {});
		return () => { cancelled = true; };
	});

	function resolveTicker(instrumentId: string): string {
		return instrumentMap.get(instrumentId) ?? instrumentId.slice(0, 8);
	}

	// ---- Fetch preview on mount ----

	$effect(() => {
		const _pid = portfolioId;
		let cancelled = false;
		loading = true;
		error = null;

		// Build current_holdings payload from actual holdings
		const currentHoldings = holdings.map((h) => ({
			instrument_id: h.instrument_id,
			quantity: h.weight * totalAum,
			current_price: 1.0,
		}));

		api.post<PreviewResponse>(
			`/model-portfolios/${_pid}/rebalance/preview`,
			{
				total_aum: totalAum > 0 ? totalAum : undefined,
				cash_available: 0,
				current_holdings: currentHoldings,
			},
		)
			.then((res) => {
				if (!cancelled) {
					preview = res;
					loading = false;
				}
			})
			.catch((err) => {
				if (!cancelled) {
					error = err instanceof Error ? err.message : "Failed to compute rebalance preview";
					loading = false;
				}
			});

		return () => { cancelled = true; };
	});

	// ---- Derived data ----

	const sortedTrades = $derived.by(() => {
		if (!preview) return [];
		return [...preview.trades].sort(
			(a, b) => Math.abs(b.delta_weight) - Math.abs(a.delta_weight),
		);
	});

	const buys = $derived(sortedTrades.filter((t) => t.action === "BUY"));
	const sells = $derived(sortedTrades.filter((t) => t.action === "SELL"));
	const holds = $derived(sortedTrades.filter((t) => t.action === "HOLD"));

	const totalBuyValue = $derived(
		sortedTrades.filter((t) => t.action === "BUY").reduce((s, t) => s + t.trade_value, 0),
	);
	const totalSellValue = $derived(
		sortedTrades.filter((t) => t.action === "SELL").reduce((s, t) => s + Math.abs(t.trade_value), 0),
	);
	const netFlow = $derived(totalBuyValue - totalSellValue);

	const turnoverClass = $derived.by(() => {
		if (!preview) return "";
		if (preview.estimated_turnover_pct > 0.20) return "rfm-val--danger";
		if (preview.estimated_turnover_pct > 0.10) return "rfm-val--warn";
		return "";
	});

	// ---- Actions ----

	function handleSubmitProposal() {
		showConfirmation = true;
	}

	async function handleExecute() {
		if (executing || !preview) return;
		executing = true;
		executionError = null;

		const tickets = preview.trades
			.filter((t) => t.action !== "HOLD")
			.map((t) => ({
				instrument_id: t.instrument_id,
				action: t.action,
				delta_weight: Math.abs(t.delta_weight),
			}));

		if (tickets.length === 0) {
			executionError = "No trades to execute (all positions are HOLD).";
			executing = false;
			return;
		}

		try {
			await api.post(`/model-portfolios/${portfolioId}/execute-trades`, {
				tickets,
				expected_version: holdingsVersion,
			});
			onSuccess();
		} catch (err: unknown) {
			if (err instanceof Error && err.name === "ConflictError") {
				executionError = "Portfolio was modified by another user. Refresh and retry.";
			} else {
				executionError = err instanceof Error ? err.message : "Trade execution failed";
			}
		} finally {
			executing = false;
		}
	}

	function handleConfirmationClose() {
		showConfirmation = false;
	}
</script>

<FocusMode
	entityKind="portfolio"
	entityId={portfolioId}
	entityLabel={portfolioName}
	onClose={onClose}
>
	{#snippet reactor()}
		<div class="rfm-content">
			{#if loading}
				<div class="rfm-loading">
					<span class="rfm-loading-text">COMPUTING REBALANCE...</span>
				</div>
			{:else if error}
				<div class="rfm-error">
					<span class="rfm-error-label">ERROR</span>
					<span class="rfm-error-msg">{error}</span>
					<button type="button" class="rfm-retry" onclick={onClose}>CLOSE</button>
				</div>
			{:else if preview}
				<div class="rfm-grid">
					<!-- Left: Proposed Trades -->
					<div class="rfm-trades-panel">
						<div class="rfm-panel-header">
							<span class="rfm-panel-title">PROPOSED TRADES</span>
						</div>
						<div class="rfm-trades-body">
							<table class="rfm-table">
								<thead>
									<tr>
										<th class="rfm-th rfm-th--name">Fund</th>
										<th class="rfm-th rfm-th--ticker">Ticker</th>
										<th class="rfm-th rfm-th--action">Action</th>
										<th class="rfm-th rfm-th--num">Current</th>
										<th class="rfm-th rfm-th--num">Target</th>
										<th class="rfm-th rfm-th--num">Weight Change</th>
										<th class="rfm-th rfm-th--num">Trade Value</th>
									</tr>
								</thead>
								<tbody>
									{#each sortedTrades as trade (trade.instrument_id)}
										<tr class="rfm-row">
											<td class="rfm-td rfm-td--name" title={trade.fund_name}>
												{trade.fund_name}
											</td>
											<td class="rfm-td rfm-td--ticker">
												{resolveTicker(trade.instrument_id)}
											</td>
											<td class="rfm-td rfm-td--action">
												<span
													class="rfm-badge"
													class:rfm-badge--buy={trade.action === "BUY"}
													class:rfm-badge--sell={trade.action === "SELL"}
													class:rfm-badge--hold={trade.action === "HOLD"}
												>
													{trade.action}
												</span>
											</td>
											<td class="rfm-td rfm-td--num">
												{formatPercent(trade.current_weight, 1)}
											</td>
											<td class="rfm-td rfm-td--num">
												{formatPercent(trade.target_weight, 1)}
											</td>
											<td
												class="rfm-td rfm-td--num"
												class:rfm-delta--pos={trade.delta_weight > 0}
												class:rfm-delta--neg={trade.delta_weight < 0}
											>
												{trade.delta_weight > 0 ? "+" : ""}{formatPercent(trade.delta_weight, 2)}
											</td>
											<td class="rfm-td rfm-td--num">
												{formatCurrency(Math.abs(trade.trade_value))}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
						<div class="rfm-trades-footer">
							{sortedTrades.length} trades ({buys.length} BUY, {sells.length} SELL, {holds.length} HOLD)
						</div>
					</div>

					<!-- Right: Impact Analysis -->
					<div class="rfm-impact-panel">
						<div class="rfm-panel-header">
							<span class="rfm-panel-title">IMPACT ANALYSIS</span>
						</div>
						<div class="rfm-impact-body">
							<div class="rfm-metric">
								<span class="rfm-metric-key">Turnover</span>
								<span class="rfm-metric-val {turnoverClass}">
									{formatPercent(preview.estimated_turnover_pct, 1)}
								</span>
							</div>
							<div class="rfm-metric">
								<span class="rfm-metric-key">Tail Loss (95% confidence)</span>
								<span class="rfm-metric-val">
									{preview.cvar_95_projected != null
										? formatPercent(preview.cvar_95_projected, 1)
										: "\u2014"}
								</span>
							</div>
							{#if preview.cvar_warning}
								<div class="rfm-warning">
									Risk limit approaching
								</div>
							{/if}
							<div class="rfm-metric">
								<span class="rfm-metric-key">Trades</span>
								<span class="rfm-metric-val">{preview.total_trades}</span>
							</div>

							<div class="rfm-divider"></div>

							<div class="rfm-section-label">TRADE VALUES</div>
							<div class="rfm-metric">
								<span class="rfm-metric-key">Total BUY</span>
								<span class="rfm-metric-val rfm-val--success">
									{formatCurrency(totalBuyValue)}
								</span>
							</div>
							<div class="rfm-metric">
								<span class="rfm-metric-key">Total SELL</span>
								<span class="rfm-metric-val rfm-val--danger">
									{formatCurrency(totalSellValue)}
								</span>
							</div>
							<div class="rfm-metric">
								<span class="rfm-metric-key">Net Flow</span>
								<span
									class="rfm-metric-val"
									class:rfm-val--success={netFlow >= 0}
									class:rfm-val--danger={netFlow < 0}
								>
									{formatCurrency(netFlow)}
								</span>
							</div>
						</div>
					</div>
				</div>

				<!-- Confirmation bar -->
				<div class="rfm-confirm-bar">
					<div class="rfm-confirm-text">
						This will generate trade orders for the active portfolio.
						Execution is simulated &mdash; no real broker orders will be placed.
					</div>

					{#if executionError}
						<div class="rfm-exec-error">{executionError}</div>
					{/if}

					<div class="rfm-confirm-actions">
						<button type="button" class="rfm-btn rfm-btn--cancel" onclick={onClose}>
							CANCEL
						</button>
						<button
							type="button"
							class="rfm-btn rfm-btn--submit"
							onclick={handleSubmitProposal}
							disabled={executing || sortedTrades.filter((t) => t.action !== "HOLD").length === 0}
						>
							SUBMIT PROPOSAL
						</button>
					</div>
				</div>
			{/if}
		</div>
	{/snippet}
</FocusMode>

{#if showConfirmation && preview}
	<TradeConfirmation
		tradeCount={sortedTrades.filter((t) => t.action !== "HOLD").length}
		buyCount={buys.length}
		sellCount={sells.length}
		turnoverPct={preview.estimated_turnover_pct}
		{executing}
		errorMessage={executionError}
		onClose={handleConfirmationClose}
		onConfirm={handleExecute}
	/>
{/if}

<style>
	.rfm-content {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		font-family: var(--terminal-font-mono);
	}

	/* Loading */
	.rfm-loading {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: 1;
	}

	.rfm-loading-text {
		font-size: var(--terminal-text-14);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-accent-amber);
		animation: rfm-pulse 1.4s ease-in-out infinite;
	}

	@keyframes rfm-pulse {
		0%, 100% { opacity: 0.4; }
		50% { opacity: 1; }
	}

	/* Error */
	.rfm-error {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--terminal-space-3);
		flex: 1;
	}

	.rfm-error-label {
		font-size: var(--terminal-text-12);
		font-weight: 700;
		color: var(--terminal-status-error);
		letter-spacing: var(--terminal-tracking-caps);
	}

	.rfm-error-msg {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-secondary);
		max-width: 500px;
		text-align: center;
	}

	.rfm-retry {
		appearance: none;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-primary);
		background: transparent;
		border: var(--terminal-border-hairline);
		padding: var(--terminal-space-1) var(--terminal-space-3);
		cursor: pointer;
	}

	/* 2-column grid */
	.rfm-grid {
		display: grid;
		grid-template-columns: 1fr 320px;
		gap: 1px;
		flex: 1;
		min-height: 0;
		background: var(--terminal-fg-muted);
	}

	/* Panel headers */
	.rfm-panel-header {
		display: flex;
		align-items: center;
		height: 32px;
		padding: 0 var(--terminal-space-3);
		border-bottom: var(--terminal-border-hairline);
		flex-shrink: 0;
	}

	.rfm-panel-title {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}

	/* Trades panel */
	.rfm-trades-panel {
		display: flex;
		flex-direction: column;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
	}

	.rfm-trades-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.rfm-trades-footer {
		flex-shrink: 0;
		padding: var(--terminal-space-2) var(--terminal-space-3);
		border-top: var(--terminal-border-hairline);
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
	}

	/* Table */
	.rfm-table {
		width: 100%;
		border-collapse: collapse;
		font-variant-numeric: tabular-nums;
	}

	.rfm-th {
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

	.rfm-th--name { text-align: left; }
	.rfm-th--ticker { text-align: left; }
	.rfm-th--action { text-align: center; }
	.rfm-th--num { text-align: right; }

	.rfm-td {
		padding: var(--terminal-space-1) var(--terminal-space-2);
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-secondary);
		border-bottom: 1px solid var(--terminal-fg-muted);
		white-space: nowrap;
	}

	.rfm-td--name {
		text-align: left;
		font-size: var(--terminal-text-11);
		font-weight: 500;
		color: var(--terminal-fg-primary);
		max-width: 220px;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.rfm-td--ticker {
		text-align: left;
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
	}

	.rfm-td--action {
		text-align: center;
	}

	.rfm-td--num {
		text-align: right;
	}

	.rfm-row {
		transition: background var(--terminal-motion-tick);
	}

	.rfm-row:hover {
		background: var(--terminal-bg-panel-raised);
	}

	/* Action badges */
	.rfm-badge {
		display: inline-block;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		padding: 1px 6px;
		text-transform: uppercase;
	}

	.rfm-badge--buy {
		color: var(--terminal-bg-void);
		background: var(--terminal-status-success);
	}

	.rfm-badge--sell {
		color: var(--terminal-bg-void);
		background: var(--terminal-status-error);
	}

	.rfm-badge--hold {
		color: var(--terminal-fg-tertiary);
		background: var(--terminal-bg-panel-raised);
	}

	/* Delta colors */
	.rfm-delta--pos {
		color: var(--terminal-status-success);
	}

	.rfm-delta--neg {
		color: var(--terminal-status-error);
	}

	/* Impact panel */
	.rfm-impact-panel {
		display: flex;
		flex-direction: column;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
	}

	.rfm-impact-body {
		flex: 1;
		padding: var(--terminal-space-3);
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-3);
		overflow-y: auto;
	}

	.rfm-metric {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.rfm-metric-key {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
	}

	.rfm-metric-val {
		font-size: var(--terminal-text-12);
		font-weight: 700;
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
	}

	.rfm-val--warn {
		color: var(--terminal-status-warn);
	}

	.rfm-val--danger {
		color: var(--terminal-status-error);
	}

	.rfm-val--success {
		color: var(--terminal-status-success);
	}

	.rfm-warning {
		padding: var(--terminal-space-1) var(--terminal-space-2);
		border-left: 2px solid var(--terminal-status-warn);
		background: var(--terminal-bg-panel-raised);
		font-size: var(--terminal-text-10);
		color: var(--terminal-status-warn);
		letter-spacing: var(--terminal-tracking-caps);
	}

	.rfm-divider {
		height: 1px;
		background: var(--terminal-fg-muted);
	}

	.rfm-section-label {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-muted);
		text-transform: uppercase;
	}

	/* Confirmation bar */
	.rfm-confirm-bar {
		flex-shrink: 0;
		padding: var(--terminal-space-3) var(--terminal-space-4);
		border-top: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
	}

	.rfm-confirm-text {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-secondary);
		margin-bottom: var(--terminal-space-3);
		line-height: 1.5;
	}

	.rfm-exec-error {
		margin-bottom: var(--terminal-space-2);
		padding: var(--terminal-space-1) var(--terminal-space-2);
		border-left: 2px solid var(--terminal-status-error);
		background: var(--terminal-bg-panel-raised);
		color: var(--terminal-status-error);
		font-size: var(--terminal-text-11);
	}

	.rfm-confirm-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--terminal-space-2);
	}

	.rfm-btn {
		appearance: none;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		padding: var(--terminal-space-1) var(--terminal-space-4);
		cursor: pointer;
		transition:
			background var(--terminal-motion-tick),
			opacity var(--terminal-motion-tick);
	}

	.rfm-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.rfm-btn--cancel {
		background: transparent;
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-secondary);
	}

	.rfm-btn--cancel:hover:not(:disabled) {
		color: var(--terminal-fg-primary);
	}

	.rfm-btn--submit {
		background: var(--terminal-accent-amber);
		border: 1px solid var(--terminal-accent-amber);
		color: var(--terminal-bg-void);
	}

	.rfm-btn--submit:hover:not(:disabled) {
		opacity: 0.9;
	}

	.rfm-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}
</style>
