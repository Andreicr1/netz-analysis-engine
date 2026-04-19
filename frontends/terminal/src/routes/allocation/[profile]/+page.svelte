<!--
  PR-A26.3 Section B — Allocation page shell.

  Layout cage: height via --terminal-shell-cage-height, LayoutCage
  padding collapsed to --terminal-space-2 via :global(.lc-cage--standard
  :has([data-allocation-root])) override — mirrors the screener
  density pattern. Preserves the calc(100vh-88px) invariant per
  feedback_layout_cage_pattern.md.

  Page structure:
    1. Breadcrumb + IPS summary strip + regime strip
    2. Title + description
    3. KPI row (CVaR / Expected Return / Last Approved / Status)
    4. Two-column: Strategic table + donut  |  Proposal review OR Propose CTA
    5. Approval history (collapsible)

  Data refresh: on approve / propose completion / override save, we
  re-run the SvelteKit loader via invalidateAll() so the 4 endpoints
  (strategic / history / proposal / regime) re-fetch in parallel.
-->
<script lang="ts">
	import { invalidateAll } from "$app/navigation";
	import { resolve } from "$app/paths";
	import { getContext } from "svelte";
	import { formatDateTime, formatPercent } from "@investintell/ui";
	import { ChevronRight } from "lucide-svelte";
	import { createClientApiClient } from "$wealth/api/client";
	import {
		PROFILE_LABELS,
		type AllocationProfile,
		type StrategicAllocationBlock,
	} from "$wealth/types/allocation-page";
	import StrategicAllocationTable from "$wealth/components/allocation/StrategicAllocationTable.svelte";
	import AllocationDonut from "$wealth/components/allocation/AllocationDonut.svelte";
	import ProposalReviewPanel from "$wealth/components/allocation/ProposalReviewPanel.svelte";
	import ProposeButton from "$wealth/components/allocation/ProposeButton.svelte";
	import OverrideBandsEditor from "$wealth/components/allocation/OverrideBandsEditor.svelte";
	import ApprovalHistoryTable from "$wealth/components/allocation/ApprovalHistoryTable.svelte";
	import IpsSummaryStrip from "$wealth/components/allocation/IpsSummaryStrip.svelte";
	import RegimeContextStrip from "$wealth/components/allocation/RegimeContextStrip.svelte";
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

	type StatusTone = "success" | "warn" | "muted";
	const statusLabel = $derived<{ text: string; tone: StatusTone }>(
		data.proposal
			? { text: "Pending Proposal", tone: "warn" }
			: strategic?.has_active_approval
				? { text: "Active", tone: "success" }
				: { text: "Never Approved", tone: "muted" },
	);

	const expectedReturn = $derived(
		data.proposal?.proposal_metrics.expected_return ?? null,
	);
</script>

