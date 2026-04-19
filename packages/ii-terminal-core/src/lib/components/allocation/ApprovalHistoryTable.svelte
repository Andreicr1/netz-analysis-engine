<!--
  PR-A26.3 Section G — Approval history table.

  Collapsible, offset/limit pagination via refetch through the API
  client. Active/Superseded badge computed from is_active server-side.

  PR-4b — terminal-density re-skin. All colors via --terminal-*;
  row heights respect [data-density] via --t-row-height.
-->
<script lang="ts">
	import { formatDateTime, formatPercent } from "@investintell/ui";
	import {
		CheckCircle2,
		AlertTriangle,
		ChevronDown,
		ChevronRight,
	} from "lucide-svelte";
	import type {
		AllocationProfile,
		ApprovalHistoryResponse,
	} from "../../types/allocation-page";

	interface Props {
		profile: AllocationProfile;
		history: ApprovalHistoryResponse;
		apiGet: <T>(path: string) => Promise<T>;
	}
	let { profile, history, apiGet }: Props = $props();

	let expanded = $state(false);
	let offset = $state(0);
	const limit = 5;
	let override = $state<ApprovalHistoryResponse | null>(null);
	const current = $derived(override ?? history);
	let loading = $state(false);
	let errorMsg = $state<string | null>(null);

	async function fetchPage(nextOffset: number): Promise<void> {
		loading = true;
		errorMsg = null;
		try {
			const resp = await apiGet<ApprovalHistoryResponse>(
				`/portfolio/profiles/${profile}/approval-history?limit=${limit}&offset=${nextOffset}`,
			);
			override = resp;
			offset = nextOffset;
		} catch (err) {
			errorMsg = err instanceof Error ? err.message : "Failed to load";
		} finally {
			loading = false;
		}
	}

	function truncate(text: string | null, n = 60): string {
		if (!text) return "—";
		return text.length > n ? `${text.slice(0, n)}…` : text;
	}

	const canPrev = $derived(offset > 0);
	const canNext = $derived(offset + limit < current.total);
</script>

