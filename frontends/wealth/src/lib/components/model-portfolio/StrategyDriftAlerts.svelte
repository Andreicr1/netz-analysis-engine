<!--
  StrategyDriftAlerts — Fund-level Z-score anomaly display.
  Shows per-fund drift severity with anomalous metric count.
  Embedded in the Portfolio Workspace view.
-->
<script lang="ts">
	import { formatNumber } from "@investintell/ui";
	import { AlertTriangle, ShieldAlert, ShieldCheck, RefreshCw } from "lucide-svelte";
	import type { StrategyDriftAlert } from "$lib/stores/portfolio-workspace.svelte";

	interface Props {
		alerts: StrategyDriftAlert[];
		loading: boolean;
		error: string | null;
		onRefresh: () => void;
	}

	let { alerts, loading, error, onRefresh }: Props = $props();

	const SEVERITY_CONFIG = {
		none:     { color: "text-[#11ec79]", bg: "bg-[#11ec79]/10", icon: ShieldCheck, label: "Stable" },
		moderate: { color: "text-[#f59e0b]", bg: "bg-[#f59e0b]/10", icon: AlertTriangle, label: "Moderate" },
		severe:   { color: "text-[#fc1a1a]", bg: "bg-[#fc1a1a]/10", icon: ShieldAlert, label: "Severe" },
	} as const;

	let actionableAlerts = $derived(
		alerts.filter(a => a.severity !== "none"),
	);
</script>

<div class="rounded-[16px] border border-white/10 bg-[#141519] p-6">
	<div class="flex items-center justify-between mb-4">
		<div class="flex items-center gap-3">
			<h3 class="text-[16px] font-semibold text-white">Strategy Drift</h3>
			{#if actionableAlerts.length > 0}
				<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[12px] font-medium bg-[#f59e0b]/10 text-[#f59e0b]">
					{actionableAlerts.length} alert{actionableAlerts.length !== 1 ? "s" : ""}
				</span>
			{/if}
		</div>
		<button
			type="button"
			class="p-2 rounded-full hover:bg-white/10 transition-colors text-white/60 hover:text-white"
			onclick={onRefresh}
			disabled={loading}
			aria-label="Refresh alerts"
		>
			<RefreshCw size={16} class={loading ? "animate-spin" : ""} />
		</button>
	</div>

	{#if loading && alerts.length === 0}
		<div class="space-y-3">
			{#each Array(2) as _}
				<div class="h-14 bg-white/5 rounded-[12px] animate-pulse"></div>
			{/each}
		</div>
	{:else if error}
		<div class="text-[14px] text-[#fc1a1a]/80 py-4">{error}</div>
	{:else if actionableAlerts.length > 0}
		<div class="space-y-2">
			{#each actionableAlerts as alert}
				{@const config = SEVERITY_CONFIG[alert.severity as keyof typeof SEVERITY_CONFIG] ?? SEVERITY_CONFIG.none}
				{@const Icon = config.icon}
				<div class="flex items-start gap-3 p-3 rounded-[12px] {config.bg} border border-white/5">
					<Icon size={16} class="{config.color} mt-0.5 shrink-0" />
					<div class="flex-1 min-w-0">
						<div class="flex items-center justify-between gap-2">
							<span class="text-[14px] font-medium text-white truncate">
								{alert.instrument_name}
							</span>
							<span class="text-[12px] font-medium {config.color} shrink-0">
								{config.label}
							</span>
						</div>
						<p class="text-[12px] text-[#85a0bd] mt-0.5">
							{alert.anomalous_count}/{alert.total_metrics} metrics anomalous
						</p>
						<!-- Z-score details -->
						{#if alert.metric_details}
							<div class="flex flex-wrap gap-1.5 mt-2">
								{#each Object.entries(alert.metric_details) as [metric, detail]}
									{#if detail.is_anomalous}
										<span class="text-[11px] px-1.5 py-0.5 rounded bg-white/5 text-[#85a0bd] tabular-nums">
											{metric.replace("_1y", "")}: z={formatNumber(detail.z_score, 1)}
										</span>
									{/if}
								{/each}
							</div>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{:else}
		<div class="py-6 text-center text-[14px] text-white/30">
			<ShieldCheck size={24} class="mx-auto mb-2 text-[#11ec79]/50" />
			All funds within normal behavioral parameters.
		</div>
	{/if}
</div>
