<!--
  Portfolio — tabs: Assets, Obligations, Alerts, Actions.
  CRUD: Create asset, create obligation, update obligation status, update action status.
-->
<script lang="ts">
	import { PageTabs, DataTable, StatusBadge, EmptyState, Button, Dialog, Card } from "@netz/ui";
	import { ActionButton, ConfirmDialog, FormField } from "@netz/ui";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type {
		PaginatedResponse, PortfolioAsset, PortfolioObligation,
		PortfolioAlert, PortfolioAction,
		AssetType, Strategy, ObligationType, ObligationStatus, ActionStatus,
	} from "$lib/types/api";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();
	let activeTab = $state("assets");
	let actionError = $state<string | null>(null);

	let assets = $derived((data.assets as PaginatedResponse<PortfolioAsset>)?.items ?? []);
	let obligations = $derived((data.obligations as PaginatedResponse<PortfolioObligation>)?.items ?? []);
	let alerts = $derived((data.alerts as PaginatedResponse<PortfolioAlert>)?.items ?? []);
	let actions = $derived((data.actions as PaginatedResponse<PortfolioAction>)?.items ?? []);

	// ── Create Asset Dialog ──
	let showCreateAsset = $state(false);
	let savingAsset = $state(false);
	let assetForm = $state({
		name: "",
		asset_type: "DIRECT_LOAN" as AssetType,
		strategy: "CORE_DIRECT_LENDING" as Strategy,
	});

	let assetNameValid = $derived(assetForm.name.trim().length >= 2);

	function resetAssetForm() {
		assetForm = { name: "", asset_type: "DIRECT_LOAN", strategy: "CORE_DIRECT_LENDING" };
		actionError = null;
	}

	async function createAsset() {
		savingAsset = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/assets`, {
				name: assetForm.name.trim(),
				asset_type: assetForm.asset_type,
				strategy: assetForm.strategy,
			});
			showCreateAsset = false;
			resetAssetForm();
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to create asset";
		} finally {
			savingAsset = false;
		}
	}

	// ── Create Obligation Dialog ──
	let showCreateObligation = $state(false);
	let savingObligation = $state(false);
	let selectedAssetId = $state<string | null>(null);
	let obligationForm = $state({
		obligation_type: "NAV_REPORT" as ObligationType,
		due_date: "",
	});

	function openObligationDialog(assetId: string) {
		selectedAssetId = assetId;
		obligationForm = { obligation_type: "NAV_REPORT", due_date: "" };
		actionError = null;
		showCreateObligation = true;
	}

	async function createObligation() {
		if (!selectedAssetId || !obligationForm.due_date) return;
		savingObligation = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/assets/${selectedAssetId}/obligations`, {
				obligation_type: obligationForm.obligation_type,
				due_date: obligationForm.due_date,
			});
			showCreateObligation = false;
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to create obligation";
		} finally {
			savingObligation = false;
		}
	}

	// ── Update Obligation Status ──
	let updatingObligationId = $state<string | null>(null);
	let showWaiveConfirm = $state(false);
	let waiveTargetId = $state<string | null>(null);

	function confirmWaive(obligationId: string) {
		waiveTargetId = obligationId;
		showWaiveConfirm = true;
	}

	async function executeWaive() {
		if (!waiveTargetId) return;
		showWaiveConfirm = false;
		await updateObligationStatus(waiveTargetId, "WAIVED");
		waiveTargetId = null;
	}

	async function updateObligationStatus(obligationId: string, status: ObligationStatus) {
		updatingObligationId = obligationId;
		try {
			const api = createClientApiClient(getToken);
			await api.patch(`/funds/${data.fundId}/obligations/${obligationId}`, { status });
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to update obligation";
		} finally {
			updatingObligationId = null;
		}
	}

	// ── Update Action Status ──
	let updatingActionId = $state<string | null>(null);

	async function updateActionStatus(actionId: string, status: ActionStatus, notes?: string) {
		updatingActionId = actionId;
		try {
			const api = createClientApiClient(getToken);
			await api.patch(`/funds/${data.fundId}/portfolio/actions/${actionId}`, {
				status,
				evidence_notes: notes ?? null,
			});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to update action";
		} finally {
			updatingActionId = null;
		}
	}

	const assetColumns = [
		{ accessorKey: "name", header: "Name" },
		{ accessorKey: "asset_type", header: "Type" },
		{ accessorKey: "strategy", header: "Strategy" },
	];

	const obligationColumns = [
		{ accessorKey: "obligation_type", header: "Type" },
		{ accessorKey: "due_date", header: "Due Date" },
		{ accessorKey: "status", header: "Status" },
	];

	const alertColumns = [
		{ accessorKey: "severity", header: "Severity" },
		{ accessorKey: "message", header: "Message" },
		{ accessorKey: "asset_name", header: "Asset" },
		{ accessorKey: "created_at", header: "Date" },
	];

	const actionColumns = [
		{ accessorKey: "title", header: "Action" },
		{ accessorKey: "status", header: "Status" },
		{ accessorKey: "evidence_notes", header: "Notes" },
	];
