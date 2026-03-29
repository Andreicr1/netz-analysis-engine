<!--
  UniverseView — Approved assets + Pending Approval workflow.
  Self-loading component for embedding in Screener tabs.
-->
<script lang="ts">
	import { DataTable, EmptyState, formatDate, ActionButton, ConsequenceDialog } from "@investintell/ui";
	import { Badge } from "@investintell/ui/components/ui/badge";
	import { Button } from "@investintell/ui/components/ui/button";
	import { Skeleton } from "@investintell/ui/components/ui/skeleton";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	type UniverseAsset = {
		id: string;
		instrument_id: string;
		instrument_name: string;
		ticker: string | null;
		asset_class: string | null;
		block_id: string | null;
		approval_date: string | null;
		approved_by: string | null;
		status: string;
	};

	type PendingApproval = {
		id: string;
		instrument_id: string;
		instrument_name: string;
		ticker: string | null;
		asset_class: string | null;
		screener_score: number | null;
		screener_status: string | null;
		decision: string | null;
		rationale: string | null;
	};

	let universe = $state<UniverseAsset[]>([]);
	let pending = $state<PendingApproval[]>([]);
	let loading = $state(true);

	async function fetchData() {
		loading = true;
		try {
			const api = createClientApiClient(getToken);
			const [u, p] = await Promise.allSettled([
				api.get("/universe"),
				api.get("/universe/pending"),
			]);
			universe = (u.status === "fulfilled" ? u.value : []) as UniverseAsset[];
			pending = (p.status === "fulfilled" ? p.value : []) as PendingApproval[];
		} finally {
			loading = false;
		}
	}

	// Tabs
	type Tab = "approved" | "pending";
	let activeTab = $state<Tab>("approved");

	// Approval actions
	let actionError = $state<string | null>(null);
	let actionTarget = $state<PendingApproval | null>(null);
	let showApproveDialog = $state(false);
	let showRejectDialog = $state(false);
	let approving = $state(false);
	let rejecting = $state(false);

	function openApprove(item: PendingApproval) { actionTarget = item; showApproveDialog = true; }
	function openReject(item: PendingApproval) { actionTarget = item; showRejectDialog = true; }

	async function approveInstrument(payload: { rationale?: string }) {
		if (!actionTarget) return;
		approving = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/universe/funds/${actionTarget.instrument_id}/approve`, { decision: "approved", rationale: payload.rationale });
			showApproveDialog = false;
			await fetchData();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Approval failed";
		} finally {
			approving = false;
			actionTarget = null;
		}
	}

	async function rejectInstrument(payload: { rationale?: string }) {
		if (!actionTarget) return;
		rejecting = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/universe/funds/${actionTarget.instrument_id}/reject`, { decision: "rejected", rationale: payload.rationale });
			showRejectDialog = false;
			await fetchData();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Rejection failed";
		} finally {
			rejecting = false;
			actionTarget = null;
		}
	}

	const approvedColumns = [
		{ accessorKey: "instrument_name", header: "Name" },
		{ accessorKey: "ticker", header: "Ticker" },
		{ accessorKey: "asset_class", header: "Asset Class" },
		{ accessorKey: "block_id", header: "Block" },
		{ accessorKey: "approval_date", header: "Approved", cell: (info: { getValue: () => unknown }) => { const v = info.getValue(); return typeof v === "string" ? formatDate(v) : "—"; } },
		{ accessorKey: "approved_by", header: "By" },
	];

	// ── Audit trail (lazy load per fund) ──
	type AuditEntry = { event_type: string; actor: string | null; before: unknown; after: unknown; created_at: string };
	let auditFundId = $state<string | null>(null);
	let auditEntries = $state<AuditEntry[]>([]);
	let auditLoading = $state(false);
	let auditError = $state<string | null>(null);
	let auditAbort: (() => void) | null = null;

	function toggleAudit(fundId: string) {
		if (auditFundId === fundId) {
			auditFundId = null;
			auditEntries = [];
			return;
		}
		auditFundId = fundId;
		auditEntries = [];
		auditLoading = true;
		auditError = null;

		auditAbort?.();
		const controller = new AbortController();
		auditAbort = () => controller.abort();

		(async () => {
			try {
				const api = createClientApiClient(getToken);
				auditEntries = await api.get<AuditEntry[]>(`/universe/funds/${fundId}/audit-trail`);
			} catch (e) {
				if (!controller.signal.aborted) {
					auditError = e instanceof Error ? e.message : "Failed to load audit trail";
				}
			} finally {
				if (!controller.signal.aborted) {
					auditLoading = false;
				}
			}
		})();
	}

	// Load on mount
	fetchData();
</script>

