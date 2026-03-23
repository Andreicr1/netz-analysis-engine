<!--
  RebalancingTab — IC governance workflow for portfolio rebalancing.
  State machine: proposed -> pending_review -> approved -> executing -> executed
  with rejected/failed branches.
  ConsequenceDialog for approve (with rationale) and execute (separate dialog).
-->
<script lang="ts">
	import {
		SectionCard,
		EmptyState,
		StatusBadge,
		Card,
		Button,
		MetricCard,
		ActionButton,
		ConsequenceDialog,
	} from "@netz/ui";
	import type { ConsequenceDialogPayload } from "@netz/ui";
	import { ChartContainer } from "@netz/ui/charts";
	import { formatPercent, formatNumber, formatDateTime } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import { resolveWealthStatus } from "$lib/utils/status-maps";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	interface Props {
		profile: string;
		currentWeights: Record<string, number>;
		cvarCurrent: number | null;
		cvarLimit: number | null;
	}

	let { profile, currentWeights, cvarCurrent, cvarLimit }: Props = $props();

	// ── State ────────────────────────────────────────────────────────
	let rebalanceEvents = $state<Array<Record<string, unknown>>>([]);
	let loadingEvents = $state(false);
	let proposing = $state(false);
	let actionError = $state<string | null>(null);

	// ── ConsequenceDialog state ──
	let showApproveDialog = $state(false);
	let showExecuteDialog = $state(false);
	let targetEventId = $state<string | null>(null);
	let targetEventLabel = $state<string>("");

	// ── Derived data ──
	let pendingEvent = $derived(
		rebalanceEvents.find((e) =>
			e.status === "pending" || e.status === "proposed" || e.status === "pending_review"
		) ?? null
	);
	let approvedEvent = $derived(
		rebalanceEvents.find((e) => e.status === "approved") ?? null
	);

	// Before/after weight comparison from latest pending/approved event
	let comparisonEvent = $derived(pendingEvent ?? approvedEvent ?? null);

	let beforeWeights = $derived.by((): Record<string, number> => {
		const raw = comparisonEvent?.weights_before;
		if (!raw || typeof raw !== "object") return currentWeights;
		const out: Record<string, number> = {};
		for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
			if (typeof v === "number") out[k] = v;
		}
		return Object.keys(out).length > 0 ? out : currentWeights;
	});

	let afterWeights = $derived.by((): Record<string, number> => {
		const raw = comparisonEvent?.weights_after;
		if (!raw || typeof raw !== "object") return {};
		const out: Record<string, number> = {};
		for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
			if (typeof v === "number") out[k] = v;
		}
		return out;
	});

	let hasProposal = $derived(Object.keys(afterWeights).length > 0);

	// CVaR impact
	let cvarBefore = $derived.by((): number | null => {
		const raw = comparisonEvent?.cvar_before;
		if (typeof raw === "number") return raw;
		if (typeof raw === "string") return parseFloat(raw);
		return cvarCurrent;
	});

	let cvarAfter = $derived.by((): number | null => {
		const raw = comparisonEvent?.cvar_after;
		if (typeof raw === "number") return raw;
		if (typeof raw === "string") return parseFloat(raw);
		return null;
	});

	// ── Butterfly chart data ──
	let butterflyChartOption = $derived.by(() => {
		if (!hasProposal) return null;

		const allFunds = [...new Set([...Object.keys(beforeWeights), ...Object.keys(afterWeights)])];
		allFunds.sort((a, b) => {
			const deltaA = (afterWeights[a] ?? 0) - (beforeWeights[a] ?? 0);
			const deltaB = (afterWeights[b] ?? 0) - (beforeWeights[b] ?? 0);
			return deltaB - deltaA;
		});

		const deltas = allFunds.map((f) => ((afterWeights[f] ?? 0) - (beforeWeights[f] ?? 0)) * 100);

		return {
			tooltip: {
				trigger: "axis" as const,
				formatter: (params: Array<{ name: string; value: number }>) => {
					const p = params[0];
					if (!p) return "";
					const sign = p.value >= 0 ? "+" : "";
					return `${p.name}: ${sign}${p.value.toFixed(2)}pp`;
				},
			},
			grid: { containLabel: true, left: 20, right: 20, top: 10, bottom: 10 },
			xAxis: {
				type: "value" as const,
				axisLabel: { formatter: (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}pp` },
			},
			yAxis: {
				type: "category" as const,
				data: allFunds,
				axisLabel: {
					width: 120,
					overflow: "truncate" as const,
					fontSize: 11,
				},
			},
			series: [
				{
					type: "bar" as const,
					data: deltas.map((d) => ({
						value: d,
						itemStyle: {
							color: d >= 0 ? "var(--netz-success)" : "var(--netz-danger)",
						},
					})),
					label: {
						show: true,
						position: "right" as const,
						formatter: (p: { value: number }) => {
							const sign = p.value >= 0 ? "+" : "";
							return `${sign}${p.value.toFixed(2)}pp`;
						},
						fontSize: 10,
					},
				},
			],
		};
	});

	// ── API calls ──

	async function loadRebalanceEvents() {
		loadingEvents = true;
		try {
			const api = createClientApiClient(getToken);
			const res = await api.get<Array<Record<string, unknown>>>(`/portfolios/${profile}/rebalance`);
			rebalanceEvents = Array.isArray(res) ? res : [];
		} catch {
			rebalanceEvents = [];
		} finally {
			loadingEvents = false;
		}
	}

	async function proposeRebalance() {
		proposing = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/portfolios/${profile}/rebalance`, {});
			await invalidateAll();
			await loadRebalanceEvents();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to propose rebalance";
		} finally {
			proposing = false;
		}
	}

	function openApproveDialog(event: Record<string, unknown>) {
		targetEventId = String(event.event_id ?? event.id ?? "");
		targetEventLabel = `Event ${targetEventId.slice(0, 8)}`;
		showApproveDialog = true;
	}

	function openExecuteDialog(event: Record<string, unknown>) {
		targetEventId = String(event.event_id ?? event.id ?? "");
		targetEventLabel = `Event ${targetEventId.slice(0, 8)}`;
		showExecuteDialog = true;
	}

	async function handleApprove(payload: ConsequenceDialogPayload) {
		if (!targetEventId) return;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/portfolios/${profile}/rebalance/${targetEventId}/approve`, {
				notes: payload.rationale ?? "",
			});
			await loadRebalanceEvents();
			await invalidateAll();
		} catch (e) {
			if (e instanceof Error && e.message.includes("409")) {
				actionError = "Another IC member has already approved this rebalance.";
			} else {
				actionError = e instanceof Error ? e.message : "Approval failed";
			}
		}
	}

	async function handleExecute(payload: ConsequenceDialogPayload) {
		if (!targetEventId) return;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/portfolios/${profile}/rebalance/${targetEventId}/execute`, {});
			await loadRebalanceEvents();
			await invalidateAll();
		} catch (e) {
			if (e instanceof Error && e.message.includes("409")) {
				actionError = "Rebalance has already been executed.";
			} else {
				actionError = e instanceof Error ? e.message : "Execution failed";
			}
		}
	}

	// Load on mount
	$effect(() => { void loadRebalanceEvents(); });

	function fmtPct(v: number | null | undefined): string {
		return typeof v === "number" ? formatPercent(v, 2, "en-US") : "--";
	}
