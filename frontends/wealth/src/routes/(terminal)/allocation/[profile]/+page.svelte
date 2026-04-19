<!--
  PR-A26.3 Section B — Allocation page shell.

  Layout cage: h-[calc(100vh-88px)] + p-6 + overflow-y-auto per
  feedback_layout_cage_pattern.md.

  Page structure:
    1. Breadcrumb + title
    2. KPI row (CVaR / Expected Return / Last Approved / Status)
    3. Two-column: Strategic table + donut  |  Proposal review OR Propose CTA
    4. Approval history (collapsible)

  Data refresh: on approve / propose completion / override save, we
  re-run the SvelteKit loader via invalidateAll() so the 3 endpoints
  re-fetch in parallel.
-->
<script lang="ts">
	import { invalidateAll } from "$app/navigation";
	import { resolve } from "$app/paths";
	import { getContext } from "svelte";
	import { formatDateTime, formatPercent } from "@investintell/ui";
	import { ChevronRight } from "lucide-svelte";
	import { createClientApiClient } from "$lib/api/client";
	import {
		PROFILE_LABELS,
		type AllocationProfile,
		type StrategicAllocationBlock,
	} from "$lib/types/allocation-page";
	import StrategicAllocationTable from "$lib/components/allocation/StrategicAllocationTable.svelte";
	import AllocationDonut from "$lib/components/allocation/AllocationDonut.svelte";
	import ProposalReviewPanel from "$lib/components/allocation/ProposalReviewPanel.svelte";
	import ProposeButton from "$lib/components/allocation/ProposeButton.svelte";
	import OverrideBandsEditor from "$lib/components/allocation/OverrideBandsEditor.svelte";
	import ApprovalHistoryTable from "$lib/components/allocation/ApprovalHistoryTable.svelte";
	import IpsSummaryStrip from "$lib/components/allocation/IpsSummaryStrip.svelte";
	import RegimeContextStrip from "$lib/components/allocation/RegimeContextStrip.svelte";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	// RouteData<StrategicAllocationResponse> envelope handling.
	const strategic = $derived(data.strategic.data);
	const strategicErr = $derived(data.strategic.error);
	const profile = $derived(data.profile as AllocationProfile | null);

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const apiBase =
		import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

	function clientApi() {
		return createClientApiClient(getToken);
	}
	async function apiGet<T>(path: string): Promise<T> {
		return clientApi().get<T>(path);
	}
	async function apiPost<T>(path: string, body?: unknown): Promise<T> {
		return clientApi().post<T>(path, body ?? {});
	}

	async function refresh(): Promise<void> {
		await invalidateAll();
	}

	// Override editor state.
	let editingBlock = $state<StrategicAllocationBlock | null>(null);
	function onEditOverride(block: StrategicAllocationBlock): void {
		editingBlock = block;
	}
	function closeOverride(): void {
		editingBlock = null;
	}

	// KPI status derivation.
	const statusLabel = $derived.by(() => {
		if (data.proposal) return { text: "Pending Proposal", tone: "warning" };
		if (strategic?.has_active_approval)
			return { text: "Active", tone: "success" };
		return { text: "Never Approved", tone: "muted" };
	});

	const expectedReturn = $derived(
		data.proposal?.proposal_metrics.expected_return ?? null,
	);
</script>