<div class="space-y-4">
	{#if loading}
		<Skeleton class="h-10 rounded-lg" />
		<Skeleton class="h-64 rounded-xl" />
	{:else}
		<div class="flex items-center gap-3">
			<Badge variant="secondary">{universe.length} approved</Badge>
			{#if pending.length > 0}
				<Badge variant="outline">{pending.length} pending</Badge>
			{/if}
		</div>

		{#if actionError}
			<div class="rounded-md border border-(--ii-status-error) bg-(--ii-status-error)/10 p-3 text-sm text-(--ii-status-error)">
				{actionError}
				<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
			</div>
		{/if}

		<!-- Tab navigation -->
		<div class="flex gap-1 border-b border-(--ii-border)">
			<button
				class="px-4 py-2 text-sm font-medium transition-colors"
				class:border-b-2={activeTab === "approved"}
				class:border-(--ii-brand-primary)={activeTab === "approved"}
				class:text-(--ii-brand-primary)={activeTab === "approved"}
				class:text-(--ii-text-muted)={activeTab !== "approved"}
				onclick={() => activeTab = "approved"}
			>
				Approved ({universe.length})
			</button>
			<button
				class="px-4 py-2 text-sm font-medium transition-colors"
				class:border-b-2={activeTab === "pending"}
				class:border-(--ii-brand-primary)={activeTab === "pending"}
				class:text-(--ii-brand-primary)={activeTab === "pending"}
				class:text-(--ii-text-muted)={activeTab !== "pending"}
				onclick={() => activeTab = "pending"}
			>
				Pending Approval ({pending.length})
			</button>
		</div>

		{#if activeTab === "approved"}
			{#if universe.length === 0}
				<EmptyState title="No approved instruments" description="Approve instruments from the Pending tab to build your investment universe." />
			{:else}
				<DataTable data={universe} columns={approvedColumns} filterColumn="instrument_name" filterPlaceholder="Search instrument..." />

				<!-- Audit trail toggle per fund -->
				<div class="mt-4 space-y-2">
					<p class="text-xs font-medium uppercase tracking-wider text-(--ii-text-muted)">Audit Trail</p>
					<div class="flex flex-wrap gap-2">
						{#each universe as asset (asset.id)}
							<button
								class="rounded border px-2 py-1 text-xs transition-colors {auditFundId === asset.instrument_id ? 'border-(--ii-brand-primary) bg-(--ii-brand-primary)/10 text-(--ii-brand-primary)' : 'border-(--ii-border) text-(--ii-text-muted) hover:bg-(--ii-surface-alt)'}"
								onclick={() => toggleAudit(asset.instrument_id)}
							>
								{asset.instrument_name}
							</button>
						{/each}
					</div>

					{#if auditFundId}
						<div class="rounded-lg border border-(--ii-border) bg-(--ii-surface-elevated) p-3">
							{#if auditLoading}
								<p class="text-sm text-(--ii-text-muted)">Loading audit trail…</p>
							{:else if auditError}
								<p class="text-sm text-(--ii-danger)">{auditError}</p>
							{:else if auditEntries.length === 0}
								<p class="text-sm text-(--ii-text-muted)">No audit events recorded.</p>
							{:else}
								<div class="space-y-2">
									{#each auditEntries as entry, idx (idx)}
										<div class="flex items-start gap-3 border-b border-(--ii-border)/50 pb-2 text-sm last:border-0">
											<Badge variant="secondary">{entry.event_type}</Badge>
											<div class="flex-1">
												<span class="text-(--ii-text-primary)">{entry.actor ?? "system"}</span>
												<span class="ml-2 text-xs text-(--ii-text-muted)">{formatDate(entry.created_at)}</span>
											</div>
										</div>
									{/each}
								</div>
							{/if}
						</div>
					{/if}
				</div>
			{/if}
		{/if}

		{#if activeTab === "pending"}
			{#if pending.length === 0}
				<EmptyState title="No pending approvals" description="Run the screener to generate approval candidates." />
			{:else}
				<div class="space-y-2">
					{#each pending as item (item.instrument_id)}
						<div class="flex items-center justify-between rounded-lg border border-(--ii-border) bg-(--ii-surface-elevated) p-4">
							<div>
								<p class="text-sm font-medium text-(--ii-text-primary)">
									{item.instrument_name}
									{#if item.ticker}
										<span class="ml-1 font-mono text-xs text-(--ii-text-muted)">{item.ticker}</span>
									{/if}
								</p>
								<div class="mt-1 flex items-center gap-3 text-xs text-(--ii-text-muted)">
									{#if item.asset_class}<span>{item.asset_class}</span>{/if}
									{#if item.screener_status}<Badge variant="secondary">{item.screener_status}</Badge>{/if}
								</div>
							</div>
							<div class="flex gap-2">
								<Button size="sm" onclick={() => openApprove(item)} disabled={approving}>Approve</Button>
								<Button size="sm" variant="destructive" onclick={() => openReject(item)} disabled={rejecting}>Reject</Button>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		{/if}
	{/if}
</div>

<ConsequenceDialog
	bind:open={showApproveDialog}
	title="Approve Fund into Universe"
	impactSummary={actionTarget ? `"${actionTarget.instrument_name}" will become eligible for portfolio allocation.` : ""}
	confirmLabel="Approve for Universe"
	requireRationale={true}
	rationaleMinLength={10}
	rationalePlaceholder="Explain why this instrument should be in the investable universe..."
	onConfirm={approveInstrument}
	onCancel={() => { showApproveDialog = false; actionTarget = null; }}
>
	{#snippet consequenceList()}
		<ul class="list-disc space-y-1 pl-4 text-sm text-(--ii-text-secondary)">
			<li>Instrument becomes eligible for portfolio allocation</li>
			<li>Decision is recorded in audit trail</li>
		</ul>
	{/snippet}
</ConsequenceDialog>

<ConsequenceDialog
	bind:open={showRejectDialog}
	title="Reject Fund from Universe"
	impactSummary={actionTarget ? `"${actionTarget.instrument_name}" will be excluded from the investable universe.` : ""}
	destructive={true}
	confirmLabel="Confirm Rejection"
	requireRationale={true}
	rationaleMinLength={10}
	rationalePlaceholder="Explain why this instrument should be excluded..."
	onConfirm={rejectInstrument}
	onCancel={() => { showRejectDialog = false; actionTarget = null; }}
>
	{#snippet consequenceList()}
		<ul class="list-disc space-y-1 pl-4 text-sm text-(--ii-text-secondary)">
			<li>Instrument is excluded from the investable universe</li>
			<li>Rejection rationale is recorded for compliance</li>
		</ul>
	{/snippet}
</ConsequenceDialog>
