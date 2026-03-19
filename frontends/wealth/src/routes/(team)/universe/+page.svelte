<!--
  Investment Universe — Approved assets + Pending Approval workflow.
  Two tabs: Approved (default) and Pending Approval with approve/reject actions.
-->
<script lang="ts">
	import {
		DataTable, PageHeader, EmptyState, Badge, Button,
		formatDate,
	} from "@netz/ui";
	import { ActionButton, ConfirmDialog } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	// ── Types ──

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

	let universe = $derived((data.universe ?? []) as UniverseAsset[]);
	let pending = $derived((data.pending ?? []) as PendingApproval[]);

	// ── Tabs ──

	type Tab = "approved" | "pending";
	let activeTab = $state<Tab>("approved");

	// ── Approval actions ──

	let actionError = $state<string | null>(null);
	let actionTarget = $state<PendingApproval | null>(null);
	let showApproveDialog = $state(false);
	let showRejectDialog = $state(false);
	let rejectRationale = $state("");
	let approving = $state(false);
	let rejecting = $state(false);

	function openApprove(item: PendingApproval) {
		actionTarget = item;
		showApproveDialog = true;
	}

	function openReject(item: PendingApproval) {
		actionTarget = item;
		rejectRationale = "";
		showRejectDialog = true;
	}

	async function approveInstrument() {
		if (!actionTarget) return;
		approving = true;
		actionError = null;
		showApproveDialog = false;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/universe/funds/${actionTarget.instrument_id}/approve`, {
				decision: "approved",
			});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Approval failed";
		} finally {
			approving = false;
			actionTarget = null;
		}
	}

	async function rejectInstrument() {
		if (!actionTarget) return;
		rejecting = true;
		actionError = null;
		showRejectDialog = false;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/universe/funds/${actionTarget.instrument_id}/reject`, {
				decision: "rejected",
				rationale: rejectRationale.trim() || undefined,
			});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Rejection failed";
		} finally {
			rejecting = false;
			actionTarget = null;
			rejectRationale = "";
		}
	}

	// ── Table columns ──

	const approvedColumns = [
		{ accessorKey: "instrument_name", header: "Name" },
		{ accessorKey: "ticker", header: "Ticker" },
		{ accessorKey: "asset_class", header: "Asset Class" },
		{ accessorKey: "block_id", header: "Block" },
		{
			accessorKey: "approval_date",
			header: "Approved",
			cell: (info: { getValue: () => unknown }) => {
				const v = info.getValue();
				return typeof v === "string" ? formatDate(v) : "—";
			},
		},
		{ accessorKey: "approved_by", header: "By" },
	];

	const pendingColumns = [
		{ accessorKey: "instrument_name", header: "Name" },
		{ accessorKey: "ticker", header: "Ticker" },
		{ accessorKey: "asset_class", header: "Asset Class" },
		{ accessorKey: "screener_status", header: "Screener Status" },
	];
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	<PageHeader title="Investment Universe">
		{#snippet actions()}
			<Badge variant="secondary">{universe.length} approved</Badge>
			{#if pending.length > 0}
				<Badge variant="outline">{pending.length} pending</Badge>
			{/if}
		{/snippet}
	</PageHeader>

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

	<!-- Approved tab -->
	{#if activeTab === "approved"}
		{#if universe.length === 0}
			<EmptyState
				title="No approved instruments"
				description="Approve instruments from the Pending tab to build your investment universe."
			/>
		{:else}
			<DataTable
				data={universe}
				columns={approvedColumns}
				filterColumn="instrument_name"
				filterPlaceholder="Search instrument..."
			/>
		{/if}
	{/if}

	<!-- Pending tab -->
	{#if activeTab === "pending"}
		{#if pending.length === 0}
			<EmptyState
				title="No pending approvals"
				description="Run the screener to generate approval candidates."
			/>
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
								{#if item.asset_class}
									<span>{item.asset_class}</span>
								{/if}
								{#if item.screener_status}
									<Badge variant="secondary">{item.screener_status}</Badge>
								{/if}
							</div>
						</div>
						<div class="flex gap-2">
							<Button
								size="sm"
								onclick={() => openApprove(item)}
								disabled={approving}
							>
								Approve
							</Button>
							<Button
								size="sm"
								variant="destructive"
								onclick={() => openReject(item)}
								disabled={rejecting}
							>
								Reject
							</Button>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	{/if}
</div>

<!-- Approve confirmation -->
<ConfirmDialog
	bind:open={showApproveDialog}
	title="Approve Instrument"
	message={actionTarget ? `Approve "${actionTarget.instrument_name}" for the investment universe?` : ""}
	confirmLabel="Approve"
	confirmVariant="default"
	onConfirm={approveInstrument}
	onCancel={() => { showApproveDialog = false; actionTarget = null; }}
/>

<!-- Reject confirmation with rationale -->
{#if showRejectDialog && actionTarget}
	<ConfirmDialog
		bind:open={showRejectDialog}
		title="Reject Instrument"
		message={`Reject "${actionTarget.instrument_name}" from the investment universe?`}
		confirmLabel="Reject"
		confirmVariant="destructive"
		onConfirm={rejectInstrument}
		onCancel={() => { showRejectDialog = false; actionTarget = null; rejectRationale = ""; }}
	/>
{/if}
