<!--
  Pipeline list — DataTable with deal columns, click row for ContextPanel.
  New Deal dialog for creating deals.
-->
<script lang="ts">
	import { DataTable, StatusBadge, ContextPanel, EmptyState, Button, Dialog, PageHeader, Skeleton, Select } from "@netz/ui";
	import { ActionButton, FormField } from "@netz/ui";
	import { goto, invalidateAll } from "$app/navigation";
	import { page } from "$app/state";
	import { getContext } from "svelte";
	import { createClientApiClient } from "$lib/api/client";
	import PipelineKanban from "$lib/components/PipelineKanban.svelte";
	import type { PageData } from "./$types";
	import type { DealStage, DealType } from "$lib/types/api";
	import { resolveCreditStatus } from "$lib/utils/status-maps";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let viewMode = $state<"list" | "kanban">("list");
	let selectedDeal = $state<Record<string, unknown> | null>(null);
	let panelOpen = $derived(selectedDeal !== null);
	let activeStage = $derived<DealStage | "ALL">(
		(page.url.searchParams.get("stage") as DealStage) ?? "ALL"
	);
	const stageFilters: Array<{ value: DealStage | "ALL"; label: string }> = [
		{ value: "ALL", label: "All stages" },
		{ value: "INTAKE", label: "Intake" },
		{ value: "QUALIFIED", label: "Qualified" },
		{ value: "IC_REVIEW", label: "IC review" },
		{ value: "CONDITIONAL", label: "Conditional" },
		{ value: "APPROVED", label: "Approved" },
		{ value: "CONVERTED_TO_ASSET", label: "Converted" },
		{ value: "REJECTED", label: "Rejected" },
		{ value: "CLOSED", label: "Closed" },
	];

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

	const stageLabels: Record<string, string> = {
		INTAKE: "Intake",
		QUALIFIED: "Qualified",
		IC_REVIEW: "IC Review",
		CONDITIONAL: "Conditional",
		APPROVED: "Approved",
		CONVERTED_TO_ASSET: "Converted",
		REJECTED: "Rejected",
		CLOSED: "Closed",
	};

	const dealTypeLabels: Record<string, string> = {
		DIRECT_LOAN: "Direct Loan",
		FUND_INVESTMENT: "Fund Investment",
		EQUITY_STAKE: "Equity Stake",
		SPV_NOTE: "SPV Note",
	};

	function humanizeEnum(value: string, labels: Record<string, string>): string {
		return labels[value] ?? value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}

	const columns = [
		{ accessorKey: "name", header: "Deal Name" },
		{ accessorKey: "stage", header: "Stage", cell: (info: { getValue: () => string }) => humanizeEnum(info.getValue(), stageLabels) },
		{ accessorKey: "deal_type", header: "Type", cell: (info: { getValue: () => string }) => humanizeEnum(info.getValue(), dealTypeLabels) },
		{ accessorKey: "sponsor_name", header: "Sponsor" },
		{ accessorKey: "created_at", header: "Created" },
	];

	function handleRowClick(row: Record<string, unknown>) {
		selectedDeal = row;
	}

	function selectStageFilter(stage: DealStage | "ALL") {
		goto(
			stage === "ALL"
				? `/funds/${data.fundId}/pipeline`
				: `/funds/${data.fundId}/pipeline?stage=${encodeURIComponent(stage)}`,
		);
	}
</script>

