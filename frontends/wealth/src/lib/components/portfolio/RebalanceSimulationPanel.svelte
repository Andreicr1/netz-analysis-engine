<!--
  RebalanceSimulationPanel — "Test Drive" for rebalance preview.
  Input: manual current holdings (USD) + cash.
  Output: suggested trades (BUY/SELL/HOLD), turnover %, weight deltas.
  Calls POST /model-portfolios/{id}/rebalance/preview (stateless).
  Design: dark premium (Figma One X).
-->
<script lang="ts">
	import { Button } from "@investintell/ui/components/ui/button";
	import { Input } from "@investintell/ui/components/ui/input";
	import { EmptyState, formatCurrency, formatPercent, formatNumber } from "@investintell/ui";
	import { blockLabel } from "$lib/constants/blocks";
	import Loader2 from "lucide-svelte/icons/loader-2";
	import Trash2 from "lucide-svelte/icons/trash-2";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import { CASH_INSTRUMENT_ID, type HoldingInput } from "$lib/types/model-portfolio";

	// ── Editable holdings state ───────────────────────────────────────
	let holdings = $state<HoldingInput[]>([]);
	let cashAvailable = $state(500_000);
	let executionSuccess = $state(false);

	async function handleExecute() {
		const validHoldings = holdings.filter(
			(h) => h.instrument_id && h.quantity > 0 && h.current_price > 0,
		);
		
		try {
			await workspace.executeTrades({
				cash_available: cashAvailable,
				current_holdings: validHoldings,
			});
			executionSuccess = true;
			setTimeout(() => {
				executionSuccess = false;
			}, 3000);
		} catch (err) {
			console.error("Failed to execute trades:", err);
		}
	}

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

	function loadDummyPortfolio() {
		const funds = workspace.portfolio?.fund_selection_schema?.funds;
		if (!funds || funds.length === 0) return;

		const subset = funds.slice(0, Math.max(3, Math.ceil(funds.length * 0.7)));
		const baseAum = 10_000_000;

		holdings = subset.map((f) => {
			const drift = 0.7 + Math.random() * 0.6;
			const holdingValue = f.weight * baseAum * drift;
			const price = 20 + Math.random() * 280;
			const quantity = Math.round((holdingValue / price) * 100) / 100;

			return {
				instrument_id: f.instrument_id,
				quantity,
				current_price: Math.round(price * 100) / 100,
			};
		});

		cashAvailable = 500_000;
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
	<div class="flex flex-col h-full">
		<!-- Input section -->
		<div class="px-5 py-4" style="border-bottom: 1px solid #404249;">
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-2">
					<span class="text-[15px] font-bold text-white">Rebalance Simulation</span>
				</div>
				<Button size="sm" variant="outline" onclick={loadDummyPortfolio}>
					Load Dummy Portfolio
				</Button>
			</div>

			<!-- Cash input -->
			<div class="flex items-center gap-3 mb-4">
				<label class="text-[11px] font-semibold text-[#85a0bd] uppercase tracking-wide whitespace-nowrap" for="cash-input">Cash Available (USD)</label>
				<Input id="cash-input" type="number" step={10000} min={0} bind:value={cashAvailable} />
				<span class="text-[12px] font-bold text-[#cbccd1] bg-white/5 px-3 py-1.5 rounded-full whitespace-nowrap tabular-nums">
					AUM: {formatCurrency(computedAum)}
				</span>
			</div>

			<!-- Holdings table -->
			<div class="mb-4">
				<div class="flex items-center justify-between mb-2">
					<span class="text-[11px] font-semibold text-[#85a0bd] uppercase tracking-wide">Current Holdings</span>
					<Button size="sm" variant="ghost" onclick={addHolding}>
						+ Add
					</Button>
				</div>

				{#if holdings.length === 0}
					<p class="text-[13px] text-[#85a0bd] py-3">
						No holdings. Click <strong class="text-[#cbccd1]">Load Dummy Portfolio</strong> or add manually.
					</p>
				{:else}
					<div class="text-[13px]">
						<!-- Head -->
						<div class="grid grid-cols-[2fr_1fr_1fr_1fr_32px] gap-2 py-2 text-[11px] font-semibold text-[#85a0bd] uppercase tracking-wide" style="border-bottom: 2px solid #404249;">
							<span>Fund</span>
							<span>Quantity</span>
							<span>Price (USD)</span>
							<span>Value</span>
							<span></span>
						</div>
						{#each holdings as holding, i}
							<div class="grid grid-cols-[2fr_1fr_1fr_1fr_32px] gap-2 items-center py-2" style="border-bottom: 1px solid rgba(64, 66, 73, 0.4);">
								<span class="text-white truncate" title={holding.instrument_id}>
									{#if holding.instrument_id}
										{fundName(holding.instrument_id)}
									{:else}
										<Input type="text" placeholder="Instrument ID" value={holding.instrument_id} oninput={(e) => updateHolding(i, "instrument_id", (e.target as HTMLInputElement).value)} />
									{/if}
								</span>
								<span>
									<Input type="number" step={1} min={0} value={holding.quantity} oninput={(e) => updateHolding(i, "quantity", Number((e.target as HTMLInputElement).value))} />
								</span>
								<span>
									<Input type="number" step={0.01} min={0} value={holding.current_price} oninput={(e) => updateHolding(i, "current_price", Number((e.target as HTMLInputElement).value))} />
								</span>
								<span class="text-white tabular-nums">{formatCurrency(holding.quantity * holding.current_price)}</span>
								<button class="flex items-center justify-center p-1 rounded text-[#85a0bd] hover:text-[#fc1a1a] hover:bg-white/5 transition-colors" onclick={() => removeHolding(i)} title="Remove">
									<Trash2 class="h-3.5 w-3.5" />
								</button>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<Button size="sm" onclick={handleRun} disabled={workspace.isRebalancing || computedAum <= 0}>
				{#if workspace.isRebalancing}
					<Loader2 class="mr-1.5 h-4 w-4 animate-spin" />
					Computing…
				{:else}
						Run Preview
				{/if}
			</Button>
		</div>

		<!-- Results section -->
		{#if hasResult && result}
			<div class="flex flex-col gap-5 p-5 flex-1 overflow-y-auto">
				<!-- KPI strip -->
				<div class="flex gap-6 px-5 py-3 bg-white/[0.03] rounded-[12px]">
					<div class="flex flex-col gap-0.5">
						<span class="text-[11px] text-[#85a0bd] font-medium">Total AUM</span>
						<span class="text-[15px] font-bold text-white tabular-nums">{formatCurrency(result.total_aum)}</span>
					</div>
					<div class="flex flex-col gap-0.5">
						<span class="text-[11px] text-[#85a0bd] font-medium">Trades</span>
						<span class="text-[15px] font-bold text-white tabular-nums">{result.total_trades}</span>
					</div>
					<div class="flex flex-col gap-0.5">
						<span class="text-[11px] text-[#85a0bd] font-medium">Turnover</span>
						<span class="text-[15px] font-bold text-white tabular-nums">{formatPercent(result.estimated_turnover_pct)}</span>
					</div>
					<div class="flex flex-col gap-0.5">
						<span class="text-[11px] text-[#85a0bd] font-medium">Cash</span>
						<span class="text-[15px] font-bold text-white tabular-nums">{formatCurrency(result.cash_available)}</span>
					</div>
				</div>

				<!-- Trades table -->
				<div class="flex flex-col gap-2">
					<span class="text-[11px] font-semibold text-[#85a0bd] uppercase tracking-[0.04em]">Suggested Trades</span>
					<div class="text-[13px]">
						<div class="grid grid-cols-[64px_2fr_1.2fr_80px_1fr_80px] gap-2 py-2 text-[11px] font-semibold text-[#85a0bd] uppercase tracking-wide" style="border-bottom: 2px solid #404249;">
							<span>Action</span>
							<span>Fund</span>
							<span>Block</span>
							<span>Delta (pp)</span>
							<span>Trade Value</span>
							<span>Est. Qty</span>
						</div>
						{#each result.trades.filter((t) => t.action !== "HOLD") as trade}
							{@const isCash = trade.instrument_id === CASH_INSTRUMENT_ID}
							<div
								class="grid grid-cols-[64px_2fr_1.2fr_80px_1fr_80px] gap-2 items-center py-2.5
									{isCash ? 'bg-white/[0.02]' : ''}"
								style="border-bottom: 1px solid rgba(64, 66, 73, 0.4);{isCash ? 'border-top: 2px solid #404249;' : ''}"
							>
								<span>
									<span
										class="inline-flex items-center justify-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide
											{trade.action === 'BUY'
												? 'bg-[#11ec79]/15 text-[#11ec79]'
												: trade.action === 'SELL'
													? 'bg-[#fc1a1a]/15 text-[#fc1a1a]'
													: 'bg-white/5 text-[#85a0bd]'}"
									>
										{isCash ? "SWEEP" : trade.action}
									</span>
								</span>
								<span class="text-white truncate {isCash ? 'font-bold' : ''}" title={trade.instrument_id}>
									{isCash ? "Cash Balance" : trade.fund_name}
								</span>
								<span class="text-[#85a0bd]">{isCash ? "—" : blockLabel(trade.block_id)}</span>
								<span class="tabular-nums {trade.delta_weight > 0 ? 'text-[#11ec79]' : 'text-[#fc1a1a]'}">
									{trade.delta_weight > 0 ? "+" : ""}{formatPercent(trade.delta_weight, 1)}
								</span>
								<span class="text-white tabular-nums">
									{trade.action === "SELL" ? "−" : "+"}{formatCurrency(Math.abs(trade.trade_value))}
								</span>
								<span class="text-[#cbccd1] tabular-nums">
									{isCash ? "—" : formatNumber(trade.estimated_quantity, 2)}
								</span>
							</div>
						{/each}
					</div>
				</div>

				<!-- Block weight comparison -->
				{#if result.weight_comparison.length > 0}
					<div class="flex flex-col gap-2">
						<span class="text-[11px] font-semibold text-[#85a0bd] uppercase tracking-[0.04em]">Block Weight Comparison</span>
						<div class="text-[13px]">
							<div class="grid grid-cols-[1.5fr_80px_80px_80px_1fr] gap-2 py-2 text-[11px] font-semibold text-[#85a0bd] uppercase tracking-wide" style="border-bottom: 2px solid #404249;">
								<span>Block</span>
								<span>Current</span>
								<span>Target</span>
								<span>Delta (pp)</span>
								<span></span>
							</div>
							{#each result.weight_comparison as wc}
								<div class="grid grid-cols-[1.5fr_80px_80px_80px_1fr] gap-2 items-center py-2.5" style="border-bottom: 1px solid rgba(64, 66, 73, 0.4);">
									<span class="text-white">{blockLabel(wc.block_id)}</span>
									<span class="text-[#cbccd1] tabular-nums">{formatPercent(wc.current_weight)}</span>
									<span class="text-[#cbccd1] tabular-nums">{formatPercent(wc.target_weight)}</span>
									<span class="tabular-nums {wc.delta_pp > 0 ? 'text-[#11ec79]' : 'text-[#fc1a1a]'}">
										{wc.delta_pp > 0 ? "+" : ""}{formatNumber(wc.delta_pp, 1)}
									</span>
									<span class="relative h-2 bg-white/5 rounded overflow-hidden">
										<span
											class="block h-full rounded transition-[width] duration-300
												{wc.delta_pp > 0 ? 'bg-[#11ec79]' : 'bg-[#fc1a1a]'}"
											style="width: {Math.min(Math.abs(wc.delta_pp) * 5, 100)}%;"
										></span>
									</span>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<!-- Trade Execution Action -->
				<div class="pt-4 mt-2" style="border-top: 1px solid rgba(64, 66, 73, 0.4);">
					<Button 
						class="w-full bg-[#0177fb] hover:bg-[#0054c2] text-white font-bold" 
						disabled={workspace.isExecuting || executionSuccess} 
						onclick={handleExecute}
					>
						{#if workspace.isExecuting}
							<Loader2 class="mr-2 h-4 w-4 animate-spin" />
							Executing Trades...
						{:else if executionSuccess}
										Trade Batch Sent to OMS
						{:else}
							Execute Trades
						{/if}
					</Button>
				</div>
			</div>
		{:else if !workspace.isRebalancing}
			<div class="flex flex-col items-center justify-center gap-3 flex-1 py-12 text-center">
				<p class="text-[13px] text-[#85a0bd]">Add current holdings above and click <strong class="text-[#cbccd1]">Run Preview</strong> to see suggested trades.</p>
			</div>
		{/if}
	</div>
{/if}
