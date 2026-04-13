<!--
  RebalancePreview — Institutional-grade trade proposal table.
  Triggered on-demand from the drift gauge when rebalance is recommended.
  Calls POST /model-portfolios/{id}/rebalance/preview via the workspace store.
-->
<script lang="ts">
	import { formatNumber, formatCurrency, formatPercent } from "@investintell/ui";
	import { X, ArrowUpRight, ArrowDownRight, Minus, Loader2 } from "lucide-svelte";
	import type { RebalancePreviewResult, SuggestedTrade } from "$lib/stores/portfolio-workspace.svelte";

	interface Props {
		preview: RebalancePreviewResult | null;
		loading: boolean;
		error: string | null;
		open: boolean;
		onclose: () => void;
	}

	let { preview, loading, error, open, onclose }: Props = $props();

	function actionIcon(action: string) {
		if (action === "BUY") return ArrowUpRight;
		if (action === "SELL") return ArrowDownRight;
		return Minus;
	}

	function actionColor(action: string): string {
		if (action === "BUY") return "text-[#11ec79]";
		if (action === "SELL") return "text-[#fc1a1a]";
		return "text-[#85a0bd]";
	}

	function actionBg(action: string): string {
		if (action === "BUY") return "bg-[#11ec79]/10";
		if (action === "SELL") return "bg-[#fc1a1a]/10";
		return "bg-white/5";
	}
</script>

