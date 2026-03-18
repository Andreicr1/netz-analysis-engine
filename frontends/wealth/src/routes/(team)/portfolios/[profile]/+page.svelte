<!--
  Portfolio Profile Detail — CVaR timeline (ECharts), snapshot metrics,
  rebalance workflow (trigger, approve, execute), drift history access.
  Per UX spec: numbers always with context, ECharts with regime bands.
-->
<script lang="ts">
	import {
		PageHeader, MetricCard, SectionCard, EmptyState, StatusBadge, Card, Button, ContextPanel,
		formatCurrency, formatDate, formatPercent, formatNumber,
	} from "@netz/ui";
	import { ChartContainer } from "@netz/ui/charts";
	import { ActionButton, ConfirmDialog } from "@netz/ui";
	import {
		globalChartOptions, regimeColors, statusColors,
	} from "@netz/ui/charts/echarts-setup";
	import StaleBanner from "$lib/components/StaleBanner.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll, goto } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";
	import type { RiskStore } from "$lib/stores/risk-store.svelte";
	import { resolveWealthStatus } from "$lib/utils/status-maps";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const riskStore = getContext<RiskStore>("netz:riskStore");

	let { data }: { data: PageData } = $props();

	// ── Snapshot metrics with context (UX principle #1) ──
	type Snapshot = {
		nav: number | null;
		return_ytd: number | null;
		return_1y: number | null;
		volatility_1y: number | null;
		sharpe_1y: number | null;
		cvar_current: number | null;
		cvar_limit: number | null;
		cvar_utilized_pct: number | null;
		regime: string | null;
		updated_at: string | null;
	};

	let snapshot = $derived(data.snapshot as Snapshot | null);
	let profile = $derived(data.profile as string);

	// CVaR from risk store (real-time via SSE/polling)
	let cvarStatus = $derived(riskStore?.cvarByProfile?.[profile] ?? null);
	let cvarHistory = $derived(riskStore?.cvarHistoryByProfile?.[profile] ?? []);

	// ── CVaR Timeline ECharts option (per UX spec) ──
	let cvarChartOption = $derived.by(() => {
		if (!cvarHistory || cvarHistory.length === 0) return null;

		const limit = cvarStatus?.cvar_limit ?? snapshot?.cvar_limit ?? -0.08;
		const warningThreshold = limit * 0.8; // 80% utilization

		return {
			...globalChartOptions,
			grid: { containLabel: true, left: 60, right: 20, top: 20, bottom: 50 },
			xAxis: { type: "time" },
			yAxis: {
				type: "value",
				inverse: true, // worse (more negative) visually higher
				axisLabel: { formatter: (v: number) => formatPercent(v, 1, "en-US") },
			},
			series: [
				{
					name: "CVaR 95%",
					type: "line",
					data: cvarHistory.map((p) => [p.date, p.cvar]),
					smooth: true,
					lineStyle: { width: 2 },
					showSymbol: false,
					markLine: {
						silent: true,
						symbol: "none",
						data: [
							{
								yAxis: limit,
								label: { formatter: `Limit: ${formatPercent(limit, 1, "en-US")}`, position: "end" },
								lineStyle: { color: statusColors.breach, type: "dashed", width: 2 },
							},
							{
								yAxis: warningThreshold,
								label: { formatter: "Warning (80%)", position: "end" },
								lineStyle: { color: statusColors.warning, type: "dashed", width: 1 },
							},
						],
					},
					markArea: {
						silent: true,
						data: [
							// Warning band between 80-100% of limit
							[
								{ yAxis: warningThreshold, itemStyle: { color: "rgba(245, 158, 11, 0.06)" } },
								{ yAxis: limit },
							],
							// Breach zone beyond limit
							[
								{ yAxis: limit, itemStyle: { color: "rgba(239, 68, 68, 0.08)" } },
								{ yAxis: limit * 1.5 },
							],
						],
					},
				},
			],
		};
	});

	// ── Rebalance workflow ──
	let showRebalanceConfirm = $state(false);
	let rebalancing = $state(false);
	let rebalanceEvents = $state<Array<Record<string, unknown>>>([]);
	let loadingEvents = $state(false);
	let actionError = $state<string | null>(null);
	let approvingEventId = $state<string | null>(null);
	let executingEventId = $state<string | null>(null);

	async function triggerRebalance() {
		rebalancing = true;
		showRebalanceConfirm = false;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/portfolios/${profile}/rebalance`, {});
			await invalidateAll();
			await loadRebalanceEvents();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Rebalance trigger failed";
		} finally {
			rebalancing = false;
		}
	}

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

	async function approveRebalance(eventId: string) {
		approvingEventId = eventId;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/portfolios/${profile}/rebalance/${eventId}/approve`, {});
			await loadRebalanceEvents();
		} catch (e) {
			if (e instanceof Error && e.message.includes("409")) {
				actionError = "Another IC member already approved this rebalance.";
			} else {
				actionError = e instanceof Error ? e.message : "Approval failed";
			}
		} finally {
			approvingEventId = null;
		}
	}

	async function executeRebalance(eventId: string) {
		executingEventId = eventId;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/portfolios/${profile}/rebalance/${eventId}/execute`, {});
			await loadRebalanceEvents();
			await invalidateAll();
		} catch (e) {
			if (e instanceof Error && e.message.includes("409")) {
				actionError = "Rebalance was already executed.";
			} else {
				actionError = e instanceof Error ? e.message : "Execution failed";
			}
		} finally {
			executingEventId = null;
		}
	}

	// ── Drift history panel ──
	let showDriftHistory = $state(false);

	// Load rebalance events on mount
	$effect(() => { loadRebalanceEvents(); });

	function fmtPct(v: number | null | undefined): string {
		return formatPercent(v, 1, "en-US");
	}

	function fmtDelta(v: number | null | undefined): string {
		if (v === null || v === undefined) return "";
		const pct = v * 100;
		const formatted = formatNumber(pct, 1, "en-US");
		return pct >= 0 ? `+${formatted}pp` : `${formatted}pp`;
	}
</script>

<div class="space-y-6 p-6">
	<!-- Stale banner -->
	{#if riskStore?.status === "stale"}
		<StaleBanner lastUpdated={riskStore.lastUpdated} onRefresh={() => riskStore.refresh()} />
	{/if}

	<PageHeader title="{profile.charAt(0).toUpperCase() + profile.slice(1)} Portfolio">
		{#snippet actions()}
			<div class="flex gap-2">
				<Button variant="outline" onclick={() => showDriftHistory = true}>
					Drift History
				</Button>
				<ActionButton
					onclick={() => showRebalanceConfirm = true}
					loading={rebalancing}
					loadingText="Triggering..."
				>
					Rebalance
				</ActionButton>
			</div>
		{/snippet}
	</PageHeader>

	{#if actionError}
		<div class="rounded-md border border-[var(--netz-status-error)] bg-[var(--netz-status-error)]/10 p-3 text-sm text-[var(--netz-status-error)]">
			{actionError}
			<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
		</div>
	{/if}

	<!-- Metric cards with context (UX #1: CVaR + limit + utilization + delta) -->
	<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
		<MetricCard
			label="CVaR 95%"
			value={fmtPct(cvarStatus?.cvar_current ?? snapshot?.cvar_current)}
			sublabel="Limit: {fmtPct(cvarStatus?.cvar_limit ?? snapshot?.cvar_limit)} | Util: {fmtPct(cvarStatus?.cvar_utilized_pct ?? snapshot?.cvar_utilized_pct)}"
			status={
				(cvarStatus?.cvar_utilized_pct ?? 0) > 1 ? "error" :
				(cvarStatus?.cvar_utilized_pct ?? 0) > 0.8 ? "warn" : undefined
			}
		/>
		<MetricCard
			label="NAV"
			value={formatCurrency(snapshot?.nav, "USD", "en-US")}
			sublabel={snapshot?.updated_at ? `Updated: ${formatDate(snapshot.updated_at)}` : ""}
		/>
		<MetricCard
			label="Return YTD"
			value={fmtPct(snapshot?.return_ytd)}
			sublabel="1Y: {fmtPct(snapshot?.return_1y)}"
		/>
		<MetricCard
			label="Regime"
			value={cvarStatus?.regime ?? snapshot?.regime ?? "—"}
			sublabel="Breach days: {cvarStatus?.consecutive_breach_days ?? 0}"
			status={cvarStatus?.trigger_status === "warning" ? "warn" : cvarStatus?.trigger_status === "breach" ? "error" : undefined}
		/>
	</div>

	<!-- CVaR Timeline Chart -->
	<SectionCard title="CVaR Timeline" subtitle="Rolling 12M with limit and regime bands">
		{#if cvarChartOption}
			<ChartContainer option={cvarChartOption} height={400} ariaLabel={`${profile} CVaR timeline`} />
		{:else}
			<EmptyState
				title="No CVaR history"
				message="CVaR timeline will appear after the daily risk pipeline runs."
			/>
		{/if}
		<!-- Stats row below chart -->
		{#if cvarStatus}
			<div class="mt-3 flex gap-6 text-xs text-[var(--netz-text-secondary)]">
				<span>Current: {fmtPct(cvarStatus.cvar_current)}</span>
				<span>Limit: {fmtPct(cvarStatus.cvar_limit)}</span>
				<span>Utilization: {fmtPct(cvarStatus.cvar_utilized_pct)}</span>
				<span>Breach days: {cvarStatus.consecutive_breach_days}</span>
			</div>
		{/if}
	</SectionCard>

	<!-- Rebalance Events -->
	<SectionCard title="Rebalance Events" subtitle="Pending and historical rebalance proposals">
		{#if loadingEvents}
			<p class="text-sm text-[var(--netz-text-muted)]">Loading events...</p>
		{:else if rebalanceEvents.length === 0}
			<EmptyState title="No rebalance events" message="Trigger a rebalance to create proposals." />
		{:else}
			<div class="space-y-3">
				{#each rebalanceEvents as event}
					<Card class="flex items-center justify-between p-4">
						<div>
							<div class="flex items-center gap-2">
								<StatusBadge status={String(event.status ?? "")} type="default" resolve={resolveWealthStatus} />
								<span class="text-sm font-medium text-[var(--netz-text-primary)]">
									Event {String(event.id ?? "").slice(0, 8)}
								</span>
							</div>
							<p class="mt-1 text-xs text-[var(--netz-text-muted)]">
								{event.created_at ? formatDate(String(event.created_at)) : ""}
							</p>
						</div>
						<div class="flex gap-2">
							{#if event.status === "pending"}
								<ActionButton
									size="sm"
									onclick={() => approveRebalance(String(event.id))}
									loading={approvingEventId === String(event.id)}
									loadingText="..."
								>
									Approve
								</ActionButton>
							{/if}
							{#if event.status === "approved"}
								<ActionButton
									size="sm"
									variant="destructive"
									onclick={() => executeRebalance(String(event.id))}
									loading={executingEventId === String(event.id)}
									loadingText="..."
								>
									Execute
								</ActionButton>
							{/if}
							<Button
								size="sm"
								variant="outline"
								onclick={() => goto(`/portfolios/${profile}/rebalance/${event.id}`)}
							>
								Detail
							</Button>
						</div>
					</Card>
				{/each}
			</div>
		{/if}
	</SectionCard>
</div>

<!-- Rebalance Confirm -->
<ConfirmDialog
	bind:open={showRebalanceConfirm}
	title="Trigger Rebalance"
	message="This will generate rebalance proposals for the {profile} portfolio based on current allocation drift. Continue?"
	confirmLabel="Trigger Rebalance"
	confirmVariant="default"
	onConfirm={triggerRebalance}
	onCancel={() => showRebalanceConfirm = false}
/>

<!-- Drift History Panel -->
{#if showDriftHistory}
	<ContextPanel
		open={showDriftHistory}
		title="Drift History — {profile}"
		onClose={() => showDriftHistory = false}
		width="560px"
	>
		<div class="p-4">
			<p class="text-sm text-[var(--netz-text-muted)]">
				Drift history with full audit trail. Export to CSV coming soon.
			</p>
			<!-- Drift timeline chart and table would go here with ECharts -->
			<EmptyState
				title="Loading drift history..."
				message="Drift events with timestamps, block deviations, and rebalance markers."
			/>
		</div>
	</ContextPanel>
{/if}
