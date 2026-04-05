<!--
  RebalanceSimulationPanel — "Test Drive" for rebalance preview.
  Input: mock or manual current holdings (USD) + cash.
  Output: suggested trades (BUY/SELL/HOLD), turnover %, weight deltas.
  Calls POST /model-portfolios/{id}/rebalance/preview (stateless).
-->
<script lang="ts">
	import { Button } from "@investintell/ui/components/ui/button";
	import { Input } from "@investintell/ui/components/ui/input";
	import { EmptyState, formatCurrency, formatPercent } from "@investintell/ui";
	import { blockLabel } from "$lib/constants/blocks";
	import ArrowRightLeft from "lucide-svelte/icons/arrow-right-left";
	import Loader2 from "lucide-svelte/icons/loader-2";
	import Plus from "lucide-svelte/icons/plus";
	import Trash2 from "lucide-svelte/icons/trash-2";
	import Sparkles from "lucide-svelte/icons/sparkles";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import { CASH_INSTRUMENT_ID, type HoldingInput } from "$lib/types/model-portfolio";

	// ── Editable holdings state ───────────────────────────────────────
	let holdings = $state<HoldingInput[]>([]);
	let cashAvailable = $state(500_000);

	function addHolding() {
		holdings = [...holdings, { instrument_id: "", quantity: 0, current_price: 0 }];
	}

	function removeHolding(index: number) {
		holdings = holdings.filter((_, i) => i !== index);
	}

	function updateHolding(index: number, field: keyof HoldingInput, value: string | number) {
		holdings = holdings.map((h, i) =>
			i === index ? { ...h, [field]: typeof value === "string" ? value : Number(value) } : h,
		);
	}

	/**
	 * Load a dummy portfolio using actual fund IDs from the model's target.
	 * Simulates a real-world scenario: client holds ~60-80% of target funds
	 * at slightly different weights, plus cash for new purchases.
	 */
	function loadDummyPortfolio() {
		const funds = workspace.portfolio?.fund_selection_schema?.funds;
		if (!funds || funds.length === 0) return;

		// Pick a subset of target funds (simulate partial holdings)
		const subset = funds.slice(0, Math.max(3, Math.ceil(funds.length * 0.7)));
		const baseAum = 10_000_000; // $10M simulated account

		holdings = subset.map((f) => {
			// Slightly deviated weight from target (±30% drift)
			const drift = 0.7 + Math.random() * 0.6; // 0.7 to 1.3
			const holdingValue = f.weight * baseAum * drift;
			// Simulate a reasonable price per share
			const price = 20 + Math.random() * 280; // $20 to $300
			const quantity = Math.round((holdingValue / price) * 100) / 100;

			return {
				instrument_id: f.instrument_id,
				quantity,
				current_price: Math.round(price * 100) / 100,
			};
		});

		cashAvailable = 500_000; // $500k cash
	}

	function handleRun() {
		const validHoldings = holdings.filter(
			(h) => h.instrument_id && h.quantity > 0 && h.current_price > 0,
		);
		workspace.runRebalancePreview({
			cash_available: cashAvailable,
			current_holdings: validHoldings,
		});
	}

	// ── Derived ───────────────────────────────────────────────────────
	let result = $derived(workspace.rebalanceResult);
	let hasResult = $derived(result !== null);

	/** Resolve fund name from target or result */
	function fundName(instrumentId: string): string {
		const funds = workspace.portfolio?.fund_selection_schema?.funds;
		const match = funds?.find((f) => f.instrument_id === instrumentId);
		return match?.fund_name ?? `${instrumentId.slice(0, 8)}…`;
	}

	let holdingsValue = $derived(
		holdings.reduce((sum, h) => sum + h.quantity * h.current_price, 0),
	);

	let computedAum = $derived(holdingsValue + cashAvailable);
</script>