<div class="flex h-full">
	<div class="flex-1 px-6">
		<PageHeader
			title="Deal Pipeline"
			breadcrumbs={[{ label: "Funds", href: "/funds" }, { label: "Pipeline" }]}
		>
			{#snippet actions()}
				<div class="flex items-center gap-3">
					<div class="flex rounded-md border border-(--netz-border)" role="group" aria-label="View mode">
						<button
							class="px-3 py-1 text-xs font-medium transition-colors {viewMode === 'list'
								? 'bg-(--netz-brand-primary) text-white'
								: 'bg-(--netz-surface) text-(--netz-text-secondary) hover:bg-(--netz-surface-alt)'} rounded-l-md"
							onclick={() => (viewMode = "list")}
							aria-label="List view"
							aria-pressed={viewMode === "list"}
						>
							List
						</button>
						<button
							class="px-3 py-1 text-xs font-medium transition-colors {viewMode === 'kanban'
								? 'bg-(--netz-brand-primary) text-white'
								: 'bg-(--netz-surface) text-(--netz-text-secondary) hover:bg-(--netz-surface-alt)'} rounded-r-md"
							onclick={() => (viewMode = "kanban")}
							aria-label="Kanban view"
							aria-pressed={viewMode === "kanban"}
						>
							Kanban
						</button>
					</div>
					<Button onclick={() => { resetForm(); showCreate = true; }}>New Deal</Button>
				</div>
			{/snippet}
		</PageHeader>

		{#if viewMode === "list"}
			<div class="mb-4 flex flex-wrap gap-2">
				{#each stageFilters as stage}
					<Button
						onclick={() => selectStageFilter(stage.value)}
						size="sm"
						variant={activeStage === stage.value ? "default" : "outline"}
					>
						{stage.label}
					</Button>
				{/each}
			</div>
		{/if}

		{#if !data.deals}
			<div class="space-y-3">
				{#each Array(6) as _}
					<Skeleton class="h-12 rounded-lg" />
				{/each}
			</div>
		{:else if data.deals.items.length === 0}
			<EmptyState
				title="No Deals"
				description="Create your first deal to get started with the pipeline."
			/>
		{:else if viewMode === "list"}
			<DataTable
				data={data.deals.items}
				{columns}
				onRowClick={handleRowClick}
			/>
		{:else}
			<PipelineKanban deals={data.deals.items} fundId={data.fundId} {getToken} />
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
					<p class="text-xs text-(--netz-text-muted)">Stage</p>
					<StatusBadge status={String(selectedDeal.stage)} type="deal" resolve={resolveCreditStatus} />
				</div>
				<div>
					<p class="text-xs text-(--netz-text-muted)">Type</p>
					<p class="text-sm">{selectedDeal.deal_type ?? "—"}</p>
				</div>
				<div>
					<p class="text-xs text-(--netz-text-muted)">Sponsor</p>
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
				class="w-full rounded-md border border-(--netz-border) bg-(--netz-surface) px-3 py-2 text-sm text-(--netz-text-primary) outline-none focus:border-(--netz-brand-primary)"
				bind:value={form.name}
				onblur={() => touched.name = true}
				placeholder="e.g. Acme Corp Senior Secured"
			/>
		</FormField>

		<FormField label="Deal Type" required>
			<Select
				bind:value={form.deal_type}
				options={[
					{ value: "DIRECT_LOAN", label: "Direct Loan" },
					{ value: "FUND_INVESTMENT", label: "Fund Investment" },
					{ value: "EQUITY_STAKE", label: "Equity Stake" },
					{ value: "SPV_NOTE", label: "SPV Note" },
				]}
			/>
		</FormField>

		<FormField label="Sponsor Name">
			<input
				type="text"
				class="w-full rounded-md border border-(--netz-border) bg-(--netz-surface) px-3 py-2 text-sm text-(--netz-text-primary) outline-none focus:border-(--netz-brand-primary)"
				bind:value={form.sponsor_name}
				placeholder="Optional"
			/>
		</FormField>

		<FormField label="Description">
			<textarea
				class="w-full rounded-md border border-(--netz-border) bg-(--netz-surface) px-3 py-2 text-sm text-(--netz-text-primary) outline-none focus:border-(--netz-brand-primary)"
				bind:value={form.description}
				rows={3}
				placeholder="Optional deal description"
			></textarea>
		</FormField>

		{#if createError}
			<p class="text-sm text-(--netz-status-error)">{createError}</p>
		{/if}

		<div class="flex justify-end gap-2 pt-2">
			<Button variant="outline" onclick={() => showCreate = false}>Cancel</Button>
			<ActionButton onclick={createDeal} loading={saving} loadingText="Creating..." disabled={!canSubmit}>
				Create Deal
			</ActionButton>
		</div>
	</form>
</Dialog>
