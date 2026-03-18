<!--
  Deal detail — tabs: Overview, IC Memo, Documents, Compliance.
  IC Memo tab uses SSE for streaming chapter content.
  Overview tab shows deal actions (decide, resolve conditions, convert).
-->
<script lang="ts">
	import { PageTabs, Card, StatusBadge, Button, EmptyState, MetricCard } from "@netz/ui";
	import { ActionButton, FormField } from "@netz/ui";
	import { ConsequenceDialog, AuditTrailPanel } from "@netz/ui";
	import { createOptimisticMutation } from "@netz/ui";
	import type { AuditTrailEntry } from "@netz/ui";
	import { formatNumber, formatBps, formatRatio } from "@netz/ui";
	import DealStageTimeline from "$lib/components/DealStageTimeline.svelte";
	import ICMemoViewer from "$lib/components/ICMemoViewer.svelte";
	import { goto, invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { DealStage, RejectionCode, ICCondition, StageTimeline, VotingStatusDetail } from "$lib/types/api";

	/** Matches components["schemas"]["DealDecision"] from packages/ui/src/types/api.d.ts */
	interface DealDecisionPayload {
		stage: string;
		rationale: string;
		actor_capacity: string;
		actor_email: string;
		rejection_code?: string | null;
		rejection_notes?: string | null;
	}

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();
	let activeTab = $state("overview");

	// ── Deal Actions State ──
	let actionError = $state<string | null>(null);

	// Stage timeline data (typed)
	let timeline = $derived(data.stageTimeline as StageTimeline | null);
	let allowedTransitions = $derived(timeline?.allowedTransitions ?? []);
	let currentStage = $derived((data.deal.stage as DealStage) ?? "INTAKE");

	// ── Audit Trail ──
	let auditEntries = $state<AuditTrailEntry[]>([]);

	const auditMutation = createOptimisticMutation<AuditTrailEntry[]>({
		getState: () => auditEntries,
		setState: (value) => { auditEntries = value; },
		request: async (optimisticValue, _previousValue) => optimisticValue,
	});

	function appendOptimisticAuditEntry(entry: AuditTrailEntry) {
		const optimistic: AuditTrailEntry = { ...entry, status: "pending" };
		auditMutation.mutate([...auditEntries, optimistic]).catch(() => {});
	}

	function confirmAuditEntry(index: number, confirmed: Partial<AuditTrailEntry>) {
		auditEntries = auditEntries.map((e, i) =>
			i === index ? { ...e, ...confirmed, status: "success", immutable: true } : e,
		);
	}

	// ── Decision Dialog ──
	let showDecision = $state(false);
	let decisionTarget = $state<DealStage | null>(null);
	let rejectionCode = $state<RejectionCode>("OUT_OF_MANDATE");
	let decisionActorCapacity = $state("");

	function openDecision(stage: DealStage) {
		decisionTarget = stage;
		rejectionCode = "OUT_OF_MANDATE";
		decisionActorCapacity = "";
		actionError = null;
		showDecision = true;
	}

	async function submitDecision(payload: { rationale?: string }) {
		if (!decisionTarget) return;
		if (!decisionActorCapacity.trim()) {
			actionError = "Actor capacity is required before submitting a decision.";
			throw new Error(actionError);
		}

		const rationale = payload.rationale ?? "";
		const isRejection = decisionTarget === "REJECTED";
		const outcomeLabel = stageLabels[decisionTarget] ?? decisionTarget;
		const pendingIndex = auditEntries.length;

		appendOptimisticAuditEntry({
			actor: "You",
			actorCapacity: decisionActorCapacity || undefined,
			timestamp: new Date().toISOString(),
			action: outcomeLabel,
			scope: `Deal: ${String(data.deal.name ?? "")}`,
			rationale,
			outcome: "Pending",
		});

		try {
			const api = createClientApiClient(getToken);
			const body: DealDecisionPayload = {
				stage: decisionTarget,
				rationale,
				actor_capacity: decisionActorCapacity,
				actor_email: "",
				...(isRejection ? {
					rejection_code: rejectionCode,
					rejection_notes: null,
				} : {}),
			};
			await api.patch(`/funds/${data.fundId}/deals/${data.dealId}/decision`, body);
			showDecision = false;
			confirmAuditEntry(pendingIndex, { outcome: outcomeLabel, status: "success", immutable: true });
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Decision failed";
			auditEntries = auditEntries.filter((_, i) => i !== pendingIndex);
		}
	}

	// ── Convert Dialog ──
	let showConvert = $state(false);
	let convertActorCapacity = $state("");

	async function convertDeal(payload: { rationale?: string }) {
		if (!convertActorCapacity.trim()) {
			actionError = "Actor capacity is required before converting a deal.";
			throw new Error(actionError);
		}
		const rationale = payload.rationale ?? "";
		const pendingIndex = auditEntries.length;

		appendOptimisticAuditEntry({
			actor: "You",
			actorCapacity: convertActorCapacity || undefined,
			timestamp: new Date().toISOString(),
			action: "Convert to Asset",
			scope: `Deal: ${String(data.deal.name ?? "")}`,
			rationale,
			outcome: "Pending",
		});

		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/deals/${data.dealId}/convert`, {});
			showConvert = false;
			confirmAuditEntry(pendingIndex, { outcome: "Converted", status: "success", immutable: true });
			await goto(`/funds/${data.fundId}/portfolio`);
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Conversion failed";
			auditEntries = auditEntries.filter((_, i) => i !== pendingIndex);
		}
	}

	// ── IC Condition Resolution ──
	let conditionSaving = $state<Set<string>>(new Set());
	let showConditionDialog = $state(false);
	let pendingCondition = $state<{ id: string; status: "resolved" | "waived" } | null>(null);
	let conditionActorCapacity = $state("");
	let votingData = $derived(data.votingStatus as VotingStatusDetail | null);
	let conditions = $derived(votingData?.conditions?.items ?? []);

	function openConditionDialog(conditionId: string, status: "resolved" | "waived") {
		pendingCondition = { id: conditionId, status };
		conditionActorCapacity = "";
		actionError = null;
		showConditionDialog = true;
	}

	async function submitConditionResolution(payload: { rationale?: string }) {
		if (!pendingCondition) return;
		if (!conditionActorCapacity.trim()) {
			actionError = "Actor capacity is required before resolving a condition.";
			throw new Error(actionError);
		}

		const { id: conditionId, status } = pendingCondition;
		const rationale = payload.rationale ?? "";
		const outcomeLabel = status === "resolved" ? "Condition Resolved" : "Condition Waived";
		const condition = conditions.find((c) => c.id === conditionId);
		const pendingIndex = auditEntries.length;

		appendOptimisticAuditEntry({
			actor: "You",
			actorCapacity: conditionActorCapacity || undefined,
			timestamp: new Date().toISOString(),
			action: outcomeLabel,
			scope: `Condition: ${String(condition?.title ?? conditionId)}`,
			rationale,
			outcome: "Pending",
		});

		conditionSaving = new Set([...conditionSaving, conditionId]);
		showConditionDialog = false;

		try {
			const api = createClientApiClient(getToken);
			await api.patch(`/funds/${data.fundId}/deals/${data.dealId}/ic-memo/conditions`, {
				condition_id: conditionId,
				status,
				evidence_docs: [],
				notes: rationale || null,
			});
			confirmAuditEntry(pendingIndex, { outcome: outcomeLabel, status: "success", immutable: true });
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to resolve condition";
			auditEntries = auditEntries.filter((_, i) => i !== pendingIndex);
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

	// ── Derived dialog meta ──
	let decisionIsDestructive = $derived(decisionTarget === "REJECTED" || decisionTarget === "CLOSED");
	let decisionTitle = $derived(decisionTarget === "REJECTED" ? "Reject Deal" : (stageLabels[decisionTarget ?? ""] ?? "Advance Deal"));
	let decisionImpact = $derived(
		decisionTarget === "REJECTED"
			? "This deal will be permanently marked as rejected. The decision and rationale will be recorded in the audit trail."
			: `This deal will advance to the ${decisionTarget} stage. This action will be recorded in the audit trail.`,
	);
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
							onclick={() => { convertActorCapacity = ""; actionError = null; showConvert = true; }}
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
			{ id: "audit", label: "Audit Trail" },
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

			<!-- Financial Terms — fields from app__domains__credit__deals__schemas__deals__DealOut -->
			{#if data.deal.tenor_months != null || data.deal.spread_bps != null || data.deal.ltv_ratio != null || data.deal.covenant_type != null || data.deal.collateral_description != null || data.deal.agreement_language != null}
				<Card class="mt-4 p-6">
					<h3 class="mb-4 text-lg font-semibold">Financial Terms</h3>
					<!-- Numeric KPIs via MetricCard -->
					<div class="mb-4 grid gap-4 md:grid-cols-3">
						<MetricCard
							label="Tenor"
							value={data.deal.tenor_months != null ? formatNumber(Number(data.deal.tenor_months), 0) + " mo" : "—"}
						/>
						<MetricCard
							label="Spread"
							value={data.deal.spread_bps != null ? formatBps(Number(data.deal.spread_bps) / 10_000) : "—"}
						/>
						<MetricCard
							label="LTV Ratio"
							value={data.deal.ltv_ratio != null ? formatRatio(parseFloat(String(data.deal.ltv_ratio))) : "—"}
						/>
					</div>
					<!-- Text fields -->
					<div class="grid gap-4 md:grid-cols-2">
						<div>
							<p class="text-xs text-[var(--netz-text-muted)]">Covenant Type</p>
							<p class="text-sm font-medium">{data.deal.covenant_type ?? "—"}</p>
						</div>
						<div>
							<p class="text-xs text-[var(--netz-text-muted)]">Covenant Frequency</p>
							<p class="text-sm font-medium">{data.deal.covenant_frequency ?? "—"}</p>
						</div>
						<div class="md:col-span-2">
							<p class="text-xs text-[var(--netz-text-muted)]">Collateral Description</p>
							<p class="text-sm font-medium">{data.deal.collateral_description ?? "—"}</p>
						</div>
						<div>
							<p class="text-xs text-[var(--netz-text-muted)]">Agreement Language</p>
							<p class="text-sm font-medium">{data.deal.agreement_language ?? "—"}</p>
						</div>
					</div>
				</Card>
			{/if}

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
											onclick={() => openConditionDialog(condition.id, "resolved")}
											loading={conditionSaving.has(condition.id)}
											loadingText="..."
											size="sm"
										>
											Resolve
										</ActionButton>
										<ActionButton
											variant="outline"
											onclick={() => openConditionDialog(condition.id, "waived")}
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

		{:else if activeTab === "audit"}
			<AuditTrailPanel
				entries={auditEntries}
				title="Decision Audit Trail"
				description="Durable record of all IC decisions, stage transitions, and condition resolutions for this deal."
			/>
		{/if}
	</div>
</div>

<!-- Decision Dialog (ConsequenceDialog) -->
<ConsequenceDialog
	bind:open={showDecision}
	title={decisionTitle}
	impactSummary={decisionImpact}
	destructive={decisionIsDestructive}
	requireRationale={true}
	rationaleLabel="Decision Rationale"
	rationalePlaceholder="Record the investment or policy basis for this IC decision."
	rationaleMinLength={20}
	confirmLabel={decisionTarget === "REJECTED" ? "Reject Deal" : "Confirm Decision"}
	metadata={[
		{ label: "Deal", value: String(data.deal.name ?? "—"), emphasis: true },
		{ label: "Current Stage", value: String(currentStage) },
		{ label: "Target Stage", value: String(decisionTarget ?? "—") },
	]}
	onConfirm={submitDecision}
	onCancel={() => { showDecision = false; }}
>
	{#snippet children()}
		<div class="space-y-4">
			{#if decisionTarget === "REJECTED"}
				<FormField label="Rejection Code" required>
					<select
						class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
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
			{/if}
			<FormField label="Actor Capacity" required>
				<input
					type="text"
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
					bind:value={decisionActorCapacity}
					placeholder="e.g. Investment Committee Member, Partner"
					aria-required="true"
				/>
			</FormField>
			{#if actionError}
				<p class="text-sm text-[var(--netz-status-error)]">{actionError}</p>
			{/if}
		</div>
	{/snippet}
</ConsequenceDialog>

<!-- Convert to Asset Dialog (ConsequenceDialog — destructive, typed confirmation) -->
<ConsequenceDialog
	bind:open={showConvert}
	title="Convert Deal to Portfolio Asset"
	impactSummary="This is an irreversible operation. The deal will be permanently converted to a portfolio asset and removed from the pipeline."
	destructive={true}
	requireRationale={true}
	rationaleLabel="Conversion Rationale"
	rationalePlaceholder="Record the basis for converting this deal to a portfolio asset."
	rationaleMinLength={20}
	typedConfirmationText={String(data.deal.name ?? "")}
	typedConfirmationLabel="Type the deal name to confirm"
	confirmLabel="Convert to Asset"
	metadata={[
		{ label: "Deal", value: String(data.deal.name ?? "—"), emphasis: true },
		{ label: "Action", value: "Convert → Portfolio Asset" },
	]}
	onConfirm={convertDeal}
	onCancel={() => { showConvert = false; }}
>
	{#snippet children()}
		<div class="space-y-4">
			<FormField label="Actor Capacity" required>
				<input
					type="text"
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
					bind:value={convertActorCapacity}
					placeholder="e.g. Managing Partner, Investment Committee"
					aria-required="true"
				/>
			</FormField>
			{#if actionError}
				<p class="text-sm text-[var(--netz-status-error)]">{actionError}</p>
			{/if}
		</div>
	{/snippet}
</ConsequenceDialog>

<!-- IC Condition Resolution Dialog (ConsequenceDialog) -->
<ConsequenceDialog
	bind:open={showConditionDialog}
	title={pendingCondition?.status === "waived" ? "Waive IC Condition" : "Resolve IC Condition"}
	impactSummary={pendingCondition?.status === "waived"
		? "Waiving this condition removes it from the outstanding IC conditions without evidence of completion. The decision will be recorded in the audit trail."
		: "Resolving this condition marks it as satisfied. Confirm evidence of completion in the rationale field."}
	destructive={pendingCondition?.status === "waived"}
	requireRationale={true}
	rationaleLabel="Resolution Rationale"
	rationalePlaceholder="Record the evidence or basis for this condition resolution."
	rationaleMinLength={20}
	confirmLabel={pendingCondition?.status === "waived" ? "Waive Condition" : "Resolve Condition"}
	onConfirm={submitConditionResolution}
	onCancel={() => { showConditionDialog = false; }}
>
	{#snippet children()}
		<div class="space-y-4">
			<FormField label="Actor Capacity" required>
				<input
					type="text"
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-secondary)]"
					bind:value={conditionActorCapacity}
					placeholder="e.g. Investment Committee Member, Partner"
					aria-required="true"
				/>
			</FormField>
			{#if actionError}
				<p class="text-sm text-[var(--netz-status-error)]">{actionError}</p>
			{/if}
		</div>
	{/snippet}
</ConsequenceDialog>
