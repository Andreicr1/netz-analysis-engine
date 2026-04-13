<!--
  /alerts -- Global Alerts Inbox (Phase 5).

  Fetches unified alerts from GET /alerts/inbox. Filter bar with
  severity + status. Keyboard navigation: J/K scroll, E acknowledge.
  Renders inside TerminalShell via (terminal) layout group.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { PanelErrorState } from "@investintell/ui/runtime";
	import { createClientApiClient } from "$lib/api/client";
	import { formatDateTime } from "@investintell/ui";

	type Severity = "info" | "warning" | "critical";
	type SeverityFilter = "all" | Severity;
	type StatusFilter = "all" | "open" | "acknowledged";

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

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	let alerts = $state<UnifiedAlert[]>([]);
	let loading = $state(true);
	let fetchError = $state(false);
	let severityFilter = $state<SeverityFilter>("all");
	let statusFilter = $state<StatusFilter>("all");
	let focusedIndex = $state(0);

	async function fetchAlerts() {
		loading = true;
		fetchError = false;
		try {
			const res = await api.get<InboxResponse>("/alerts/inbox?limit=200");
			alerts = res.items;
		} catch {
			alerts = [];
			fetchError = true;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		fetchAlerts();
	});

	const filteredAlerts = $derived.by(() => {
		let result = alerts;
		if (severityFilter !== "all") {
			result = result.filter((a) => a.severity === severityFilter);
		}
		if (statusFilter === "open") {
			result = result.filter((a) => !a.acknowledged_at);
		} else if (statusFilter === "acknowledged") {
			result = result.filter((a) => a.acknowledged_at != null);
		}
		return result;
	});

	async function handleAcknowledge(alert: UnifiedAlert) {
		try {
			await api.post(`/alerts/${alert.source}/${alert.id}/acknowledge`, {});
			alerts = alerts.map((a) =>
				a.id === alert.id
					? { ...a, acknowledged_at: new Date().toISOString() }
					: a,
			);
		} catch {
			// Next refresh reconciles
		}
	}

	function handleKeydown(event: KeyboardEvent) {
		const len = filteredAlerts.length;
		if (len === 0) return;

		if (event.key === "j" || event.key === "ArrowDown") {
			event.preventDefault();
			focusedIndex = Math.min(focusedIndex + 1, len - 1);
		} else if (event.key === "k" || event.key === "ArrowUp") {
			event.preventDefault();
			focusedIndex = Math.max(focusedIndex - 1, 0);
		} else if (event.key === "e" || event.key === "E") {
			event.preventDefault();
			const alert = filteredAlerts[focusedIndex];
			if (alert && !alert.acknowledged_at) {
				handleAcknowledge(alert);
			}
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
		if (iso.length < 16) return iso;
		return iso.substring(11, 16);
	}

	const SEVERITY_OPTIONS: { value: SeverityFilter; label: string }[] = [
		{ value: "all", label: "ALL" },
		{ value: "critical", label: "CRIT" },
		{ value: "warning", label: "WARN" },
		{ value: "info", label: "INFO" },
	];

	const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
		{ value: "all", label: "ALL" },
		{ value: "open", label: "OPEN" },
		{ value: "acknowledged", label: "READ" },
	];
</script>

<svelte:head>
	<title>Alerts -- InvestIntell</title>
