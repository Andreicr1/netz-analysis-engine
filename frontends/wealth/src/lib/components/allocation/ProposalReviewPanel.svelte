<!--
  PR-A26.3 Section D — Proposal Review Panel.

  Shows a pending propose-mode run as a diff vs the current approved
  Strategic. Approve is atomic; an infeasible proposal opens a confirm
  modal before POSTing with ``confirm_cvar_infeasible = true``.

  Dismiss is cosmetic in v1 — the panel hides locally, the DB run
  persists. Running a new propose supersedes it.
-->
<script lang="ts">
	import { formatDateTime, formatNumber, formatPercent } from "@investintell/ui";
	import { CheckCircle2, AlertTriangle } from "lucide-svelte";
	import GenericEChart from "$lib/components/charts/GenericEChart.svelte";
	import CascadeTimeline from "./CascadeTimeline.svelte";
	import type {
		AllocationProfile,
		ApproveProposalRequest,
		LatestProposalResponse,
		StrategicAllocationBlock,
	} from "$lib/types/allocation-page";

	interface Props {
		profile: AllocationProfile;
		proposal: LatestProposalResponse;
		strategicBlocks: StrategicAllocationBlock[];
		onApproved: () => Promise<void> | void;
		apiPost: <T>(path: string, body: unknown) => Promise<T>;
	}

	let { profile, proposal, strategicBlocks, onApproved, apiPost }: Props = $props();

	let expanded = $state(false);
	let approving = $state(false);
	let showConfirmInfeasible = $state(false);
	let dismissed = $state(false);
	let errorMsg = $state<string | null>(null);

	const nameByBlock = $derived(
		new Map(strategicBlocks.map((b) => [b.block_id, b.block_name])),
	);
	const currentByBlock = $derived(
		new Map(
			strategicBlocks.map((b) => [b.block_id, b.target_weight ?? 0]),
		),
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
							color: d.delta >= 0 ? "#10b981" : "#ef4444",
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
	<section class="rounded-lg border border-border bg-card p-4">
		<header class="flex items-start justify-between mb-3">
			<div>
				<h2 class="text-base font-medium text-foreground">Pending Proposal</h2>
				<p class="text-xs text-muted-foreground mt-0.5">
					Generated {formatDateTime(proposal.requested_at)}
				</p>
			</div>
			{#if isInfeasible}
				<span
					class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-warning/10 text-warning"
				>
					<AlertTriangle class="w-3 h-3" /> CVaR infeasible
				</span>
			{:else}
				<span
					class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-success/10 text-success"
				>
					<CheckCircle2 class="w-3 h-3" /> Feasible
				</span>
			{/if}
		</header>

		<dl class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3 text-sm">
			<div>
				<dt class="text-xs uppercase tracking-wide text-muted-foreground">Proposed E[r]</dt>
				<dd class="tabular-nums text-foreground">
					{proposal.proposal_metrics.expected_return !== null
						? formatPercent(proposal.proposal_metrics.expected_return)
						: "—"}
				</dd>
			</div>
			<div>
				<dt class="text-xs uppercase tracking-wide text-muted-foreground">Proposed CVaR</dt>
				<dd class="tabular-nums text-foreground">
					{proposal.proposal_metrics.expected_cvar !== null
						? formatPercent(proposal.proposal_metrics.expected_cvar)
						: "—"}
				</dd>
			</div>
			<div>
				<dt class="text-xs uppercase tracking-wide text-muted-foreground">Target CVaR</dt>
				<dd class="tabular-nums text-foreground">
					{proposal.proposal_metrics.target_cvar !== null
						? formatPercent(proposal.proposal_metrics.target_cvar)
						: "—"}
				</dd>
			</div>
			<div>
				<dt class="text-xs uppercase tracking-wide text-muted-foreground">Sharpe</dt>
				<dd class="tabular-nums text-foreground">
					{proposal.proposal_metrics.expected_sharpe !== null
						? formatNumber(proposal.proposal_metrics.expected_sharpe, 2)
						: "—"}
				</dd>
			</div>
		</dl>

		{#if proposal.phase_attempts.length > 0}
			<div class="mb-4">
				<CascadeTimeline
					phases={proposal.phase_attempts}
					winnerSignal={proposal.winner_signal}
					coverage={proposal.coverage}
					mode="settled"
				/>
			</div>
		{/if}

		<div class="mb-4">
			<GenericEChart options={diffChartOptions} height={420} />
		</div>

		<div class="mb-4">
			<button
				type="button"
				class="text-xs text-primary hover:underline"
				onclick={() => (expanded = !expanded)}
			>
				{expanded ? "Hide" : "Show"} block-by-block diff
			</button>
			{#if expanded}
				<div class="mt-2 overflow-x-auto rounded-md border border-border">
					<table class="w-full text-xs">
						<thead class="bg-muted/40 text-muted-foreground uppercase">
							<tr>
								<th class="text-left px-3 py-1.5">Asset Class</th>
								<th class="text-right px-3 py-1.5">Current</th>
								<th class="text-right px-3 py-1.5">Proposed</th>
								<th class="text-right px-3 py-1.5">Delta</th>
							</tr>
						</thead>
						<tbody>
							{#each diffs as row (row.block_id)}
								<tr class="border-t border-border">
									<td class="px-3 py-1.5">{row.block_name}</td>
									<td class="px-3 py-1.5 text-right tabular-nums">
										{formatPercent(row.current)}
									</td>
									<td class="px-3 py-1.5 text-right tabular-nums">
										{formatPercent(row.proposed)}
									</td>
									<td
										class="px-3 py-1.5 text-right tabular-nums"
										class:text-success={row.delta > 0}
										class:text-destructive={row.delta < 0}
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
			<p class="text-xs text-destructive mb-2">{errorMsg}</p>
		{/if}

		<footer class="flex items-center justify-between">
			<button
				type="button"
				class="text-xs text-muted-foreground hover:text-foreground"
				onclick={() => (dismissed = true)}
			>
				Dismiss proposal
			</button>
			<button
				type="button"
				class="px-4 py-1.5 rounded-md bg-primary text-primary-foreground text-sm hover:bg-primary/90 disabled:opacity-50"
				onclick={onApproveClick}
				disabled={approving}
			>
				{approving ? "Approving…" : "Approve Allocation"}
			</button>
		</footer>
	</section>

	{#if showConfirmInfeasible}
		<div
			class="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
			role="dialog"
			aria-modal="true"
			aria-labelledby="confirm-infeasible-title"
		>
			<div class="w-full max-w-md rounded-lg bg-card border border-border p-5">
				<h3
					id="confirm-infeasible-title"
					class="text-base font-medium text-foreground mb-2"
				>
					Proposal did not reach CVaR target
				</h3>
				<p class="text-sm text-muted-foreground mb-4">
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
					</strong>. Approving accepts a Strategic IPS that cannot meet
					the target. Continue anyway?
				</p>
				<div class="flex items-center justify-end gap-2">
					<button
						type="button"
						class="px-3 py-1.5 rounded-md text-sm text-muted-foreground hover:text-foreground"
						onclick={() => (showConfirmInfeasible = false)}
						disabled={approving}
					>
						Cancel
					</button>
					<button
						type="button"
						class="px-3 py-1.5 rounded-md bg-destructive text-destructive-foreground text-sm hover:bg-destructive/90 disabled:opacity-50"
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
