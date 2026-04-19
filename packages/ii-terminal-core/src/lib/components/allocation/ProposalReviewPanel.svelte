<!--
  PR-A26.3 Section D — Proposal Review Panel.

  Shows a pending propose-mode run as a diff vs the current approved
  Strategic. Approve is atomic; an infeasible proposal opens a confirm
  modal before POSTing with ``confirm_cvar_infeasible = true``.

  Dismiss is cosmetic in v1 — the panel hides locally, the DB run
  persists. Running a new propose supersedes it.

  PR-4b — terminal re-skin. ECharts bar colors now resolved via
  ``readTerminalTokens()`` (no hex in script). All surfaces use
  ``--terminal-*`` custom properties; no Tailwind semantic colors.
-->
<script lang="ts">
	import {
		formatDateTime,
		formatNumber,
		formatPercent,
		readTerminalTokens,
	} from "@investintell/ui";
	import { CheckCircle2, AlertTriangle } from "lucide-svelte";
	import GenericEChart from "../../components/charts/GenericEChart.svelte";
	import CascadeTimeline from "./CascadeTimeline.svelte";
	import type {
		AllocationProfile,
		ApproveProposalRequest,
		LatestProposalResponse,
		StrategicAllocationBlock,
	} from "../../types/allocation-page";

	interface Props {
		profile: AllocationProfile;
		proposal: LatestProposalResponse;
		strategicBlocks: StrategicAllocationBlock[];
		onApproved: () => Promise<void> | void;
		apiPost: <T>(path: string, body: unknown) => Promise<T>;
	}

	let { profile, proposal, strategicBlocks, onApproved, apiPost }: Props =
		$props();

	let expanded = $state(false);
	let approving = $state(false);
	let showConfirmInfeasible = $state(false);
	let dismissed = $state(false);
	let errorMsg = $state<string | null>(null);

	const nameByBlock = $derived(
		new Map(strategicBlocks.map((b) => [b.block_id, b.block_name])),
	);
	const currentByBlock = $derived(
		new Map(strategicBlocks.map((b) => [b.block_id, b.target_weight ?? 0])),
	);

	const diffs = $derived(
		proposal.proposed_bands.map((b) => {
			const current = currentByBlock.get(b.block_id) ?? 0;
			return {
				block_id: b.block_id,
				block_name: nameByBlock.get(b.block_id) ?? b.block_id,
				current,
				proposed: b.target_weight,
				delta: b.target_weight - current,
			};
		}),
	);

	const diffChartOptions = $derived.by(() => {
		const tokens = readTerminalTokens();
		const sorted = [...diffs].sort((a, b) => a.delta - b.delta);
		return {
			tooltip: {
				trigger: "axis",
				axisPointer: { type: "shadow" },
				formatter: (arr: { name: string; value: number }[]) => {
					const p = arr[0];
					if (!p) return "";
					return `${p.name}<br/>Delta: ${formatPercent(p.value, 2)}`;
				},
			},
			grid: { left: 140, right: 20, top: 10, bottom: 30 },
			xAxis: {
				type: "value",
				axisLabel: { formatter: (v: number) => formatPercent(v, 0) },
			},
			yAxis: {
				type: "category",
				data: sorted.map((d) => d.block_name),
				axisLabel: { fontSize: 11 },
			},
			series: [
				{
					type: "bar",
					data: sorted.map((d) => ({
						value: d.delta,
						itemStyle: {
							color: d.delta >= 0 ? tokens.statusSuccess : tokens.statusError,
						},
					})),
				},
			],
		};
	});

	const isInfeasible = $derived(!proposal.proposal_metrics.cvar_feasible);

	async function doApprove(confirmInfeasible: boolean): Promise<void> {
		approving = true;
		errorMsg = null;
		try {
			const body: ApproveProposalRequest = {
				confirm_cvar_infeasible: confirmInfeasible,
				operator_message: null,
			};
			await apiPost(
				`/portfolio/profiles/${profile}/approve-proposal/${proposal.run_id}`,
				body,
			);
			showConfirmInfeasible = false;
			await onApproved();
		} catch (err) {
			errorMsg = err instanceof Error ? err.message : "Approval failed";
		} finally {
			approving = false;
		}
	}

	function onApproveClick(): void {
		if (isInfeasible) {
			showConfirmInfeasible = true;
			return;
		}
		void doApprove(false);
	}
</script>