</svelte:head>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<svelte:boundary>
	<div class="ai-root" role="main" onkeydown={handleKeydown} tabindex="-1">
		<div class="ai-header">
			<span class="ai-title">ALERTS INBOX</span>
			<span class="ai-hint">J/K navigate, E acknowledge</span>
		</div>

		<div class="ai-filters">
			<div class="ai-filter-group">
				<span class="ai-filter-label">SEVERITY</span>
				{#each SEVERITY_OPTIONS as opt (opt.value)}
					<button
						type="button"
						class="ai-filter-btn"
						class:ai-filter-btn--active={severityFilter === opt.value}
						onclick={() => { severityFilter = opt.value; focusedIndex = 0; }}
					>
						{opt.label}
					</button>
				{/each}
			</div>
			<div class="ai-filter-group">
				<span class="ai-filter-label">STATUS</span>
				{#each STATUS_OPTIONS as opt (opt.value)}
					<button
						type="button"
						class="ai-filter-btn"
						class:ai-filter-btn--active={statusFilter === opt.value}
						onclick={() => { statusFilter = opt.value; focusedIndex = 0; }}
					>
						{opt.label}
					</button>
				{/each}
			</div>
		</div>

		<div class="ai-body">
			{#if loading}
				<div class="ai-empty">Loading alerts...</div>
			{:else if fetchError}
				<div class="ai-empty">Failed to load alerts</div>
			{:else if filteredAlerts.length === 0}
				<div class="ai-empty">No alerts</div>
			{:else}
				{#each filteredAlerts as alert, i (alert.id)}
					<div
						class="ai-row"
						class:ai-row--focused={i === focusedIndex}
						class:ai-row--read={alert.acknowledged_at != null}
						role="button"
						tabindex="-1"
						onclick={() => { focusedIndex = i; }}
					>
						<span
							class="ai-sev"
							class:ai-sev--info={alert.severity === "info"}
							class:ai-sev--warning={alert.severity === "warning"}
							class:ai-sev--critical={alert.severity === "critical"}
						>
							{severityLabel(alert.severity)}
						</span>
						<span class="ai-source">{alert.source.toUpperCase()}</span>
						<span class="ai-msg">
							{alert.title}
							{#if alert.subtitle}
								<span class="ai-subtitle"> -- {alert.subtitle}</span>
							{/if}
						</span>
						<span class="ai-time">{shortTime(alert.created_at)}</span>
						{#if !alert.acknowledged_at}
							<button
								type="button"
								class="ai-ack-btn"
								onclick={(e: MouseEvent) => { e.stopPropagation(); handleAcknowledge(alert); }}
							>
								ACK
							</button>
						{:else}
							<span class="ai-read-badge">READ</span>
						{/if}
					</div>
				{/each}
			{/if}
		</div>
	</div>

	{#snippet failed(err: unknown, reset: () => void)}
		<PanelErrorState
			title="Alerts inbox error"
			message={err instanceof Error ? err.message : "Unexpected error"}
			onRetry={reset}
		/>
	{/snippet}
</svelte:boundary>

<style>
	.ai-root {
		display: flex;
		flex-direction: column;
		height: calc(100vh - 88px);
		background: var(--terminal-bg-void);
		font-family: var(--terminal-font-mono);
		outline: none;
		padding: var(--terminal-space-4);
		gap: var(--terminal-space-2);
	}

	.ai-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
	}

	.ai-title {
		font-size: var(--terminal-text-14);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-primary);
		text-transform: uppercase;
	}

	.ai-hint {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
		letter-spacing: var(--terminal-tracking-caps);
	}

	.ai-filters {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-4);
		flex-shrink: 0;
		padding: var(--terminal-space-2) 0;
		border-bottom: var(--terminal-border-hairline);
	}

	.ai-filter-group {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-1);
	}

	.ai-filter-label {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-muted);
		text-transform: uppercase;
		margin-right: var(--terminal-space-1);
	}

	.ai-filter-btn {
		appearance: none;
		height: 22px;
		padding: 0 var(--terminal-space-2);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		background: transparent;
		border: 1px solid var(--terminal-fg-muted);
		cursor: pointer;
		text-transform: uppercase;
		transition: color var(--terminal-motion-tick), border-color var(--terminal-motion-tick);
	}

	.ai-filter-btn:hover {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber-dim);
	}

	.ai-filter-btn--active {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber);
	}

	.ai-filter-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}

	.ai-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		background: var(--terminal-bg-panel);
	}

	.ai-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
	}

	.ai-row {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-2) var(--terminal-space-3);
		border-bottom: 1px solid var(--terminal-fg-muted);
		cursor: pointer;
		transition: background var(--terminal-motion-tick);
	}

	.ai-row:hover {
		background: var(--terminal-bg-panel-raised);
	}

	.ai-row--focused {
		background: var(--terminal-bg-panel-raised);
		outline: 1px solid var(--terminal-accent-amber-dim);
		outline-offset: -1px;
	}

	.ai-row--read {
		opacity: 0.5;
	}

	.ai-sev {
		flex-shrink: 0;
		width: 36px;
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.ai-sev--info { color: var(--terminal-accent-cyan); }
	.ai-sev--warning { color: var(--terminal-status-warn); }
	.ai-sev--critical { color: var(--terminal-status-error); }

	.ai-source {
		flex-shrink: 0;
		width: 64px;
		font-size: 9px;
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
	}

	.ai-msg {
		flex: 1;
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-secondary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.ai-subtitle {
		color: var(--terminal-fg-muted);
	}

	.ai-time {
		flex-shrink: 0;
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		font-variant-numeric: tabular-nums;
	}

	.ai-ack-btn {
		appearance: none;
		flex-shrink: 0;
		height: 20px;
		padding: 0 var(--terminal-space-2);
		font-family: var(--terminal-font-mono);
		font-size: 9px;
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-accent-cyan);
		background: transparent;
		border: 1px solid var(--terminal-accent-cyan);
		cursor: pointer;
		transition: background var(--terminal-motion-tick);
	}

	.ai-ack-btn:hover {
		background: var(--terminal-bg-panel-raised);
	}

	.ai-ack-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}

	.ai-read-badge {
		flex-shrink: 0;
		font-size: 9px;
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-muted);
	}
</style>
