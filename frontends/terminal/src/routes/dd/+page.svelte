<!--
  /dd — DD Track Kanban (Phase 6, Session A).

  Three-column kanban for DD report queue: QUEUE (pending),
  IN PROGRESS, COMPLETED. Fetches from GET /dd-reports/queue
  and polls every 30 seconds. Terminal-native primitives only.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { goto } from "$app/navigation";
	import { resolve } from "$app/paths";
	import { createClientApiClient } from "@investintell/ii-terminal-core/api/client";
	import Panel from "@investintell/ii-terminal-core/components/terminal/layout/Panel.svelte";
	import PanelHeader from "@investintell/ii-terminal-core/components/terminal/layout/PanelHeader.svelte";
	import DDQueueCard from "@investintell/ii-terminal-core/components/terminal/dd/DDQueueCard.svelte";

	interface DDReportQueueItem {
		id: string;
		instrument_id: string;
		instrument_label: string | null;
		report_type: string;
		version: number;
		status: string;
		confidence_score: number | null;
		decision_anchor: string | null;
		created_at: string;
		approved_at: string | null;
		progress_pct: number | null;
		current_chapter: string | null;
	}

	interface DDReportsQueueOut {
		pending: DDReportQueueItem[];
		in_progress: DDReportQueueItem[];
		completed_recent: DDReportQueueItem[];
		counts: Record<string, number>;
	}

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	let pending = $state<DDReportQueueItem[]>([]);
	let inProgress = $state<DDReportQueueItem[]>([]);
	let completed = $state<DDReportQueueItem[]>([]);
	let counts = $state<Record<string, number>>({});
	let loading = $state(true);
	let fetchError = $state(false);

	async function fetchQueue() {
		try {
			const res = await api.get<DDReportsQueueOut>("/dd-reports/queue");
			pending = res.pending;
			inProgress = res.in_progress;
			completed = res.completed_recent;
			counts = res.counts;
			fetchError = false;
		} catch {
			fetchError = true;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		fetchQueue();
		const timer = setInterval(fetchQueue, 30_000);
		return () => clearInterval(timer);
	});

	const DD_BASE = resolve("/dd");

	function navigateToReport(id: string) {
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- DD_BASE is already a resolve() result; template concat is the supported pattern for dynamic segments in this codebase.
		goto(`${DD_BASE}/${id}`);
	}

	const pendingCount = $derived(counts.pending ?? pending.length);
	const inProgressCount = $derived(counts.in_progress ?? inProgress.length);
	const completedCount = $derived(counts.completed_recent ?? completed.length);
</script>

<div class="dd-kanban" data-dd-root>
	{#if loading}
		<div class="dd-loading">Loading DD queue...</div>
	{:else if fetchError}
		<div class="dd-error">Failed to load DD queue. Retrying...</div>
	{:else}
		<div class="dd-columns">
			<div class="dd-column">
				<Panel scrollable>
					{#snippet header()}
						<PanelHeader label="QUEUE">
							{#snippet actions()}
								<span class="dd-count-badge dd-count-badge--secondary">{pendingCount}</span>
							{/snippet}
						</PanelHeader>
					{/snippet}
					<div class="dd-card-list">
						{#each pending as item (item.id)}
							<DDQueueCard
								id={item.id}
								instrumentId={item.instrument_id}
								instrumentLabel={item.instrument_label}
								status={item.status}
								version={item.version}
								confidenceScore={item.confidence_score}
								decisionAnchor={item.decision_anchor}
								createdAt={item.created_at}
								approvedAt={item.approved_at}
								onClick={() => navigateToReport(item.id)}
							/>
						{:else}
							<span class="dd-empty">No reports queued</span>
						{/each}
					</div>
				</Panel>
			</div>

			<div class="dd-column">
				<Panel scrollable>
					{#snippet header()}
						<PanelHeader label="IN PROGRESS">
							{#snippet actions()}
								<span class="dd-count-badge dd-count-badge--amber">{inProgressCount}</span>
							{/snippet}
						</PanelHeader>
					{/snippet}
					<div class="dd-card-list">
						{#each inProgress as item (item.id)}
							<DDQueueCard
								id={item.id}
								instrumentId={item.instrument_id}
								instrumentLabel={item.instrument_label}
								status={item.status}
								version={item.version}
								confidenceScore={item.confidence_score}
								decisionAnchor={item.decision_anchor}
								createdAt={item.created_at}
								approvedAt={item.approved_at}
								onClick={() => navigateToReport(item.id)}
							/>
						{:else}
							<span class="dd-empty">No reports in progress</span>
						{/each}
					</div>
				</Panel>
			</div>

			<div class="dd-column">
				<Panel scrollable>
					{#snippet header()}
						<PanelHeader label="COMPLETED">
							{#snippet actions()}
								<span class="dd-count-badge dd-count-badge--secondary">{completedCount}</span>
							{/snippet}
						</PanelHeader>
					{/snippet}
					<div class="dd-card-list">
						{#each completed as item (item.id)}
							<DDQueueCard
								id={item.id}
								instrumentId={item.instrument_id}
								instrumentLabel={item.instrument_label}
								status={item.status}
								version={item.version}
								confidenceScore={item.confidence_score}
								decisionAnchor={item.decision_anchor}
								createdAt={item.created_at}
								approvedAt={item.approved_at}
								onClick={() => navigateToReport(item.id)}
							/>
						{:else}
							<span class="dd-empty">No completed reports</span>
						{/each}
					</div>
				</Panel>
			</div>
		</div>
	{/if}
</div>

<style>
	.dd-kanban {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		font-family: var(--terminal-font-mono);
		overflow: hidden;
	}

	.dd-columns {
		display: grid;
		grid-template-columns: 1fr 1fr 1fr;
		gap: var(--terminal-space-3);
		width: 100%;
		height: 100%;
		min-height: 0;
	}

	.dd-column {
		min-height: 0;
		overflow: hidden;
	}

	.dd-card-list {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
	}

	.dd-count-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 18px;
		height: 16px;
		padding: 0 4px;
		font-size: var(--terminal-text-10);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		border-radius: var(--terminal-radius-none);
	}

	.dd-count-badge--secondary {
		background: var(--terminal-fg-muted);
		color: var(--terminal-fg-inverted);
	}

	.dd-count-badge--amber {
		background: var(--terminal-accent-amber);
		color: var(--terminal-fg-inverted);
	}

	.dd-loading,
	.dd-error {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.dd-error {
		color: var(--terminal-status-error);
	}

	.dd-empty {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		padding: var(--terminal-space-3);
	}
</style>