{#if open}
	<!-- Backdrop -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" onclick={onclose}></div>

	<!-- Drawer -->
	<div class="fixed right-0 top-0 bottom-0 z-50 w-full max-w-[720px] bg-[#1a1b20] border-l border-white/10 shadow-2xl flex flex-col">
		<!-- Header -->
		<div class="flex items-center justify-between px-6 py-5 border-b border-white/10">
			<div>
				<h2 class="text-[18px] font-semibold text-white">Rebalance Preview</h2>
				{#if preview}
					<p class="text-[13px] text-[#85a0bd] mt-0.5">
						{preview.portfolio_name} · {preview.profile} · AUM {formatCurrency(preview.total_aum)}
					</p>
				{/if}
			</div>
			<button
				type="button"
				class="p-2 rounded-full hover:bg-white/10 text-white/60 hover:text-white transition-colors"
				onclick={onclose}
				aria-label="Close"
			>
				<X size={20} />
			</button>
		</div>

		<!-- Content -->
		<div class="flex-1 overflow-y-auto px-6 py-4">
			{#if loading}
				<div class="flex items-center justify-center py-16 gap-3 text-[#85a0bd]">
					<Loader2 size={20} class="animate-spin" />
					<span class="text-[14px]">Computing trade proposals...</span>
				</div>
			{:else if error}
				<div class="py-8 text-center text-[14px] text-[#fc1a1a]/80">{error}</div>
			{:else if preview}
				<!-- CVaR Warning Banner -->
				{#if preview.cvar_warning}
					<div class="mb-4 rounded-[12px] border border-[#f59e0b]/30 bg-[#f59e0b]/10 px-4 py-3 flex items-start gap-3">
						<span class="text-[#f59e0b] text-[18px] leading-none mt-0.5">⚠</span>
						<div>
							<span class="text-[13px] font-semibold text-[#f59e0b] block">Risk Limit Warning</span>
							<span class="text-[12px] text-[#85a0bd]">
								Projected tail loss ({formatPercent((preview.cvar_95_projected ?? 0) * 100)}) is approaching
								{#if preview.cvar_limit != null}
									the limit ({formatPercent(preview.cvar_limit * 100)}).
								{:else}
									the allocation limit.
								{/if}
								Review trades before executing.
							</span>
						</div>
					</div>
				{/if}

				<!-- Summary cards -->
				<div class="grid grid-cols-3 gap-3 mb-6">
					<div class="rounded-[12px] bg-white/5 p-4">
						<span class="text-[12px] text-[#85a0bd] block mb-1">Total Trades</span>
						<span class="text-[20px] font-bold text-white tabular-nums">{preview.total_trades}</span>
					</div>
					<div class="rounded-[12px] bg-white/5 p-4">
						<span class="text-[12px] text-[#85a0bd] block mb-1">Est. Turnover</span>
						<span class="text-[20px] font-bold text-white tabular-nums">{formatPercent(preview.estimated_turnover_pct)}</span>
					</div>
					<div class="rounded-[12px] bg-white/5 p-4">
						<span class="text-[12px] text-[#85a0bd] block mb-1">Cash Available</span>
						<span class="text-[20px] font-bold text-white tabular-nums">{formatCurrency(preview.cash_available)}</span>
					</div>
				</div>

				<!-- Trade table -->
				<table class="w-full">
					<thead>
						<tr class="border-b border-white/10">
							<th class="text-left text-[12px] font-semibold text-[#85a0bd] uppercase tracking-wider pb-3 pr-3">Action</th>
							<th class="text-left text-[12px] font-semibold text-[#85a0bd] uppercase tracking-wider pb-3 pr-3">Instrument</th>
							<th class="text-right text-[12px] font-semibold text-[#85a0bd] uppercase tracking-wider pb-3 pr-3">Current</th>
							<th class="text-right text-[12px] font-semibold text-[#85a0bd] uppercase tracking-wider pb-3 pr-3">Target</th>
							<th class="text-right text-[12px] font-semibold text-[#85a0bd] uppercase tracking-wider pb-3 pr-3">Delta</th>
							<th class="text-right text-[12px] font-semibold text-[#85a0bd] uppercase tracking-wider pb-3">Trade Value</th>
						</tr>
					</thead>
					<tbody>
						{#each preview.trades as trade}
							{@const Icon = actionIcon(trade.action)}
							<tr class="border-b border-white/5 hover:bg-white/[0.02] transition-colors">
								<td class="py-3 pr-3">
									<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[12px] font-medium {actionBg(trade.action)} {actionColor(trade.action)}">
										<Icon size={12} />
										{trade.action}
									</span>
								</td>
								<td class="py-3 pr-3">
									<div class="flex flex-col">
										<span class="text-[14px] text-white">{trade.fund_name.length > 35 ? trade.fund_name.slice(0, 35) + "..." : trade.fund_name}</span>
										<span class="text-[11px] text-[#85a0bd]">{trade.block_id}</span>
									</div>
								</td>
								<td class="py-3 pr-3 text-right text-[13px] text-white tabular-nums">
									{formatPercent(trade.current_weight * 100)}
								</td>
								<td class="py-3 pr-3 text-right text-[13px] text-white tabular-nums">
									{formatPercent(trade.target_weight * 100)}
								</td>
								<td class="py-3 pr-3 text-right text-[13px] tabular-nums {actionColor(trade.action)}">
									{trade.delta_weight >= 0 ? "+" : ""}{formatNumber(trade.delta_weight * 100, 2)}pp
								</td>
								<td class="py-3 text-right text-[13px] tabular-nums {actionColor(trade.action)}">
									{trade.trade_value >= 0 ? "+" : ""}{formatCurrency(Math.abs(trade.trade_value))}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>

				<!-- Weight comparison -->
				{#if preview.weight_comparison.length > 0}
					<div class="mt-6">
						<h4 class="text-[14px] font-medium text-white mb-3">Block Weight Comparison</h4>
						<div class="space-y-2">
							{#each preview.weight_comparison as wc}
								<div class="flex items-center gap-3 text-[13px]">
									<span class="text-[#85a0bd] w-[120px] truncate">{wc.block_id}</span>
									<span class="text-white tabular-nums w-[60px] text-right">{formatPercent(wc.current_weight * 100)}</span>
									<span class="text-[#85a0bd]">&rarr;</span>
									<span class="text-white tabular-nums w-[60px] text-right">{formatPercent(wc.target_weight * 100)}</span>
									<span class="tabular-nums {wc.delta_pp >= 0 ? 'text-[#11ec79]' : 'text-[#fc1a1a]'}">
										({wc.delta_pp >= 0 ? "+" : ""}{formatNumber(wc.delta_pp, 2)}pp)
									</span>
								</div>
							{/each}
						</div>
					</div>
				{/if}
			{:else}
				<div class="py-16 text-center text-[14px] text-white/30">
					Click "Generate Rebalance Proposal" to compute trade suggestions.
				</div>
			{/if}
		</div>
	</div>
{/if}