</script>

<div class="space-y-(--netz-space-section-gap)">
	{#if actionError}
		<div
			class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)"
			role="alert"
		>
			{actionError}
			<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
		</div>
	{/if}

	<!-- Propose Button + CVaR Impact KPIs -->
	<div class="flex flex-wrap items-start justify-between gap-4">
		<ActionButton
			onclick={proposeRebalance}
			loading={proposing}
			loadingText="Proposing..."
		>
			Propose Rebalance
		</ActionButton>
	</div>

	<!-- CVaR Impact Metrics -->
	{#if hasProposal && (cvarBefore !== null || cvarAfter !== null)}
		<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
			<MetricCard
				label="CVaR Current"
				value={fmtPct(cvarBefore)}
				sublabel="Before rebalance"
			/>
			<MetricCard
				label="CVaR Projected"
				value={fmtPct(cvarAfter)}
				sublabel="After rebalance"
				status={cvarAfter !== null && cvarLimit !== null && Math.abs(cvarAfter) > Math.abs(cvarLimit) ? "breach" : undefined}
			/>
			<MetricCard
				label="CVaR Limit"
				value={fmtPct(cvarLimit)}
				sublabel="Portfolio limit"
			/>
			{#if cvarBefore !== null && cvarAfter !== null}
				{@const delta = (cvarAfter - cvarBefore) * 100}
				<MetricCard
					label="CVaR Impact"
					value="{delta >= 0 ? '+' : ''}{formatNumber(delta, 2, 'en-US')}pp"
					sublabel={delta > 0 ? "Risk increase" : delta < 0 ? "Risk reduction" : "No change"}
					status={delta > 0 ? "breach" : delta < 0 ? "ok" : undefined}
				/>
			{/if}
		</div>
	{/if}

	<!-- Before/After Butterfly Chart -->
	{#if butterflyChartOption}
		<SectionCard title="Weight Change Impact" subtitle="Tornado chart: delta weight per fund">
			<ChartContainer
				option={butterflyChartOption}
				height={Math.max(200, Object.keys(afterWeights).length * 32)}
				ariaLabel="{profile} rebalance weight impact"
			/>
		</SectionCard>
	{/if}

	<!-- Before/After Weight Table -->
	{#if hasProposal}
		<SectionCard title="Before / After Comparison" subtitle="Current weights vs. proposed allocation">
			<div class="overflow-x-auto">
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-(--netz-border) text-left text-xs font-medium uppercase tracking-wider text-(--netz-text-secondary)">
							<th class="pb-2 pr-4">Fund</th>
							<th class="pb-2 pr-4 text-right">Before</th>
							<th class="pb-2 pr-4 text-right">After</th>
							<th class="pb-2 text-right">Delta</th>
						</tr>
					</thead>
					<tbody>
						{#each Object.keys(beforeWeights).sort((a, b) => (beforeWeights[b] ?? 0) - (beforeWeights[a] ?? 0)) as fund (fund)}
							{@const before = beforeWeights[fund] ?? 0}
							{@const after = afterWeights[fund] ?? 0}
							{@const delta = after - before}
							<tr class="border-b border-(--netz-border)/50">
								<td class="py-2 pr-4 text-(--netz-text-primary)">{fund}</td>
								<td class="py-2 pr-4 text-right font-mono text-(--netz-text-secondary)">{formatPercent(before, 2, "en-US")}</td>
								<td class="py-2 pr-4 text-right font-mono font-semibold text-(--netz-text-primary)">{formatPercent(after, 2, "en-US")}</td>
								<td class="py-2 text-right font-mono" class:text-(--netz-success)={delta > 0.0001} class:text-(--netz-danger)={delta < -0.0001}>
									{#if Math.abs(delta) > 0.00005}
										{delta > 0 ? "+" : ""}{formatNumber(delta * 100, 2, "en-US")}pp
									{:else}
										--
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</SectionCard>
	{/if}

	<!-- Rebalance Events List with State Machine -->
	<SectionCard title="Rebalance Events" subtitle="Proposals, approvals, and execution history">
		{#if loadingEvents}
			<p class="text-sm text-(--netz-text-muted)">Loading events...</p>
		{:else if rebalanceEvents.length === 0}
			<EmptyState title="No Rebalance Events" message="Click 'Propose Rebalance' to generate a proposal based on current allocation drift." />
		{:else}
			<div class="space-y-3">
				{#each rebalanceEvents as event (event.event_id ?? event.id)}
					{@const eventId = String(event.event_id ?? event.id ?? "")}
					{@const eventStatus = String(event.status ?? "")}
					<Card class="p-4">
						<div class="flex items-start justify-between gap-4">
							<div class="flex-1">
								<div class="flex items-center gap-2">
									<StatusBadge status={eventStatus} resolve={resolveWealthStatus} />
									<span class="text-sm font-medium text-(--netz-text-primary)">
										{eventId.slice(0, 8)}
									</span>
									<span class="text-xs text-(--netz-text-muted)">
										{event.event_type ?? "rebalance"}
									</span>
								</div>
								<div class="mt-1 flex items-center gap-3 text-xs text-(--netz-text-muted)">
									{#if event.created_at}
										<span>{formatDateTime(String(event.created_at))}</span>
									{/if}
									{#if event.approved_by}
										<span>Approved by: {event.approved_by}</span>
									{/if}
									{#if event.trigger_reason}
										<span>Reason: {String(event.trigger_reason).slice(0, 60)}</span>
									{/if}
								</div>
								{#if event.notes}
									<p class="mt-2 rounded-md bg-(--netz-surface-alt) p-2 text-xs text-(--netz-text-secondary)">
										{event.notes}
									</p>
								{/if}
							</div>
							<div class="flex gap-2">
								{#if eventStatus === "pending" || eventStatus === "proposed" || eventStatus === "pending_review"}
									<ActionButton
										size="sm"
										onclick={() => openApproveDialog(event)}
									>
										Approve
									</ActionButton>
								{/if}
								{#if eventStatus === "approved"}
									<ActionButton
										size="sm"
										variant="destructive"
										onclick={() => openExecuteDialog(event)}
									>
										Execute
									</ActionButton>
								{/if}
							</div>
						</div>
					</Card>
				{/each}
			</div>
		{/if}
	</SectionCard>
</div>

<!-- Approve ConsequenceDialog -->
<ConsequenceDialog
	bind:open={showApproveDialog}
	title="Approve Rebalance Proposal"
	impactSummary="Approving this rebalance proposal will allow execution. The portfolio weights will NOT change until the proposal is explicitly executed."
	requireRationale={true}
	rationaleLabel="Approval rationale"
	rationalePlaceholder="Provide the basis for approving this rebalance (e.g., CVaR impact acceptable, aligned with IC mandate)."
	confirmLabel="Approve proposal"
	metadata={[
		{ label: "Event", value: targetEventLabel, emphasis: true },
		{ label: "Portfolio", value: profile },
		{ label: "Action", value: "Approve for execution" },
	]}
	onConfirm={handleApprove}
	onCancel={() => { showApproveDialog = false; targetEventId = null; }}
/>

<!-- Execute ConsequenceDialog (SEPARATE from approve) -->
<ConsequenceDialog
	bind:open={showExecuteDialog}
	title="Execute Rebalance"
	impactSummary="This will apply the proposed weights to the portfolio. A new snapshot will be created with the updated allocation. This action cannot be undone."
	destructive={true}
	requireRationale={true}
	rationaleLabel="Execution rationale"
	rationalePlaceholder="Confirm execution basis (e.g., market conditions verified, compliance cleared)."
	confirmLabel="Execute rebalance"
	metadata={[
		{ label: "Event", value: targetEventLabel, emphasis: true },
		{ label: "Portfolio", value: profile },
		{ label: "Impact", value: "New portfolio snapshot created" },
	]}
	onConfirm={handleExecute}
	onCancel={() => { showExecuteDialog = false; targetEventId = null; }}
/>
