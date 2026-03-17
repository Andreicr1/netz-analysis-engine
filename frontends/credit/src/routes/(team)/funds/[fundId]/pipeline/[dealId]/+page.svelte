<!--
  Deal detail — tabs: Overview, IC Memo, Documents, Compliance.
  IC Memo tab uses SSE for streaming chapter content.
  Overview tab shows deal actions (decide, resolve conditions, convert).
-->
<script lang="ts">
	import { PageTabs, Card, StatusBadge, Button, EmptyState, Dialog } from "@netz/ui";
	import { ActionButton, ConfirmDialog, FormField } from "@netz/ui";
	import DealStageTimeline from "$lib/components/DealStageTimeline.svelte";
	import ICMemoViewer from "$lib/components/ICMemoViewer.svelte";
	import { goto, invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { DealStage, RejectionCode, ICCondition, StageTimeline, VotingStatusDetail } from "$lib/types/api";
	import { VALID_TRANSITIONS } from "$lib/types/api";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();
	let activeTab = $state("overview");

	// ── Deal Actions State ──
	let saving = $state(false);
	let actionError = $state<string | null>(null);

	// Stage timeline data (typed)
	let timeline = $derived(data.stageTimeline as StageTimeline | null);
	let allowedTransitions = $derived(timeline?.allowedTransitions ?? []);
	let currentStage = $derived((data.deal.stage as DealStage) ?? "INTAKE");

	// ── Decision Dialog ──
	let showDecision = $state(false);
	let decisionTarget = $state<DealStage | null>(null);
	let decisionNotes = $state("");
	let rejectionCode = $state<RejectionCode>("OUT_OF_MANDATE");

	function openDecision(stage: DealStage) {
		decisionTarget = stage;
		decisionNotes = "";
		rejectionCode = "OUT_OF_MANDATE";
		actionError = null;
		showDecision = true;
	}

	async function submitDecision() {
		if (!decisionTarget) return;
		saving = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.patch(`/funds/${data.fundId}/deals/${data.dealId}/decision`, {
				stage: decisionTarget,
				...(decisionTarget === "REJECTED" ? {
					rejection_code: rejectionCode,
					rejection_notes: decisionNotes || null,
				} : {}),
			});
			showDecision = false;
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Decision failed";
		} finally {
			saving = false;
		}
	}

	// ── Convert Dialog ──
	let showConvert = $state(false);
	let convertConfirmName = $state("");
	let canConvert = $derived(
		convertConfirmName.trim().toLowerCase() === (data.deal.name as string ?? "").trim().toLowerCase()
	);

	async function convertDeal() {
		saving = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/deals/${data.dealId}/convert`, {});
			showConvert = false;
			await goto(`/funds/${data.fundId}/portfolio`);
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Conversion failed";
		} finally {
			saving = false;
		}
	}

	// ── IC Condition Resolution ──
	let conditionSaving = $state<Set<string>>(new Set());
	let votingData = $derived(data.votingStatus as VotingStatusDetail | null);
	let conditions = $derived(votingData?.conditions?.items ?? []);

	async function resolveCondition(conditionId: string, status: "resolved" | "waived") {
		conditionSaving = new Set([...conditionSaving, conditionId]);
		try {
			const api = createClientApiClient(getToken);
			await api.patch(`/funds/${data.fundId}/deals/${data.dealId}/ic-memo/conditions`, {
				condition_id: conditionId,
				status,
				evidence_docs: [],
				notes: null,
			});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to resolve condition";
		} finally {
			const next = new Set(conditionSaving);
			next.delete(conditionId);
			conditionSaving = next;
		}
	}

	// ── Stage action labels ──
	const stageLabels: Record<string, string> = {
		QUALIFIED: "Advance to Qualified",
		IC_REVIEW: "Send to IC Review",
		APPROVED: "Approve",
		CONDITIONAL: "Approve with Conditions",
		CONVERTED_TO_ASSET: "Convert to Asset",
		REJECTED: "Reject",
		CLOSED: "Close",
	};
</script>

<div class="p-6">
	<div class="mb-4 flex items-center justify-between">
		<div>
			<h2 class="text-xl font-semibold text-[var(--netz-text-primary)]">
				{data.deal.name ?? "Deal"}
			</h2>
			<div class="mt-1 flex items-center gap-2">
				<StatusBadge status={String(data.deal.stage)} type="deal" />
				{#if data.deal.deal_type}
					<span class="text-sm text-[var(--netz-text-muted)]">{data.deal.deal_type}</span>
				{/if}
				{#if data.deal.sponsor_name}
					<span class="text-sm text-[var(--netz-text-muted)]">| {data.deal.sponsor_name}</span>
				{/if}
			</div>
		</div>

		<!-- Action buttons based on allowed transitions -->
		{#if allowedTransitions.length > 0}
			<div class="flex gap-2">
				{#each allowedTransitions as transition}
					{#if transition === "CONVERTED_TO_ASSET"}
						<Button
							variant="default"
							onclick={() => { convertConfirmName = ""; actionError = null; showConvert = true; }}
						>
							Convert to Asset
						</Button>
					{:else if transition === "REJECTED"}
						<Button variant="destructive" onclick={() => openDecision(transition)}>
							Reject
						</Button>
					{:else}
						<Button onclick={() => openDecision(transition)}>
							{stageLabels[transition] ?? transition}
						</Button>
					{/if}
				{/each}
			</div>
		{/if}
	</div>

	{#if actionError}
		<div class="mb-4 rounded-md border border-[var(--netz-status-error)] bg-[var(--netz-status-error)]/10 p-3 text-sm text-[var(--netz-status-error)]">
			{actionError}
		</div>
	{/if}

	{#if timeline}
		<div class="mb-6">
			<DealStageTimeline timeline={timeline.nodes as import("$lib/types/api").StageTimelineEntry[]} />
		</div>
	{/if}

	<PageTabs
		tabs={[
			{ id: "overview", label: "Overview" },
			{ id: "conditions", label: `Conditions${conditions.length > 0 ? ` (${conditions.length})` : ""}` },
			{ id: "ic-memo", label: "IC Memo" },
			{ id: "documents", label: "Documents" },
		]}
		active={activeTab}
		onChange={(tab) => activeTab = tab}
	/>

	<div class="mt-4">
		{#if activeTab === "overview"}
			<Card class="p-6">
				<h3 class="mb-4 text-lg font-semibold">Deal Overview</h3>
				<div class="grid gap-4 md:grid-cols-2">
					<div>
						<p class="text-xs text-[var(--netz-text-muted)]">Borrower / Sponsor</p>
						<p class="text-sm font-medium">{data.deal.sponsor_name ?? "—"}</p>
					</div>
					<div>
						<p class="text-xs text-[var(--netz-text-muted)]">Deal Type</p>
						<p class="text-sm font-medium">{data.deal.deal_type ?? "—"}</p>
					</div>
					<div>
						<p class="text-xs text-[var(--netz-text-muted)]">Description</p>
						<p class="text-sm font-medium">{data.deal.description ?? "—"}</p>
					</div>
					<div>
						<p class="text-xs text-[var(--netz-text-muted)]">Created</p>
						<p class="text-sm font-medium">{data.deal.created_at ?? "—"}</p>
					</div>
					{#if data.deal.rejection_code}
						<div>
							<p class="text-xs text-[var(--netz-text-muted)]">Rejection Code</p>
							<p class="text-sm font-medium text-[var(--netz-status-error)]">{data.deal.rejection_code}</p>
						</div>
						<div>
							<p class="text-xs text-[var(--netz-text-muted)]">Rejection Notes</p>
							<p class="text-sm font-medium text-[var(--netz-status-error)]">{data.deal.rejection_notes ?? "—"}</p>
						</div>
					{/if}
					{#if data.deal.asset_id}
						<div>
							<p class="text-xs text-[var(--netz-text-muted)]">Converted Asset</p>
							<Button variant="link" href="/funds/{data.fundId}/portfolio">
								View in Portfolio
							</Button>
						</div>
					{/if}
				</div>
			</Card>

		{:else if activeTab === "conditions"}
			{#if conditions.length === 0}
				<EmptyState
					title="No Conditions"
					description="IC conditions will appear here when the deal is approved with conditions."
				/>
			{:else}
				<Card class="p-6">
					<h3 class="mb-4 text-lg font-semibold">IC Conditions</h3>
					<div class="space-y-3">
						{#each conditions as condition (condition.id)}
							<div class="flex items-start justify-between rounded-lg border border-[var(--netz-border)] p-4">
								<div class="flex-1">
									<p class="text-sm font-medium text-[var(--netz-text-primary)]">
										{condition.title}
									</p>
									<p class="mt-1 text-xs text-[var(--netz-text-muted)]">
										Status: <StatusBadge status={condition.status} type="default" />
									</p>
									{#if condition.notes}
										<p class="mt-1 text-xs text-[var(--netz-text-muted)]">{condition.notes}</p>
									{/if}
								</div>
								{#if condition.status === "open"}
									<div class="ml-4 flex gap-2">
										<ActionButton
											onclick={() => resolveCondition(condition.id, "resolved")}
											loading={conditionSaving.has(condition.id)}
											loadingText="..."
											size="sm"
										>
											Resolve
										</ActionButton>
										<ActionButton
											variant="outline"
											onclick={() => resolveCondition(condition.id, "waived")}
											loading={conditionSaving.has(condition.id)}
											loadingText="..."
											size="sm"
										>
											Waive
										</ActionButton>
									</div>
								{/if}
							</div>
						{/each}
					</div>
				</Card>
			{/if}

		{:else if activeTab === "ic-memo"}
			<ICMemoViewer
				icMemo={data.icMemo}
				votingStatus={data.votingStatus}
				fundId={data.fundId}
				dealId={data.dealId}
			/>

		{:else if activeTab === "documents"}
			<EmptyState
				title="Deal Documents"
				description="Evidence and supporting documents for this deal."
			/>
		{/if}
	</div>
</div>

<!-- Decision Dialog -->
<Dialog bind:open={showDecision} title={decisionTarget === "REJECTED" ? "Reject Deal" : (stageLabels[decisionTarget ?? ""] ?? "Decide")}>
	<div class="space-y-4">
		{#if decisionTarget === "REJECTED"}
			<FormField label="Rejection Code" required>
				<select
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
					bind:value={rejectionCode}
				>
					<option value="OUT_OF_MANDATE">Out of Mandate</option>
					<option value="TICKET_TOO_SMALL">Ticket Too Small</option>
					<option value="JURISDICTION_EXCLUDED">Jurisdiction Excluded</option>
					<option value="INSUFFICIENT_RETURN">Insufficient Return</option>
					<option value="WEAK_CREDIT_PROFILE">Weak Credit Profile</option>
					<option value="NO_COLLATERAL">No Collateral</option>
				</select>
			</FormField>
			<FormField label="Rejection Notes">
				<textarea
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
					bind:value={decisionNotes}
					rows={3}
					placeholder="Reason for rejection..."
				></textarea>
			</FormField>
		{:else}
			<p class="text-sm text-[var(--netz-text-secondary)]">
				Move this deal to <strong>{decisionTarget}</strong>? This action will be recorded in the audit trail.
			</p>
		{/if}

		{#if actionError}
			<p class="text-sm text-[var(--netz-status-error)]">{actionError}</p>
		{/if}

		<div class="flex justify-end gap-2 pt-2">
			<Button variant="outline" onclick={() => showDecision = false}>Cancel</Button>
			<ActionButton
				onclick={submitDecision}
				loading={saving}
				loadingText="Saving..."
				variant={decisionTarget === "REJECTED" ? "destructive" : "default"}
			>
				{decisionTarget === "REJECTED" ? "Reject Deal" : "Confirm"}
			</ActionButton>
		</div>
	</div>
</Dialog>

<!-- Convert to Asset Dialog (double-confirmation) -->
<Dialog bind:open={showConvert} title="Convert Deal to Portfolio Asset">
	<div class="space-y-4">
		<p class="text-sm text-[var(--netz-text-secondary)]">
			This is an <strong>irreversible</strong> operation. The deal will be converted to a portfolio asset.
		</p>
		<FormField label="Type the deal name to confirm" required>
			<input
				type="text"
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
				bind:value={convertConfirmName}
				placeholder={String(data.deal.name)}
			/>
		</FormField>

		{#if actionError}
			<p class="text-sm text-[var(--netz-status-error)]">{actionError}</p>
		{/if}

		<div class="flex justify-end gap-2 pt-2">
			<Button variant="outline" onclick={() => showConvert = false}>Cancel</Button>
			<ActionButton
				onclick={convertDeal}
				loading={saving}
				loadingText="Converting..."
				disabled={!canConvert}
				variant="destructive"
			>
				Convert to Asset
			</ActionButton>
		</div>
	</div>
</Dialog>
