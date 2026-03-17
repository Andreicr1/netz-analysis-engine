<!--
  Pipeline list — DataTable with deal columns, click row for ContextPanel.
  New Deal dialog for creating deals.
-->
<script lang="ts">
	import { DataTable, StatusBadge, ContextPanel, EmptyState, Button, Dialog } from "@netz/ui";
	import { ActionButton, ConfirmDialog, FormField } from "@netz/ui";
	import { goto, invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { DealType } from "$lib/types/api";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let selectedDeal = $state<Record<string, unknown> | null>(null);
	let panelOpen = $derived(selectedDeal !== null);

	// ── Create Deal Dialog ──
	let showCreate = $state(false);
	let saving = $state(false);
	let createError = $state<string | null>(null);

	let form = $state({
		name: "",
		deal_type: "DIRECT_LOAN" as DealType,
		sponsor_name: "",
		description: "",
	});

	let touched = $state({ name: false });
	let nameError = $derived(touched.name && form.name.trim().length < 2 ? "Name must be at least 2 characters" : null);
	let canSubmit = $derived(form.name.trim().length >= 2 && !saving);

	function resetForm() {
		form = { name: "", deal_type: "DIRECT_LOAN", sponsor_name: "", description: "" };
		touched = { name: false };
		createError = null;
	}

	async function createDeal() {
		saving = true;
		createError = null;
		try {
			const api = createClientApiClient(getToken);
			const deal = await api.post<{ id: string }>(`/funds/${data.fundId}/deals`, {
				name: form.name.trim(),
				deal_type: form.deal_type,
				sponsor_name: form.sponsor_name.trim() || null,
				description: form.description.trim() || null,
			});
			showCreate = false;
			resetForm();
			await goto(`/funds/${data.fundId}/pipeline/${deal.id}`);
		} catch (e) {
			createError = e instanceof Error ? e.message : "Failed to create deal";
		} finally {
			saving = false;
		}
	}

	const columns = [
		{ accessorKey: "name", header: "Deal Name" },
		{ accessorKey: "stage", header: "Stage", cell: (info: { getValue: () => string }) => info.getValue() },
		{ accessorKey: "deal_type", header: "Type" },
		{ accessorKey: "sponsor_name", header: "Sponsor" },
		{ accessorKey: "created_at", header: "Created" },
	];

	function handleRowClick(row: Record<string, unknown>) {
		selectedDeal = row;
	}
</script>

<div class="flex h-full">
	<div class="flex-1 p-6">
		<div class="mb-4 flex items-center justify-between">
			<h2 class="text-xl font-semibold text-[var(--netz-text-primary)]">Deal Pipeline</h2>
			<Button onclick={() => { resetForm(); showCreate = true; }}>New Deal</Button>
		</div>

		{#if data.deals.items.length === 0}
			<EmptyState
				title="No Deals"
				description="Create your first deal to get started with the pipeline."
			/>
		{:else}
			<DataTable
				data={data.deals.items}
				{columns}
				onRowClick={handleRowClick}
			/>
		{/if}
	</div>

	<!-- Context panel for quick deal summary -->
	{#if selectedDeal}
		<ContextPanel
			open={panelOpen}
			title={String(selectedDeal.name ?? "Deal")}
			onClose={() => selectedDeal = null}
		>
			<div class="space-y-4 p-4">
				<div>
					<p class="text-xs text-[var(--netz-text-muted)]">Stage</p>
					<StatusBadge status={String(selectedDeal.stage)} type="deal" />
				</div>
				<div>
					<p class="text-xs text-[var(--netz-text-muted)]">Type</p>
					<p class="text-sm">{selectedDeal.deal_type ?? "—"}</p>
				</div>
				<div>
					<p class="text-xs text-[var(--netz-text-muted)]">Sponsor</p>
					<p class="text-sm">{selectedDeal.sponsor_name ?? "—"}</p>
				</div>
				<div class="flex gap-2 pt-2">
					<Button href="/funds/{data.fundId}/pipeline/{selectedDeal.id}" class="flex-1">
						Open Deal
					</Button>
				</div>
			</div>
		</ContextPanel>
	{/if}
</div>

<!-- Create Deal Dialog -->
<Dialog bind:open={showCreate} title="New Deal">
	<form onsubmit={(e) => { e.preventDefault(); createDeal(); }} class="space-y-4">
		<FormField label="Deal Name" error={nameError} required>
			<input
				type="text"
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={form.name}
				onblur={() => touched.name = true}
				placeholder="e.g. Acme Corp Senior Secured"
			/>
		</FormField>

		<FormField label="Deal Type" required>
			<select
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={form.deal_type}
			>
				<option value="DIRECT_LOAN">Direct Loan</option>
				<option value="FUND_INVESTMENT">Fund Investment</option>
				<option value="EQUITY_STAKE">Equity Stake</option>
				<option value="SPV_NOTE">SPV Note</option>
			</select>
		</FormField>

		<FormField label="Sponsor Name">
			<input
				type="text"
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={form.sponsor_name}
				placeholder="Optional"
			/>
		</FormField>

		<FormField label="Description">
			<textarea
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={form.description}
				rows={3}
				placeholder="Optional deal description"
			></textarea>
		</FormField>

		{#if createError}
			<p class="text-sm text-[var(--netz-status-error)]">{createError}</p>
		{/if}

		<div class="flex justify-end gap-2 pt-2">
			<Button variant="outline" onclick={() => showCreate = false}>Cancel</Button>
			<ActionButton onclick={createDeal} loading={saving} loadingText="Creating..." disabled={!canSubmit}>
				Create Deal
			</ActionButton>
		</div>
	</form>
</Dialog>
