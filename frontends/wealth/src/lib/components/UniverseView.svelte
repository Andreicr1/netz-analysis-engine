<!--
  UniverseView — Approved assets + Pending Approval workflow.
  Self-loading component for embedding in Screener tabs.
-->
<script lang="ts">
	import { DataTable, EmptyState, Badge, Button, Skeleton, formatDate } from "@netz/ui";
	import { ActionButton, ConsequenceDialog } from "@netz/ui";
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
			<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
				{actionError}
				<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
			</div>
		{/if}

		<!-- Tab navigation -->
		<div class="flex gap-1 border-b border-(--netz-border)">
			<button
				class="px-4 py-2 text-sm font-medium transition-colors"
				class:border-b-2={activeTab === "approved"}
				class:border-(--netz-brand-primary)={activeTab === "approved"}
				class:text-(--netz-brand-primary)={activeTab === "approved"}
				class:text-(--netz-text-muted)={activeTab !== "approved"}
				onclick={() => activeTab = "approved"}
			>
				Approved ({universe.length})
			</button>
			<button
				class="px-4 py-2 text-sm font-medium transition-colors"
				class:border-b-2={activeTab === "pending"}
				class:border-(--netz-brand-primary)={activeTab === "pending"}
				class:text-(--netz-brand-primary)={activeTab === "pending"}
				class:text-(--netz-text-muted)={activeTab !== "pending"}
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
			{/if}
		{/if}

		{#if activeTab === "pending"}
			{#if pending.length === 0}
				<EmptyState title="No pending approvals" description="Run the screener to generate approval candidates." />
			{:else}
				<div class="space-y-2">
					{#each pending as item (item.instrument_id)}
						<div class="flex items-center justify-between rounded-lg border border-(--netz-border) bg-(--netz-surface-elevated) p-4">
							<div>
								<p class="text-sm font-medium text-(--netz-text-primary)">
									{item.instrument_name}
									{#if item.ticker}
										<span class="ml-1 font-mono text-xs text-(--netz-text-muted)">{item.ticker}</span>
									{/if}
								</p>
								<div class="mt-1 flex items-center gap-3 text-xs text-(--netz-text-muted)">
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
		<ul class="list-disc space-y-1 pl-4 text-sm text-(--netz-text-secondary)">
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
		<ul class="list-disc space-y-1 pl-4 text-sm text-(--netz-text-secondary)">
			<li>Instrument is excluded from the investable universe</li>
			<li>Rejection rationale is recorded for compliance</li>
		</ul>
	{/snippet}
</ConsequenceDialog>