{#if !workspace.portfolio}
	<div class="p-6">
		<EmptyState
			title="No portfolio selected"
			message="Select a model portfolio to simulate rebalancing."
		/>
	</div>
{:else if !workspace.portfolio.fund_selection_schema}
	<div class="p-6">
		<EmptyState
			title="Portfolio not constructed"
			message="Run Construct first to generate target weights before simulating rebalance."
		/>
	</div>
{:else}
	<div class="rebalance-panel">
		<!-- Input section -->
		<div class="rebalance-inputs">
			<div class="input-header">
				<div class="header-left">
					<ArrowRightLeft class="h-4 w-4" style="color: var(--ii-primary);" />
					<span class="input-title">Rebalance Simulation</span>
				</div>
				<Button size="sm" variant="outline" onclick={loadDummyPortfolio}>
					<Sparkles class="mr-1.5 h-3.5 w-3.5" />
					Load Dummy Portfolio
				</Button>
			</div>

			<!-- Cash input -->
			<div class="cash-row">
				<label class="field-label" for="cash-input">Cash Available (USD)</label>
				<Input
					id="cash-input"
					type="number"
					step={10000}
					min={0}
					bind:value={cashAvailable}
					class="cash-input"
				/>
				<span class="aum-badge">
					AUM: {formatCurrency(computedAum)}
				</span>
			</div>

			<!-- Holdings table -->
			<div class="holdings-section">
				<div class="holdings-header">
					<span class="field-label">Current Holdings</span>
					<Button size="sm" variant="ghost" onclick={addHolding}>
						<Plus class="mr-1 h-3.5 w-3.5" />
						Add
					</Button>
				</div>

				{#if holdings.length === 0}
					<p class="holdings-empty">
						No holdings. Click <strong>Load Dummy Portfolio</strong> or add manually.
					</p>
				{:else}
					<div class="holdings-table">
						<div class="holdings-row holdings-head">
							<span class="col-fund">Fund</span>
							<span class="col-qty">Quantity</span>
							<span class="col-price">Price (USD)</span>
							<span class="col-value">Value</span>
							<span class="col-action"></span>
						</div>
						{#each holdings as holding, i}
							<div class="holdings-row">
								<span class="col-fund" title={holding.instrument_id}>
									{#if holding.instrument_id}
										{fundName(holding.instrument_id)}
									{:else}
										<Input
											type="text"
											placeholder="Instrument ID"
											value={holding.instrument_id}
											oninput={(e: Event) => updateHolding(i, "instrument_id", (e.target as HTMLInputElement).value)}
											class="inline-input"
										/>
									{/if}
								</span>
								<span class="col-qty">
									<Input
										type="number"
										step={1}
										min={0}
										value={holding.quantity}
										oninput={(e: Event) => updateHolding(i, "quantity", Number((e.target as HTMLInputElement).value))}
										class="inline-input"
									/>
								</span>
								<span class="col-price">
									<Input
										type="number"
										step={0.01}
										min={0}
										value={holding.current_price}
										oninput={(e: Event) => updateHolding(i, "current_price", Number((e.target as HTMLInputElement).value))}
										class="inline-input"
									/>
								</span>
								<span class="col-value tabular">
									{formatCurrency(holding.quantity * holding.current_price)}
								</span>
								<span class="col-action">
									<button class="remove-btn" onclick={() => removeHolding(i)} title="Remove">
										<Trash2 class="h-3.5 w-3.5" />
									</button>
								</span>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<Button
				size="sm"
				onclick={handleRun}
				disabled={workspace.isRebalancing || holdings.length === 0}
				class="run-btn"
			>
				{#if workspace.isRebalancing}
					<Loader2 class="mr-1.5 h-4 w-4 animate-spin" />
					Computing…
				{:else}
					<ArrowRightLeft class="mr-1.5 h-4 w-4" />
					Run Preview
				{/if}
			</Button>
		</div>

		<!-- Results section -->
		{#if hasResult && result}
			<div class="rebalance-results">
				<!-- KPI strip -->
				<div class="kpi-strip">
					<div class="kpi-item">
						<span class="kpi-label">Total AUM</span>
						<span class="kpi-value">{formatCurrency(result.total_aum)}</span>
					</div>
					<div class="kpi-item">
						<span class="kpi-label">Trades</span>
						<span class="kpi-value">{result.total_trades}</span>
					</div>
					<div class="kpi-item">
						<span class="kpi-label">Turnover</span>
						<span class="kpi-value">{formatPercent(result.estimated_turnover_pct)}</span>
					</div>
					<div class="kpi-item">
						<span class="kpi-label">Cash</span>
						<span class="kpi-value">{formatCurrency(result.cash_available)}</span>
					</div>
				</div>

				<!-- Trades table -->
				<div class="result-section">
					<span class="result-label">Suggested Trades</span>
					<div class="trades-table">
						<div class="trade-row trade-head">
							<span class="col-action-badge">Action</span>
							<span class="col-trade-fund">Fund</span>
							<span class="col-trade-block">Block</span>
							<span class="col-trade-delta">Delta (pp)</span>
							<span class="col-trade-value">Trade Value</span>
							<span class="col-trade-qty">Est. Qty</span>
						</div>
						{#each result.trades.filter((t) => t.action !== "HOLD") as trade}
							{@const isCash = trade.instrument_id === CASH_INSTRUMENT_ID}
							<div class="trade-row" class:trade-row-cash={isCash}>
								<span class="col-action-badge">
									<span
										class="action-badge"
										class:action-buy={trade.action === "BUY"}
										class:action-sell={trade.action === "SELL"}
										class:action-cash={isCash}
									>
										{isCash ? "SWEEP" : trade.action}
									</span>
								</span>
								<span class="col-trade-fund" class:cash-fund-name={isCash} title={trade.instrument_id}>
									{isCash ? "Cash Balance" : trade.fund_name}
								</span>
								<span class="col-trade-block">{isCash ? "—" : blockLabel(trade.block_id)}</span>
								<span
									class="col-trade-delta tabular"
									class:delta-positive={trade.delta_weight > 0}
									class:delta-negative={trade.delta_weight < 0}
								>
									{trade.delta_weight > 0 ? "+" : ""}{(trade.delta_weight * 100).toFixed(1)}
								</span>
								<span class="col-trade-value tabular">
									{trade.action === "SELL" ? "−" : "+"}{formatCurrency(Math.abs(trade.trade_value))}
								</span>
								<span class="col-trade-qty tabular">
									{isCash ? "—" : trade.estimated_quantity.toFixed(2)}
								</span>
							</div>
						{/each}
					</div>
				</div>

				<!-- Block weight comparison -->
				{#if result.weight_comparison.length > 0}
					<div class="result-section">
						<span class="result-label">Block Weight Comparison</span>
						<div class="weight-table">
							<div class="weight-row weight-head">
								<span class="col-wt-block">Block</span>
								<span class="col-wt-current">Current</span>
								<span class="col-wt-target">Target</span>
								<span class="col-wt-delta">Delta (pp)</span>
								<span class="col-wt-bar"></span>
							</div>
							{#each result.weight_comparison as wc}
								<div class="weight-row">
									<span class="col-wt-block">{blockLabel(wc.block_id)}</span>
									<span class="col-wt-current tabular">{formatPercent(wc.current_weight)}</span>
									<span class="col-wt-target tabular">{formatPercent(wc.target_weight)}</span>
									<span
										class="col-wt-delta tabular"
										class:delta-positive={wc.delta_pp > 0}
										class:delta-negative={wc.delta_pp < 0}
									>
										{wc.delta_pp > 0 ? "+" : ""}{wc.delta_pp.toFixed(1)}
									</span>
									<span class="col-wt-bar">
										<span
											class="bar-fill"
											class:bar-positive={wc.delta_pp > 0}
											class:bar-negative={wc.delta_pp < 0}
											style="width: {Math.min(Math.abs(wc.delta_pp) * 5, 100)}%;"
										></span>
									</span>
								</div>
							{/each}
						</div>
					</div>
				{/if}
			</div>
		{:else if !workspace.isRebalancing}
			<div class="rebalance-empty">
				<ArrowRightLeft class="h-8 w-8" style="color: var(--ii-text-muted); opacity: 0.4;" />
				<p>Add current holdings above and click <strong>Run Preview</strong> to see suggested trades.</p>
			</div>
		{/if}
	</div>
{/if}

<style>
	.rebalance-panel {
		display: flex;
		flex-direction: column;
		gap: 0;
		height: 100%;
	}

	.rebalance-inputs {
		padding: 16px;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.input-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 12px;
	}

	.header-left {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.input-title {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 700;
		color: var(--ii-text-primary);
	}

	.cash-row {
		display: flex;
		align-items: center;
		gap: 12px;
		margin-bottom: 12px;
	}

	.field-label {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		white-space: nowrap;
	}

	.aum-badge {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 700;
		color: var(--ii-text-secondary);
		background: var(--ii-surface-alt);
		padding: 4px 10px;
		border-radius: var(--ii-radius-sm, 6px);
		white-space: nowrap;
		font-variant-numeric: tabular-nums;
	}

	.holdings-section {
		margin-bottom: 12px;
	}

	.holdings-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 6px;
	}

	.holdings-empty {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
		padding: 12px 0;
	}

	.holdings-table,
	.trades-table,
	.weight-table {
		font-size: var(--ii-text-small, 0.8125rem);
		width: 100%;
	}

	.holdings-row,
	.trade-row,
	.weight-row {
		display: grid;
		align-items: center;
		gap: 8px;
		padding: 6px 0;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.holdings-row {
		grid-template-columns: 2fr 1fr 1fr 1fr 32px;
	}

	.trade-row {
		grid-template-columns: 64px 2fr 1.2fr 80px 1fr 80px;
	}

	.weight-row {
		grid-template-columns: 1.5fr 80px 80px 80px 1fr;
	}

	.holdings-head,
	.trade-head,
	.weight-head {
		font-weight: 600;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-label, 0.75rem);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		border-bottom: 2px solid var(--ii-border-subtle);
	}

	.tabular {
		font-variant-numeric: tabular-nums;
	}

	.remove-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: none;
		color: var(--ii-text-muted);
		cursor: pointer;
		padding: 4px;
		border-radius: 4px;
	}

	.remove-btn:hover {
		color: var(--ii-danger);
		background: var(--ii-surface-alt);
	}

	.rebalance-results {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding: 16px;
		flex: 1;
		overflow-y: auto;
	}

	.result-section {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.result-label {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.kpi-strip {
		display: flex;
		gap: 24px;
		padding: 12px 16px;
		background: var(--ii-surface-alt);
		border-radius: var(--ii-radius-md, 9px);
	}

	.kpi-item {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.kpi-label {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-weight: 500;
	}

	.kpi-value {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
	}

	.action-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 2px 8px;
		border-radius: 4px;
		font-size: 0.6875rem;
		font-weight: 700;
		letter-spacing: 0.05em;
		text-transform: uppercase;
	}

	.action-buy {
		background: hsl(var(--ii-success-h, 145) var(--ii-success-s, 65%) var(--ii-success-l, 42%) / 0.15);
		color: var(--ii-success);
	}

	.action-sell {
		background: hsl(var(--ii-danger-h, 0) var(--ii-danger-s, 85%) var(--ii-danger-l, 55%) / 0.15);
		color: var(--ii-danger);
	}

	.action-cash {
		background: hsl(210 15% 50% / 0.12);
		color: var(--ii-text-secondary);
	}

	.trade-row-cash {
		background: var(--ii-surface-alt);
		border-top: 2px solid var(--ii-border-subtle);
	}

	.cash-fund-name {
		font-weight: 700;
	}

	.delta-positive {
		color: var(--ii-success);
	}

	.delta-negative {
		color: var(--ii-danger);
	}

	.col-wt-bar {
		position: relative;
		height: 8px;
		background: var(--ii-surface-alt);
		border-radius: 4px;
		overflow: hidden;
	}

	.bar-fill {
		display: block;
		height: 100%;
		border-radius: 4px;
		transition: width 0.3s ease;
	}

	.bar-positive {
		background: var(--ii-success);
	}

	.bar-negative {
		background: var(--ii-danger);
	}

	.rebalance-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 12px;
		flex: 1;
		padding: 40px 24px;
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}
</style>