</script>

<div class="p-6">
	<div class="mb-4 flex items-center justify-between">
		<h2 class="text-xl font-semibold text-[var(--netz-text-primary)]">Portfolio</h2>
		{#if activeTab === "assets"}
			<Button onclick={() => { resetAssetForm(); showCreateAsset = true; }}>Add Asset</Button>
		{/if}
	</div>

	{#if actionError}
		<div class="mb-4 rounded-md border border-[var(--netz-status-error)] bg-[var(--netz-status-error)]/10 p-3 text-sm text-[var(--netz-status-error)]">
			{actionError}
			<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
		</div>
	{/if}

	<PageTabs
		tabs={[
			{ id: "assets", label: `Assets (${assets.length})` },
			{ id: "obligations", label: `Obligations (${obligations.length})` },
			{ id: "alerts", label: `Alerts (${alerts.length})` },
			{ id: "actions", label: `Actions (${actions.length})` },
		]}
		active={activeTab}
		onChange={(tab) => activeTab = tab}
	/>

	<div class="mt-4">
		{#if activeTab === "assets"}
			{#if assets.length === 0}
				<EmptyState title="No Assets" description="Portfolio assets will appear here after deal conversion or manual creation." />
			{:else}
				<div class="space-y-3">
					{#each assets as asset (asset.id)}
						<Card class="flex items-center justify-between p-4">
							<div>
								<p class="text-sm font-medium text-[var(--netz-text-primary)]">{asset.name}</p>
								<p class="text-xs text-[var(--netz-text-muted)]">
									{asset.asset_type} | {asset.strategy}
								</p>
							</div>
							<Button size="sm" variant="outline" onclick={() => openObligationDialog(asset.id)}>
								Add Obligation
							</Button>
						</Card>
					{/each}
				</div>
			{/if}

		{:else if activeTab === "obligations"}
			{#if obligations.length === 0}
				<EmptyState title="No Obligations" description="Obligation tracking for portfolio assets." />
			{:else}
				<div class="space-y-3">
					{#each obligations as ob (ob.id)}
						<Card class="flex items-center justify-between p-4">
							<div>
								<p class="text-sm font-medium text-[var(--netz-text-primary)]">{ob.obligation_type}</p>
								<p class="text-xs text-[var(--netz-text-muted)]">
									Due: {ob.due_date} | <StatusBadge status={ob.status} type="default" />
								</p>
							</div>
							{#if ob.status === "OPEN" || ob.status === "OVERDUE"}
								<div class="flex gap-2">
									<ActionButton
										size="sm"
										onclick={() => updateObligationStatus(ob.id, "FULFILLED")}
										loading={updatingObligationId === ob.id}
										loadingText="..."
									>
										Fulfill
									</ActionButton>
									<ActionButton
										size="sm"
										variant="outline"
										onclick={() => confirmWaive(ob.id)}
										loading={updatingObligationId === ob.id}
										loadingText="..."
									>
										Waive
									</ActionButton>
								</div>
							{/if}
						</Card>
					{/each}
				</div>
			{/if}

		{:else if activeTab === "alerts"}
			{#if alerts.length === 0}
				<EmptyState title="No Alerts" description="Portfolio alerts will appear here." />
			{:else}
				<DataTable data={alerts} columns={alertColumns} />
			{/if}

		{:else if activeTab === "actions"}
			{#if actions.length === 0}
				<EmptyState title="No Actions" description="Action items will appear here." />
			{:else}
				<div class="space-y-3">
					{#each actions as action (action.id)}
						<Card class="flex items-center justify-between p-4">
							<div>
								<p class="text-sm font-medium text-[var(--netz-text-primary)]">{action.title}</p>
								<p class="text-xs text-[var(--netz-text-muted)]">
									<StatusBadge status={action.status} type="default" />
									{#if action.evidence_notes}
										| {action.evidence_notes}
									{/if}
								</p>
							</div>
							{#if action.status !== "CLOSED"}
								<div class="flex gap-2">
									{#if action.status === "OPEN"}
										<ActionButton
											size="sm"
											variant="outline"
											onclick={() => updateActionStatus(action.id, "IN_PROGRESS")}
											loading={updatingActionId === action.id}
											loadingText="..."
										>
											Start
										</ActionButton>
									{/if}
									<ActionButton
										size="sm"
										onclick={() => updateActionStatus(action.id, "CLOSED")}
										loading={updatingActionId === action.id}
										loadingText="..."
									>
										Close
									</ActionButton>
								</div>
							{/if}
						</Card>
					{/each}
				</div>
			{/if}
		{/if}
	</div>
</div>

<!-- Create Asset Dialog -->
<Dialog bind:open={showCreateAsset} title="Add Portfolio Asset">
	<form onsubmit={(e) => { e.preventDefault(); createAsset(); }} class="space-y-4">
		<FormField label="Asset Name" required>
			<input
				type="text"
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={assetForm.name}
				placeholder="e.g. Acme Corp Senior Secured Loan"
			/>
		</FormField>

		<FormField label="Asset Type" required>
			<select
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={assetForm.asset_type}
			>
				<option value="DIRECT_LOAN">Direct Loan</option>
				<option value="FUND_INVESTMENT">Fund Investment</option>
				<option value="EQUITY_STAKE">Equity Stake</option>
				<option value="SPV_NOTE">SPV Note</option>
			</select>
		</FormField>

		<FormField label="Strategy" required>
			<select
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={assetForm.strategy}
			>
				<option value="CORE_DIRECT_LENDING">Core Direct Lending</option>
				<option value="OPPORTUNISTIC">Opportunistic</option>
				<option value="DISTRESSED">Distressed</option>
				<option value="VENTURE_DEBT">Venture Debt</option>
				<option value="FUND_OF_FUNDS">Fund of Funds</option>
			</select>
		</FormField>

		{#if actionError}
			<p class="text-sm text-[var(--netz-status-error)]">{actionError}</p>
		{/if}

		<div class="flex justify-end gap-2 pt-2">
			<Button variant="outline" onclick={() => showCreateAsset = false}>Cancel</Button>
			<ActionButton onclick={createAsset} loading={savingAsset} loadingText="Creating..." disabled={!assetNameValid}>
				Create Asset
			</ActionButton>
		</div>
	</form>
</Dialog>

<!-- Create Obligation Dialog -->
<Dialog bind:open={showCreateObligation} title="Add Obligation">
	<form onsubmit={(e) => { e.preventDefault(); createObligation(); }} class="space-y-4">
		<FormField label="Obligation Type" required>
			<select
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={obligationForm.obligation_type}
			>
				<option value="NAV_REPORT">NAV Report</option>
				<option value="COVENANT_TEST">Covenant Test</option>
				<option value="FINANCIAL_STATEMENT">Financial Statement</option>
				<option value="AUDIT_REPORT">Audit Report</option>
				<option value="COMPLIANCE_CERT">Compliance Certificate</option>
			</select>
		</FormField>

		<FormField label="Due Date" required>
			<input
				type="date"
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={obligationForm.due_date}
			/>
		</FormField>

		{#if actionError}
			<p class="text-sm text-[var(--netz-status-error)]">{actionError}</p>
		{/if}

		<div class="flex justify-end gap-2 pt-2">
			<Button variant="outline" onclick={() => showCreateObligation = false}>Cancel</Button>
			<ActionButton
				onclick={createObligation}
				loading={savingObligation}
				loadingText="Creating..."
				disabled={!obligationForm.due_date}
			>
				Create Obligation
			</ActionButton>
		</div>
	</form>
</Dialog>

<!-- Waive Obligation Confirmation -->
<ConfirmDialog
	bind:open={showWaiveConfirm}
	title="Waive Obligation"
	message="Waiving an obligation is a significant business decision and will be recorded in the audit trail. Continue?"
	confirmLabel="Waive"
	confirmVariant="destructive"
	onConfirm={executeWaive}
	onCancel={() => { showWaiveConfirm = false; waiveTargetId = null; }}
/>
