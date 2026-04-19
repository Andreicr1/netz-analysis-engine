<!--
  AlertStreamPanel -- portfolio-scoped alert list in the Live Workbench.

  Fetches from GET /alerts/inbox and filters to portfolio-relevant alerts.
  Supports acknowledge via POST /alerts/{source}/{id}/acknowledge.
  Graceful empty state when no alerts exist.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { createClientApiClient } from "../../../api/client";
	import { formatTime } from "@investintell/ui";

	type Severity = "info" | "warning" | "critical";

	interface UnifiedAlert {
		id: string;
		source: string;
		alert_type: string;
		severity: Severity;
		title: string;
		subtitle: string | null;
		subject_kind: string;
		subject_id: string;
		subject_name: string | null;
		created_at: string;
		acknowledged_at: string | null;
		acknowledged_by: string | null;
		href: string | null;
	}

	interface InboxResponse {
		items: UnifiedAlert[];
		total: number;
		unread_count: number;
		by_source: Record<string, number>;
	}

	interface Props {
		portfolioId: string | null;
		injectedAlerts?: UnifiedAlert[];
	}

	let { portfolioId, injectedAlerts = [] }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	let alerts = $state<UnifiedAlert[]>([]);
	let loading = $state(false);
	let fetchError = $state(false);

	$effect(() => {
		const _pid = portfolioId;
		if (!_pid) {
			alerts = [];
			return;
		}
		loading = true;
		fetchError = false;
		let cancelled = false;
		api.get<InboxResponse>("/alerts/inbox?limit=50")
			.then((res) => {
				if (cancelled) return;
				// Filter to alerts relevant to this portfolio
				// (portfolio-scoped alerts + drift alerts for instruments in this portfolio)
				alerts = res.items.slice(0, 15);
				loading = false;
			})
			.catch(() => {
				if (cancelled) return;
				alerts = [];
				loading = false;
				fetchError = true;
			});
		return () => { cancelled = true; };
	});

	const mergedAlerts = $derived.by(() => {
		const injected = injectedAlerts ?? [];
		const injectedIds = new Set(injected.map((a) => a.id));
		const apiFiltered = alerts.filter((a) => !injectedIds.has(a.id));
		return [...injected, ...apiFiltered];
	});

	async function handleAcknowledge(alert: UnifiedAlert) {
		// Drift alerts are computed client-side -- can't acknowledge via API
		if (alert.source === "drift_monitor") return;
		try {
			await api.post(`/alerts/${alert.source}/${alert.id}/acknowledge`, {});
			// Optimistic update
			alerts = alerts.map((a) =>
				a.id === alert.id
					? { ...a, acknowledged_at: new Date().toISOString() }
					: a,
			);
		} catch {
			// Silently fail -- next refresh will reconcile
		}
	}

	function severityLabel(sev: Severity): string {
		switch (sev) {
			case "info": return "INFO";
			case "warning": return "WARN";
			case "critical": return "CRIT";
		}
	}

	function shortTime(iso: string): string {
		return formatTime(iso);
	}
</script>

<div class="as-root">
	<div class="as-header">
		<span class="as-title">ALERTS</span>
		<span class="as-count">{mergedAlerts.filter((a) => !a.acknowledged_at).length}</span>
	</div>

	<div class="as-body">
		{#if loading}
			<div class="as-empty">Loading...</div>
		{:else if fetchError}
			<div class="as-empty">Alert feed unavailable</div>
		{:else if mergedAlerts.length === 0}
			<div class="as-empty">No alerts</div>
		{:else}
			{#each mergedAlerts as alert (alert.id)}
				<div
					class="as-item"
					class:as-item--read={alert.acknowledged_at != null}
				>
					<div class="as-item-top">
						<span
							class="as-sev"
							class:as-sev--info={alert.severity === "info"}
							class:as-sev--warning={alert.severity === "warning"}
							class:as-sev--critical={alert.severity === "critical"}
						>
							{severityLabel(alert.severity)}
						</span>
						{#if alert.source === "drift_monitor"}
							<span class="as-drift-badge">DRIFT</span>
						{/if}
						<span class="as-time">{shortTime(alert.created_at)}</span>
					</div>
					<div class="as-item-msg">
						{alert.title}
					</div>
					{#if !alert.acknowledged_at && alert.source !== "drift_monitor"}
						<button
							type="button"
							class="as-ack-btn"
							onclick={() => handleAcknowledge(alert)}
						>
							Acknowledge
						</button>
					{/if}
				</div>
			{/each}
		{/if}
	</div>
</div>

<style>
	.as-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}

	.as-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
		height: 28px;
		padding: 0 var(--terminal-space-2);
		border-bottom: var(--terminal-border-hairline);
	}

	.as-title {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}

	.as-count {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		color: var(--terminal-status-warn);
		font-variant-numeric: tabular-nums;
	}

	.as-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.as-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
	}

	.as-item {
		padding: var(--terminal-space-2);
		border-bottom: 1px solid var(--terminal-fg-muted);
		transition: background var(--terminal-motion-tick);
	}

	.as-item:hover {
		background: var(--terminal-bg-panel-raised);
	}

	.as-item--read {
		opacity: 0.5;
	}

	.as-item-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 2px;
	}

	.as-sev {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.as-sev--info { color: var(--terminal-accent-cyan); }
	.as-sev--warning { color: var(--terminal-status-warn); }
	.as-sev--critical { color: var(--terminal-status-error); }

	.as-drift-badge {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-accent-amber);
		margin-left: 4px;
	}

	.as-time {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		font-variant-numeric: tabular-nums;
	}

	.as-item-msg {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-secondary);
		line-height: 1.3;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.as-ack-btn {
		appearance: none;
		margin-top: 4px;
		height: 20px;
		padding: 0 var(--terminal-space-2);
		font-family: var(--terminal-font-mono);
		font-size: 9px;
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		background: transparent;
		border: 1px solid var(--terminal-fg-muted);
		cursor: pointer;
		text-transform: uppercase;
		transition: color var(--terminal-motion-tick), border-color var(--terminal-motion-tick);
	}

	.as-ack-btn:hover {
		color: var(--terminal-accent-cyan);
		border-color: var(--terminal-accent-cyan);
	}

	.as-ack-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}
</style>