{#if !dismissed}
	<section class="proposal-panel">
		<header class="proposal-panel__header">
			<div class="proposal-panel__title-block">
				<h2 class="proposal-panel__title">Pending Proposal</h2>
				<p class="proposal-panel__subtitle">
					Generated {formatDateTime(proposal.requested_at)}
				</p>
			</div>
			{#if isInfeasible}
				<span class="status-pill status-pill--warn">
					<AlertTriangle class="w-3 h-3" /> CVaR infeasible
				</span>
			{:else}
				<span class="status-pill status-pill--ok">
					<CheckCircle2 class="w-3 h-3" /> Feasible
				</span>
			{/if}
		</header>

		<dl class="metrics-grid">
			<div class="metric">
				<dt class="metric__label">Proposed E[r]</dt>
				<dd class="metric__value">
					{proposal.proposal_metrics.expected_return !== null
						? formatPercent(proposal.proposal_metrics.expected_return)
						: "—"}
				</dd>
			</div>
			<div class="metric">
				<dt class="metric__label">Proposed CVaR</dt>
				<dd class="metric__value">
					{proposal.proposal_metrics.expected_cvar !== null
						? formatPercent(proposal.proposal_metrics.expected_cvar)
						: "—"}
				</dd>
			</div>
			<div class="metric">
				<dt class="metric__label">Target CVaR</dt>
				<dd class="metric__value">
					{proposal.proposal_metrics.target_cvar !== null
						? formatPercent(proposal.proposal_metrics.target_cvar)
						: "—"}
				</dd>
			</div>
			<div class="metric">
				<dt class="metric__label">Sharpe</dt>
				<dd class="metric__value">
					{proposal.proposal_metrics.expected_sharpe !== null
						? formatNumber(proposal.proposal_metrics.expected_sharpe, 2)
						: "—"}
				</dd>
			</div>
		</dl>

		{#if proposal.phase_attempts.length > 0}
			<div class="proposal-panel__cascade">
				<CascadeTimeline
					phases={proposal.phase_attempts}
					winnerSignal={proposal.winner_signal}
					coverage={proposal.coverage}
					mode="settled"
				/>
			</div>
		{/if}

		<div class="proposal-panel__chart">
			<GenericEChart options={diffChartOptions} height={420} />
		</div>

		<div class="proposal-panel__diff">
			<button
				type="button"
				class="proposal-panel__diff-toggle"
				onclick={() => (expanded = !expanded)}
			>
				{expanded ? "Hide" : "Show"} block-by-block diff
			</button>
			{#if expanded}
				<div class="diff-table-wrap">
					<table class="diff-table">
						<thead>
							<tr>
								<th class="align-left">Asset Class</th>
								<th class="align-right">Current</th>
								<th class="align-right">Proposed</th>
								<th class="align-right">Delta</th>
							</tr>
						</thead>
						<tbody>
							{#each diffs as row (row.block_id)}
								<tr>
									<td class="align-left">{row.block_name}</td>
									<td class="align-right numeric">
										{formatPercent(row.current)}
									</td>
									<td class="align-right numeric">
										{formatPercent(row.proposed)}
									</td>
									<td
										class="align-right numeric"
										class:delta-up={row.delta > 0}
										class:delta-down={row.delta < 0}
									>
										{row.delta >= 0 ? "+" : ""}{formatPercent(row.delta)}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>

		{#if errorMsg}
			<p class="proposal-panel__error">{errorMsg}</p>
		{/if}

		<footer class="proposal-panel__footer">
			<button
				type="button"
				class="action action--ghost"
				onclick={() => (dismissed = true)}
			>
				Dismiss proposal
			</button>
			<button
				type="button"
				class="action action--primary"
				onclick={onApproveClick}
				disabled={approving}
			>
				{approving ? "Approving…" : "Approve Allocation"}
			</button>
		</footer>
	</section>

	{#if showConfirmInfeasible}
		<div
			class="modal-backdrop"
			role="dialog"
			aria-modal="true"
			aria-labelledby="confirm-infeasible-title"
		>
			<div class="modal">
				<h3 id="confirm-infeasible-title" class="modal__title">
					Proposal did not reach CVaR target
				</h3>
				<p class="modal__body">
					The optimizer could not meet the configured CVaR limit of
					<strong>
						{proposal.proposal_metrics.target_cvar !== null
							? formatPercent(proposal.proposal_metrics.target_cvar)
							: "—"}
					</strong>; best achievable was
					<strong>
						{proposal.proposal_metrics.expected_cvar !== null
							? formatPercent(proposal.proposal_metrics.expected_cvar)
							: "—"}
					</strong>. Approving accepts a Strategic IPS that cannot meet the
					target. Continue anyway?
				</p>
				<div class="modal__footer">
					<button
						type="button"
						class="action action--ghost"
						onclick={() => (showConfirmInfeasible = false)}
						disabled={approving}
					>
						Cancel
					</button>
					<button
						type="button"
						class="action action--destructive"
						onclick={() => void doApprove(true)}
						disabled={approving}
					>
						{approving ? "Approving…" : "Confirm Approval"}
					</button>
				</div>
			</div>
		</div>
	{/if}
{/if}

<style>
	.proposal-panel {
		border: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
		padding: var(--terminal-space-4);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-primary);
	}
	.proposal-panel__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--terminal-space-3);
		margin-bottom: var(--terminal-space-3);
	}
	.proposal-panel__title {
		font-size: var(--terminal-text-14);
		font-weight: 500;
		color: var(--terminal-fg-primary);
		margin: 0;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.proposal-panel__subtitle {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		margin: var(--terminal-space-1) 0 0;
	}
	.status-pill {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-1);
		padding: var(--terminal-space-1) var(--terminal-space-2);
		border: var(--terminal-border-hairline);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.status-pill--ok {
		color: var(--terminal-status-success);
		border-color: var(--terminal-status-success);
	}
	.status-pill--warn {
		color: var(--terminal-status-warn);
		border-color: var(--terminal-status-warn);
	}

	.metrics-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: var(--terminal-space-3);
		margin: 0 0 var(--terminal-space-3);
	}
	@media (min-width: 640px) {
		.metrics-grid {
			grid-template-columns: repeat(4, 1fr);
		}
	}
	.metric {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
	}
	.metric__label {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		margin: 0;
	}
	.metric__value {
		font-size: var(--terminal-text-14);
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
		margin: 0;
	}

	.proposal-panel__cascade,
	.proposal-panel__chart {
		margin-bottom: var(--terminal-space-4);
	}

	.proposal-panel__diff {
		margin-bottom: var(--terminal-space-4);
	}
	.proposal-panel__diff-toggle {
		background: transparent;
		border: none;
		color: var(--terminal-accent-amber);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		cursor: pointer;
		padding: 0;
	}
	.proposal-panel__diff-toggle:hover,
	.proposal-panel__diff-toggle:focus-visible {
		text-decoration: underline;
		outline: none;
	}

	.diff-table-wrap {
		margin-top: var(--terminal-space-2);
		overflow-x: auto;
		border: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel-raised);
	}
	.diff-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--terminal-text-11);
		font-family: var(--terminal-font-mono);
	}
	.diff-table thead tr {
		background: var(--terminal-bg-panel-sunken);
	}
	.diff-table th {
		padding: var(--terminal-space-1) var(--terminal-space-3);
		font-weight: 500;
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.diff-table td {
		padding: var(--terminal-space-1) var(--terminal-space-3);
		border-top: var(--terminal-border-hairline);
		height: var(--t-row-height);
		color: var(--terminal-fg-primary);
	}
	.align-left {
		text-align: left;
	}
	.align-right {
		text-align: right;
	}
	.numeric {
		font-variant-numeric: tabular-nums;
	}
	.delta-up {
		color: var(--terminal-status-success);
	}
	.delta-down {
		color: var(--terminal-status-error);
	}

	.proposal-panel__error {
		font-size: var(--terminal-text-10);
		color: var(--terminal-status-error);
		margin: 0 0 var(--terminal-space-2);
	}

	.proposal-panel__footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--terminal-space-3);
	}

	.action {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-1);
		padding: var(--terminal-space-2) var(--terminal-space-3);
		border: var(--terminal-border-hairline);
		background: transparent;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		cursor: pointer;
		transition: border-color var(--terminal-motion-tick)
				var(--terminal-motion-easing-out),
			color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}
	.action:disabled {
		color: var(--terminal-fg-disabled);
		border-color: var(--terminal-fg-disabled);
		cursor: not-allowed;
	}
	.action--ghost {
		color: var(--terminal-fg-tertiary);
	}
	.action--ghost:hover:not(:disabled),
	.action--ghost:focus-visible:not(:disabled) {
		color: var(--terminal-fg-primary);
		border-color: var(--terminal-fg-secondary);
		outline: none;
	}
	.action--primary {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber);
	}
	.action--primary:hover:not(:disabled),
	.action--primary:focus-visible:not(:disabled) {
		background: var(--terminal-bg-panel-sunken);
		outline: none;
	}
	.action--destructive {
		color: var(--terminal-status-error);
		border-color: var(--terminal-status-error);
	}
	.action--destructive:hover:not(:disabled),
	.action--destructive:focus-visible:not(:disabled) {
		background: var(--terminal-bg-panel-sunken);
		outline: none;
	}

	.modal-backdrop {
		position: fixed;
		inset: 0;
		z-index: var(--terminal-z-modal);
		background: var(--terminal-bg-scrim);
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--terminal-space-4);
	}
	.modal {
		width: 100%;
		max-width: 480px;
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		padding: var(--terminal-space-4);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-primary);
	}
	.modal__title {
		font-size: var(--terminal-text-14);
		font-weight: 500;
		margin: 0 0 var(--terminal-space-2);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}
	.modal__body {
		font-size: var(--terminal-text-12);
		color: var(--terminal-fg-secondary);
		margin: 0 0 var(--terminal-space-4);
		line-height: var(--terminal-leading-normal);
	}
	.modal__body strong {
		color: var(--terminal-fg-primary);
		font-weight: inherit;
	}
	.modal__footer {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: var(--terminal-space-2);
	}
</style>
