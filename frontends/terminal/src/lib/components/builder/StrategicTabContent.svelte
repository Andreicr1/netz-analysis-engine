<!--
  X3.1 — STRATEGIC tab content.

  Absorbs the former /allocation/[profile]/+page.svelte body:
    - IpsSummaryStrip
    - KPI row (CVaR / Expected Return / Last Approved / Status)
    - StrategicAllocationTable + AllocationDonut (left)
    - ProposalReviewPanel or ProposeButton (right)
    - ApprovalHistoryTable (bottom)
    - OverrideBandsEditor (drawer)

  Receives the strategic + proposal + history data the workspace
  loader already fetched, plus a refresh callback that invalidates
  the route to re-fetch in parallel after approve / propose / set-
  override actions.

  RegimeContextStrip is NOT included here — it lives in the
  workspace header, above the tab strip, so it persists across tabs.
-->
<script lang="ts">
	import { formatDateTime, formatPercent } from "@investintell/ui";
	import IpsSummaryStrip from "$wealth/components/allocation/IpsSummaryStrip.svelte";
	import StrategicAllocationTable from "$wealth/components/allocation/StrategicAllocationTable.svelte";
	import AllocationDonut from "$wealth/components/allocation/AllocationDonut.svelte";
	import ProposalReviewPanel from "$wealth/components/allocation/ProposalReviewPanel.svelte";
	import ProposeButton from "$wealth/components/allocation/ProposeButton.svelte";
	import OverrideBandsEditor from "$wealth/components/allocation/OverrideBandsEditor.svelte";
	import ApprovalHistoryTable from "$wealth/components/allocation/ApprovalHistoryTable.svelte";
	import {
		PROFILE_LABELS,
		type AllocationProfile,
		type ApprovalHistoryResponse,
		type LatestProposalResponse,
		type StrategicAllocationBlock,
		type StrategicAllocationResponse,
	} from "$wealth/types/allocation-page";

	interface Props {
		profile: AllocationProfile;
		strategic: StrategicAllocationResponse;
		proposal: LatestProposalResponse | null;
		history: ApprovalHistoryResponse;
		refresh: () => Promise<void>;
		apiGet: <T>(path: string) => Promise<T>;
		apiPost: <T>(path: string, body?: unknown) => Promise<T>;
		getToken: () => Promise<string>;
		apiBase: string;
	}

	let {
		profile,
		strategic,
		proposal,
		history,
		refresh,
		apiGet,
		apiPost,
		getToken,
		apiBase,
	}: Props = $props();

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
		proposal
			? { text: "Pending Proposal", tone: "warn" }
			: strategic.has_active_approval
				? { text: "Active", tone: "success" }
				: { text: "Never Approved", tone: "muted" },
	);

	const expectedReturn = $derived(
		proposal?.proposal_metrics.expected_return ?? null,
	);
</script>

<div class="strategic">
	<IpsSummaryStrip
		{profile}
		cvarLimit={strategic.cvar_limit}
		lastApprovedAt={strategic.last_approved_at}
		lastApprovedBy={strategic.last_approved_by}
	/>

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
				{proposal ? "from pending proposal" : "—"}
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
				<span class="status-pill status-pill--{statusLabel.tone}">
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
			{#if proposal}
				<ProposalReviewPanel
					{profile}
					{proposal}
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

	<ApprovalHistoryTable {profile} {history} {apiGet} />

	{#if editingBlock}
		<OverrideBandsEditor
			{profile}
			block={editingBlock}
			onClose={closeOverride}
			onSaved={refresh}
			{apiPost}
		/>
	{/if}
</div>

<style>
	.strategic {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-4);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-primary);
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