<div data-allocation-root class="allocation-root">
	{#if strategicErr || !strategic || !profile}
		<div class="allocation-error">
			<h2 class="allocation-error__title">Unable to load allocation</h2>
			<p class="allocation-error__body">
				{strategicErr?.message ?? "Unknown error."}
			</p>
		</div>
	{:else}
		<nav class="crumbs" aria-label="Breadcrumb">
			<a href={resolve("/allocation")} class="crumbs__link">Allocations</a>
			<ChevronRight class="w-3 h-3" />
			<span class="crumbs__current">{PROFILE_LABELS[profile]}</span>
		</nav>

		<IpsSummaryStrip
			class="mb-3"
			{profile}
			cvarLimit={strategic.cvar_limit}
			lastApprovedAt={strategic.last_approved_at}
			lastApprovedBy={strategic.last_approved_by}
		/>

		<RegimeContextStrip class="mb-3" data={data.regime} />

		<header class="page-header">
			<h1 class="page-header__title">
				{PROFILE_LABELS[profile]} Allocation
			</h1>
			<p class="page-header__subtitle">
				Strategic IPS governance — propose, review, and approve CVaR-optimal
				allocations for this profile.
			</p>
		</header>

		<div class="kpi-row">
			<div class="kpi">
				<div class="kpi__label">CVaR Limit</div>
				<div class="kpi__value">{formatPercent(strategic.cvar_limit)}</div>
			</div>
			<div class="kpi">
				<div class="kpi__label">Expected Return</div>
				<div class="kpi__value">
					{expectedReturn !== null ? formatPercent(expectedReturn) : "—"}
				</div>
				<div class="kpi__caption">
					{data.proposal ? "from pending proposal" : "—"}
				</div>
			</div>
			<div class="kpi">
				<div class="kpi__label">Last Approved</div>
				<div class="kpi__value kpi__value--sm">
					{strategic.last_approved_at
						? formatDateTime(strategic.last_approved_at)
						: "—"}
				</div>
				<div class="kpi__caption">by {strategic.last_approved_by ?? "—"}</div>
			</div>
			<div class="kpi">
				<div class="kpi__label">Status</div>
				<div class="kpi__status">
					<span
						class="status-pill status-pill--{statusLabel.tone}"
					>
						{statusLabel.text}
					</span>
				</div>
			</div>
		</div>

		<div class="main-grid">
			<div class="main-grid__left">
				<section class="panel">
					<header class="panel__header">
						<h2 class="panel__title">Current Strategic Allocation</h2>
						<p class="panel__subtitle">
							Approved IPS anchor for the {PROFILE_LABELS[profile]} profile.
						</p>
					</header>
					<StrategicAllocationTable
						blocks={strategic.blocks}
						{onEditOverride}
					/>
				</section>
				<section class="panel">
					<header class="panel__header">
						<h2 class="panel__title">Composition</h2>
					</header>
					<AllocationDonut
						blocks={strategic.blocks}
						hasActiveApproval={strategic.has_active_approval}
					/>
				</section>
			</div>

			<div class="main-grid__right">
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

		<ApprovalHistoryTable {profile} history={data.history} {apiGet} />

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

<style>
	.allocation-root {
		height: 100%;
		overflow-y: auto;
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-primary);
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-4);
	}

	/*
	 * Override LayoutCage padding for the allocation surface.
	 * Data-dense governance view mirrors the screener density —
	 * 8px instead of the 24px default. Preserves the cage height
	 * invariant (calc(100vh-88px)) per feedback_layout_cage_pattern.md.
	 */
	:global(.lc-cage--standard:has([data-allocation-root])) {
		padding: var(--terminal-space-2) !important;
	}

	.allocation-error {
		border: var(--terminal-border-alert);
		background: var(--terminal-bg-panel);
		padding: var(--terminal-space-4);
	}
	.allocation-error__title {
		font-size: var(--terminal-text-12);
		margin: 0;
		color: var(--terminal-status-error);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.allocation-error__body {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		margin: var(--terminal-space-1) 0 0;
	}

	.crumbs {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-1);
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.crumbs__link {
		color: var(--terminal-fg-tertiary);
		text-decoration: none;
	}
	.crumbs__link:hover,
	.crumbs__link:focus-visible {
		color: var(--terminal-fg-primary);
		outline: none;
	}
	.crumbs__current {
		color: var(--terminal-fg-primary);
	}

	.page-header {
		margin: 0;
	}
	.page-header__title {
		font-size: var(--terminal-text-20);
		font-weight: 500;
		color: var(--terminal-fg-primary);
		margin: 0;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.page-header__subtitle {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-tertiary);
		margin: var(--terminal-space-1) 0 0;
	}

	.kpi-row {
		display: grid;
		grid-template-columns: 1fr;
		gap: var(--terminal-space-2);
	}
	@media (min-width: 768px) {
		.kpi-row {
			grid-template-columns: repeat(2, 1fr);
		}
	}
	@media (min-width: 1024px) {
		.kpi-row {
			grid-template-columns: repeat(4, 1fr);
		}
	}
	.kpi {
		border: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
		padding: var(--terminal-space-3);
	}
	.kpi__label {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.kpi__value {
		font-size: var(--terminal-text-20);
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
		margin-top: var(--terminal-space-1);
	}
	.kpi__value--sm {
		font-size: var(--terminal-text-12);
	}
	.kpi__caption {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		margin-top: var(--terminal-space-1);
	}
	.kpi__status {
		margin-top: var(--terminal-space-1);
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
	.status-pill--success {
		color: var(--terminal-status-success);
		border-color: var(--terminal-status-success);
	}
	.status-pill--warn {
		color: var(--terminal-status-warn);
		border-color: var(--terminal-status-warn);
	}
	.status-pill--muted {
		color: var(--terminal-fg-tertiary);
		border-color: var(--terminal-fg-muted);
	}

	.main-grid {
		display: grid;
		grid-template-columns: 1fr;
		gap: var(--terminal-space-4);
	}
	@media (min-width: 1024px) {
		.main-grid {
			grid-template-columns: 3fr 2fr;
		}
	}
	.main-grid__left,
	.main-grid__right {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-4);
	}

	.panel {
		border: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
		padding: var(--terminal-space-3);
	}
	.panel__header {
		margin-bottom: var(--terminal-space-3);
	}
	.panel__title {
		font-size: var(--terminal-text-12);
		font-weight: 500;
		color: var(--terminal-fg-primary);
		margin: 0;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.panel__subtitle {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		margin: var(--terminal-space-1) 0 0;
	}
</style>
