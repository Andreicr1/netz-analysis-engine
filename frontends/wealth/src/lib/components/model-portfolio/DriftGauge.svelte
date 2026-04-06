<!--
  DriftGauge — Block-level allocation drift visual indicator.
  Shows per-block drift bars with ok/maintenance/urgent color coding.
  Embedded in the Portfolio Workspace view.
-->
<script lang="ts">
	import { formatNumber, formatPercent, formatShortDate } from "@investintell/ui";
	import { AlertTriangle, CheckCircle, XOctagon, RefreshCw, Clock } from "lucide-svelte";
	import type { LiveDriftResult, BlockDrift } from "$lib/stores/portfolio-workspace.svelte";

	interface Props {
		drift: LiveDriftResult | null;
		loading: boolean;
		error: string | null;
		onRefresh: () => void;
		onRebalance?: () => void;
	}

	let { drift, loading, error, onRefresh, onRebalance }: Props = $props();

	const STATUS_CONFIG = {
		ok:          { color: "text-[#11ec79]", bg: "bg-[#11ec79]/10", border: "border-[#11ec79]/20", icon: CheckCircle, label: "On Target" },
		maintenance: { color: "text-[#f59e0b]", bg: "bg-[#f59e0b]/10", border: "border-[#f59e0b]/20", icon: AlertTriangle, label: "Maintenance" },
		urgent:      { color: "text-[#fc1a1a]", bg: "bg-[#fc1a1a]/10", border: "border-[#fc1a1a]/20", icon: XOctagon, label: "Urgent" },
	} as const;

	let overallConfig = $derived(
		drift ? STATUS_CONFIG[drift.overall_status as keyof typeof STATUS_CONFIG] ?? STATUS_CONFIG.ok : STATUS_CONFIG.ok,
	);

	/** True when the latest NAV date is more than 1 business day old. */
	let navStale = $derived.by(() => {
		if (!drift?.latest_nav_date) return false;
		const navDate = new Date(drift.latest_nav_date);
		const now = new Date();
		const diffMs = now.getTime() - navDate.getTime();
		const diffDays = diffMs / (1000 * 60 * 60 * 24);
		// Allow 3 calendar days to account for weekends
		return diffDays > 3;
	});

	function barWidth(block: BlockDrift): string {
		const pct = Math.min(Math.abs(block.absolute_drift) * 1000, 100);
		return `${pct}%`;
	}

	function barColor(status: string): string {
		if (status === "urgent") return "bg-[#fc1a1a]";
		if (status === "maintenance") return "bg-[#f59e0b]";
		return "bg-[#11ec79]";
	}
</script>

<div class="rounded-[16px] border border-white/10 bg-[#141519] p-6">
	<!-- Header -->
	<div class="flex items-center justify-between mb-4">
		<div class="flex items-center gap-3">
			<h3 class="text-[16px] font-semibold text-white">Allocation Drift</h3>
			{#if drift}
				{@const Icon = overallConfig.icon}
				<span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[12px] font-medium {overallConfig.bg} {overallConfig.border} border {overallConfig.color}">
					<Icon size={14} />
					{overallConfig.label}
				</span>
				{#if drift.latest_nav_date}
					<span class="inline-flex items-center gap-1 text-[11px] {navStale ? 'text-[#f59e0b]' : 'text-[#85a0bd]'}">
						{#if navStale}<Clock size={12} />{/if}
						As of {formatShortDate(drift.latest_nav_date)}
					</span>
				{/if}
			{/if}
		</div>
		<button
			type="button"
			class="p-2 rounded-full hover:bg-white/10 transition-colors text-white/60 hover:text-white"
			onclick={onRefresh}
			disabled={loading}
			aria-label="Refresh drift"
		>
			<RefreshCw size={16} class={loading ? "animate-spin" : ""} />
		</button>
	</div>

	{#if loading && !drift}
		<div class="space-y-3">
			{#each Array(3) as _}
				<div class="h-8 bg-white/5 rounded animate-pulse"></div>
			{/each}
		</div>
	{:else if error}
		<div class="text-[14px] text-[#fc1a1a]/80 py-4">{error}</div>
	{:else if drift}
		<!-- Summary row -->
		<div class="flex items-center gap-6 mb-4 text-[13px] text-[#85a0bd]">
			<span>Max drift: <span class="text-white font-medium tabular-nums">{formatPercent(drift.max_drift_pct * 100)}</span></span>
			<span>Turnover: <span class="text-white font-medium tabular-nums">{formatPercent(drift.estimated_turnover * 100)}</span></span>
		</div>

		<!-- Block bars -->
		<div class="space-y-2">
			{#each drift.blocks as block}
				<div class="flex items-center gap-3">
					<span class="text-[13px] text-[#85a0bd] w-[120px] truncate" title={block.block_id}>
						{block.block_id}
					</span>
					<div class="flex-1 h-[6px] bg-white/5 rounded-full overflow-hidden">
						<div
							class="h-full rounded-full transition-all duration-500 {barColor(block.status)}"
							style:width={barWidth(block)}
						></div>
					</div>
					<span class="text-[12px] tabular-nums w-[60px] text-right {block.status === 'ok' ? 'text-[#85a0bd]' : block.status === 'maintenance' ? 'text-[#f59e0b]' : 'text-[#fc1a1a]'}">
						{block.absolute_drift >= 0 ? "+" : ""}{formatNumber(block.absolute_drift * 100, 2)}%
					</span>
				</div>
			{/each}
		</div>

		<!-- Rebalance action -->
		{#if drift.rebalance_recommended && onRebalance}
			<div class="mt-4 pt-4 border-t border-white/10">
				<button
					type="button"
					class="w-full py-3 rounded-[12px] bg-[#0177fb] hover:bg-[#0166d9] text-white text-[14px] font-medium transition-colors"
					onclick={onRebalance}
				>
					Generate Rebalance Proposal
				</button>
			</div>
		{/if}
	{:else}
		<div class="py-6 text-center text-[14px] text-white/30">
			No drift data available. Portfolio may not be constructed yet.
		</div>
	{/if}
</div>
