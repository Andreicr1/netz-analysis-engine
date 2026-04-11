<script lang="ts">
	import { onMount, onDestroy } from "svelte";

	let alerts = $state<any[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let intervalId: ReturnType<typeof setInterval>;

	async function fetchAlerts() {
		try {
			const res = await fetch("/api/v1/wealth/monitoring/alerts");
			if (!res.ok) throw new Error("Failed to fetch alerts");
			alerts = await res.json();
			error = null;
		} catch (err: any) {
			error = err.message;
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		fetchAlerts();
		// Poll every 60 seconds
		intervalId = setInterval(fetchAlerts, 60000);
	});

	onDestroy(() => {
		if (intervalId) clearInterval(intervalId);
	});

	let stale_dd = $derived(alerts.filter(a => a.type === "stale_dd" || a.type === "stale_dd_report").length);
	let rebalance_overdue = $derived(alerts.filter(a => a.type === "rebalance_overdue" || a.alert_type === "rebalance_overdue").length);
	let cvar_breach = $derived(alerts.filter(a => a.type === "cvar_breach" || a.alert_type === "cvar_breach").length);
	let drift = $derived(alerts.filter(a => a.type === "strategy_drift" || a.alert_type === "strategy_drift").length);

	let totalCritical = $derived(stale_dd + rebalance_overdue + cvar_breach + drift);

</script>

<div class="risk-card {totalCritical > 0 ? 'has-alerts' : 'no-alerts'}">
	<header class="risk-header">
		{#if loading && alerts.length === 0}
			<span class="text-gray-500">[ SYS: SCANNING... ]</span>
		{:else if error}
			<span class="text-red">[ SYS: ALERT FEED OFFLINE ]</span>
		{:else if totalCritical > 0}
			<span class="animate-pulse text-red font-bold">[ ACTION REQUIRED ]</span>
		{:else}
			<span class="text-gray-500">[ SYS: ALERTS ]</span>
		{/if}
	</header>
	
	<div class="risk-body flex flex-col gap-1">
		<div class="flex justify-between">
			<span class={stale_dd > 0 ? 'text-red' : 'text-gray-400'}>DD_STALE:</span>
			<span class={stale_dd > 0 ? 'text-red' : 'text-gray-400'}>{stale_dd}</span>
		</div>
		<div class="flex justify-between">
			<span class={rebalance_overdue > 0 ? 'text-red' : 'text-gray-400'}>REBALANCE_OVERDUE:</span>
			<span class={rebalance_overdue > 0 ? 'text-red' : 'text-gray-400'}>{rebalance_overdue}</span>
		</div>
		<div class="flex justify-between">
			<span class={cvar_breach > 0 ? 'text-red' : 'text-gray-400'}>CVAR_BREACH:</span>
			<span class={cvar_breach > 0 ? 'text-red' : 'text-gray-400'}>{cvar_breach}</span>
		</div>
		<div class="flex justify-between">
			<span class={drift > 0 ? 'text-red' : 'text-gray-400'}>DRIFT:</span>
			<span class={drift > 0 ? 'text-red' : 'text-gray-400'}>{drift}</span>
		</div>
	</div>
</div>

<style>
	.risk-card {
		width: 100%;
		border: 1px solid #333333;
		padding: 12px;
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
		font-size: 11px;
		color: #e5e7eb;
	}

	.risk-card.no-alerts {
		background-color: #0a0a0a;
	}

	.risk-card.has-alerts {
		background-color: rgba(69, 10, 10, 0.2); /* bg-red-950/20 */
		border-color: #7f1d1d; /* slightly redder border */
	}

	.risk-header {
		margin-bottom: 12px;
		border-bottom: 1px dashed #333;
		padding-bottom: 6px;
	}

	.animate-pulse {
		animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
	}

	@keyframes pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: .5; }
	}
	
	.text-gray-500 { color: #6b7280; }
	.text-gray-400 { color: #9ca3af; }
	.text-red { color: #ef4444; }
	.font-bold { font-weight: 700; }
	.flex { display: flex; }
	.flex-col { flex-direction: column; }
	.justify-between { justify-content: space-between; }
	.gap-1 { gap: 0.25rem; }
</style>