<section class="approval-history">
	<button
		type="button"
		class="approval-history__toggle"
		onclick={() => (expanded = !expanded)}
		aria-expanded={expanded}
	>
		{#if expanded}
			<ChevronDown class="w-4 h-4" />
		{:else}
			<ChevronRight class="w-4 h-4" />
		{/if}
		<h2 class="approval-history__title">Approval History</h2>
		<span class="approval-history__count">({current.total})</span>
	</button>

	{#if expanded}
		<div class="approval-history__body">
			{#if errorMsg}
				<p class="approval-history__error">{errorMsg}</p>
			{/if}

			{#if current.entries.length === 0}
				<p class="approval-history__empty">No approvals yet.</p>
			{:else}
				<div class="history-table-wrap">
					<table class="history-table">
						<thead>
							<tr>
								<th class="align-left">Status</th>
								<th class="align-left">Approved At</th>
								<th class="align-left">Approved By</th>
								<th class="align-right">CVaR</th>
								<th class="align-right">Expected Return</th>
								<th class="align-center">Feasible</th>
								<th class="align-left">Message</th>
							</tr>
						</thead>
						<tbody>
							{#each current.entries as entry (entry.approval_id)}
								<tr>
									<td class="align-left">
										{#if entry.is_active}
											<span class="status-pill status-pill--active">Active</span>
										{:else}
											<span class="status-pill status-pill--superseded"
												>Superseded</span
											>
										{/if}
									</td>
									<td class="align-left">{formatDateTime(entry.approved_at)}</td>
									<td class="align-left">{entry.approved_by}</td>
									<td class="align-right numeric">
										{entry.cvar_at_approval !== null
											? formatPercent(entry.cvar_at_approval)
											: "—"}
									</td>
									<td class="align-right numeric">
										{entry.expected_return_at_approval !== null
											? formatPercent(entry.expected_return_at_approval)
											: "—"}
									</td>
									<td class="align-center">
										{#if entry.cvar_feasible_at_approval}
											<span class="icon icon--ok">
												<CheckCircle2 class="w-4 h-4" />
											</span>
										{:else}
											<span class="icon icon--warn">
												<AlertTriangle class="w-4 h-4" />
											</span>
										{/if}
									</td>
									<td
										class="align-left muted"
										title={entry.operator_message ?? ""}
									>
										{truncate(entry.operator_message)}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}

			<div class="approval-history__pager">
				<button
					type="button"
					class="pager-btn"
					disabled={!canPrev || loading}
					onclick={() => void fetchPage(Math.max(0, offset - limit))}
				>
					Previous
				</button>
				<span class="pager-label">
					{offset + 1}–{Math.min(
						offset + current.entries.length,
						current.total,
					)} of {current.total}
				</span>
				<button
					type="button"
					class="pager-btn"
					disabled={!canNext || loading}
					onclick={() => void fetchPage(offset + limit)}
				>
					Next
				</button>
			</div>
		</div>
	{/if}
</section>

<style>
	.approval-history {
		border: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-primary);
	}
	.approval-history__toggle {
		width: 100%;
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		background: transparent;
		border: none;
		padding: var(--terminal-space-3) var(--terminal-space-4);
		color: var(--terminal-fg-secondary);
		font-family: var(--terminal-font-mono);
		text-align: left;
		cursor: pointer;
	}
	.approval-history__toggle:hover,
	.approval-history__toggle:focus-visible {
		color: var(--terminal-fg-primary);
		outline: none;
	}
	.approval-history__title {
		font-size: var(--terminal-text-12);
		font-weight: 500;
		margin: 0;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.approval-history__count {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
	}
	.approval-history__body {
		border-top: var(--terminal-border-hairline);
		padding: var(--terminal-space-3);
	}
	.approval-history__error {
		font-size: var(--terminal-text-10);
		color: var(--terminal-status-error);
		margin: 0 0 var(--terminal-space-2);
	}
	.approval-history__empty {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-tertiary);
		text-align: center;
		padding: var(--terminal-space-6) 0;
		margin: 0;
	}

	.history-table-wrap {
		overflow-x: auto;
		border: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel-raised);
	}
	.history-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--terminal-text-11);
		font-family: var(--terminal-font-mono);
	}
	.history-table thead tr {
		background: var(--terminal-bg-panel-sunken);
	}
	.history-table th {
		padding: var(--terminal-space-1) var(--terminal-space-3);
		font-weight: 500;
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.history-table tbody tr {
		border-top: var(--terminal-border-hairline);
		height: var(--t-row-height);
	}
	.history-table td {
		padding: var(--terminal-space-1) var(--terminal-space-3);
		color: var(--terminal-fg-primary);
	}
	.align-left {
		text-align: left;
	}
	.align-right {
		text-align: right;
	}
	.align-center {
		text-align: center;
	}
	.numeric {
		font-variant-numeric: tabular-nums;
	}
	.muted {
		color: var(--terminal-fg-tertiary);
	}

	.status-pill {
		display: inline-flex;
		align-items: center;
		padding: 0 var(--terminal-space-2);
		border: var(--terminal-border-hairline);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.status-pill--active {
		color: var(--terminal-status-success);
		border-color: var(--terminal-status-success);
	}
	.status-pill--superseded {
		color: var(--terminal-fg-tertiary);
		border-color: var(--terminal-fg-muted);
	}

	.icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
	}
	.icon--ok {
		color: var(--terminal-status-success);
	}
	.icon--warn {
		color: var(--terminal-status-warn);
	}

	.approval-history__pager {
		margin-top: var(--terminal-space-3);
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: var(--terminal-space-2);
	}
	.pager-btn {
		padding: var(--terminal-space-1) var(--terminal-space-3);
		border: var(--terminal-border-hairline);
		background: transparent;
		color: var(--terminal-fg-tertiary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		cursor: pointer;
		transition: color var(--terminal-motion-tick)
				var(--terminal-motion-easing-out),
			border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}
	.pager-btn:hover:not(:disabled),
	.pager-btn:focus-visible:not(:disabled) {
		color: var(--terminal-fg-primary);
		border-color: var(--terminal-fg-secondary);
		outline: none;
	}
	.pager-btn:disabled {
		color: var(--terminal-fg-disabled);
		border-color: var(--terminal-fg-disabled);
		cursor: not-allowed;
		opacity: 0.4;
	}
	.pager-label {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
	}
</style>