<div class="h-[calc(100vh-88px)] overflow-y-auto p-6">
	{#if strategicErr || !strategic || !profile}
		<div class="rounded-md border border-destructive/40 bg-destructive/5 p-4">
			<h2 class="text-sm font-medium text-destructive">
				Unable to load allocation
			</h2>
			<p class="text-xs text-muted-foreground mt-1">
				{strategicErr?.message ?? "Unknown error."}
			</p>
		</div>
	{:else}
	<nav
		class="flex items-center gap-1 text-xs text-muted-foreground mb-3"
		aria-label="Breadcrumb"
	>
		<a href={resolve("/allocation")} class="hover:text-foreground">
			Allocations
		</a>
		<ChevronRight class="w-3 h-3" />
		<span class="text-foreground">{PROFILE_LABELS[profile]}</span>
	</nav>

	<IpsSummaryStrip
		class="mb-3"
		{profile}
		cvarLimit={strategic.cvar_limit}
		lastApprovedAt={strategic.last_approved_at}
		lastApprovedBy={strategic.last_approved_by}
	/>

	<RegimeContextStrip class="mb-3" data={data.regime} />

	<header class="mb-5">
		<h1 class="text-2xl font-semibold text-foreground">
			{PROFILE_LABELS[profile]} Allocation
		</h1>
		<p class="text-sm text-muted-foreground mt-1">
			Strategic IPS governance — propose, review, and approve CVaR-optimal
			allocations for this profile.
		</p>
	</header>

	<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
		<div class="rounded-lg border border-border bg-card p-4">
			<div class="text-xs uppercase tracking-wide text-muted-foreground">
				CVaR Limit
			</div>
			<div class="text-xl font-semibold text-foreground tabular-nums mt-1">
				{formatPercent(strategic.cvar_limit)}
			</div>
		</div>
		<div class="rounded-lg border border-border bg-card p-4">
			<div class="text-xs uppercase tracking-wide text-muted-foreground">
				Expected Return
			</div>
			<div class="text-xl font-semibold text-foreground tabular-nums mt-1">
				{expectedReturn !== null ? formatPercent(expectedReturn) : "—"}
			</div>
			<div class="text-[10px] text-muted-foreground mt-0.5">
				{data.proposal ? "from pending proposal" : "—"}
			</div>
		</div>
		<div class="rounded-lg border border-border bg-card p-4">
			<div class="text-xs uppercase tracking-wide text-muted-foreground">
				Last Approved
			</div>
			<div class="text-sm text-foreground mt-1">
				{strategic.last_approved_at
					? formatDateTime(strategic.last_approved_at)
					: "—"}
			</div>
			<div class="text-[10px] text-muted-foreground mt-0.5">
				by {strategic.last_approved_by ?? "—"}
			</div>
		</div>
		<div class="rounded-lg border border-border bg-card p-4">
			<div class="text-xs uppercase tracking-wide text-muted-foreground">
				Status
			</div>
			<div class="mt-1">
				<span
					class="inline-flex items-center px-2 py-0.5 rounded-full text-xs"
					class:bg-success={statusLabel.tone === "success"}
					class:text-success-foreground={statusLabel.tone === "success"}
					class:bg-warning={statusLabel.tone === "warning"}
					class:text-warning-foreground={statusLabel.tone === "warning"}
					class:bg-muted={statusLabel.tone === "muted"}
					class:text-muted-foreground={statusLabel.tone === "muted"}
				>
					{statusLabel.text}
				</span>
			</div>
		</div>
	</div>

	<div class="grid grid-cols-1 lg:grid-cols-5 gap-4 mb-6">
		<div class="lg:col-span-3 space-y-4">
			<section class="rounded-lg border border-border bg-card p-4">
				<header class="mb-3">
					<h2 class="text-base font-medium text-foreground">
						Current Strategic Allocation
					</h2>
					<p class="text-xs text-muted-foreground mt-0.5">
						Approved IPS anchor for the {PROFILE_LABELS[profile]} profile.
					</p>
				</header>
				<StrategicAllocationTable
					blocks={strategic.blocks}
					{onEditOverride}
				/>
			</section>
			<section class="rounded-lg border border-border bg-card p-4">
				<header class="mb-2">
					<h2 class="text-base font-medium text-foreground">Composition</h2>
				</header>
				<AllocationDonut
					blocks={strategic.blocks}
					hasActiveApproval={strategic.has_active_approval}
				/>
			</section>
		</div>

		<div class="lg:col-span-2 space-y-4">
			{#if data.proposal}
				<ProposalReviewPanel
					{profile}
					proposal={data.proposal}
					strategicBlocks={strategic.blocks}
					onApproved={refresh}
					{apiPost}
				/>
			{:else}
				<ProposeButton
					{profile}
					cvarLimit={strategic.cvar_limit}
					onCompleted={refresh}
					{apiPost}
					{getToken}
					{apiBase}
				/>
			{/if}
		</div>
	</div>

	<ApprovalHistoryTable
		{profile}
		history={data.history}
		{apiGet}
	/>

	{#if editingBlock}
		<OverrideBandsEditor
			{profile}
			block={editingBlock}
			onClose={closeOverride}
			onSaved={refresh}
			{apiPost}
		/>
	{/if}
	{/if}
</div>
