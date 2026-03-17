<!--
  Dashboard — three-tier layout:
  Tier 1 (Command): TaskInbox + alert counts
  Tier 2 (Analytical): PipelineFunnel + AUM DataCards + AI confidence
  Tier 3 (Operational): Risk/return scatter + macro sparklines + activity feed
-->
<script lang="ts">
	import { DataCard, StatusBadge, EmptyState, FunnelChart, ScatterChart, TimeSeriesChart } from "@netz/ui";
	import TaskInbox from "$lib/components/TaskInbox.svelte";
	import PipelineFunnel from "$lib/components/PipelineFunnel.svelte";
	import type { PageData } from "./$types";
	import type { PortfolioSummary, PipelineSummary, PipelineAnalytics, MacroSnapshot, TaskItem } from "$lib/types/api";

	let { data }: { data: PageData } = $props();

	let portfolio = $derived(data.portfolioSummary as PortfolioSummary | null);
	let pipeline = $derived(data.pipelineSummary as PipelineSummary | null);
	let analytics = $derived(data.pipelineAnalytics as PipelineAnalytics | null);
	let macro = $derived(data.macroSnapshot as MacroSnapshot | null);
</script>

<div class="space-y-6 p-6">
	<!-- Tier 1: Command -->
	<section>
		<h2 class="mb-4 text-lg font-semibold text-[var(--netz-text-primary)]">Action Queue</h2>
		<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
			<DataCard
				label="Deals Awaiting IC"
				value={String(pipeline?.pending_ic ?? 0)}
				trend={pipeline?.pending_ic_trend as string ?? "flat"}
			/>
			<DataCard
				label="Documents Pending Review"
				value={String(pipeline?.docs_pending ?? 0)}
				trend="flat"
			/>
			<DataCard
				label="Overdue Obligations"
				value={String(portfolio?.overdue_count ?? 0)}
				trend={Number(portfolio?.overdue_count ?? 0) > 0 ? "down" : "flat"}
			/>
			<DataCard
				label="Compliance Alerts"
				value={String((data.complianceAlerts as string[] | null)?.length ?? 0)}
				trend="flat"
			/>
		</div>

		{#if data.taskInbox}
			<div class="mt-4">
				<TaskInbox tasks={data.taskInbox as TaskItem[]} />
			</div>
		{/if}
	</section>

	<!-- Tier 2: Analytical -->
	<section>
		<h2 class="mb-4 text-lg font-semibold text-[var(--netz-text-primary)]">Pipeline & Portfolio</h2>
		<div class="grid gap-4 lg:grid-cols-3">
			<div class="lg:col-span-1">
				{#if analytics}
					<PipelineFunnel data={analytics} />
				{:else}
					<EmptyState title="No Pipeline Data" description="Pipeline analytics will appear here." />
				{/if}
			</div>
			<div class="grid gap-4 lg:col-span-2 lg:grid-cols-2">
				<DataCard
					label="Total AUM"
					value={String(portfolio?.total_aum ?? "—")}
					trend={portfolio?.aum_trend as string ?? "flat"}
				/>
				<DataCard
					label="Active Loans"
					value={String(portfolio?.active_count ?? 0)}
					trend="flat"
				/>
				<DataCard
					label="AI-Ready Deals"
					value={String(pipeline?.ai_ready ?? 0)}
					trend="up"
				/>
				<DataCard
					label="Converted QTD"
					value={String(pipeline?.converted_qtd ?? 0)}
					trend="up"
				/>
			</div>
		</div>
	</section>

	<!-- Tier 3: Operational -->
	<section>
		<h2 class="mb-4 text-lg font-semibold text-[var(--netz-text-primary)]">Market & Activity</h2>
		<div class="grid gap-4 lg:grid-cols-2">
			{#if macro}
				<div class="rounded-lg border border-[var(--netz-border)] bg-white p-4">
					<h3 class="mb-3 text-sm font-medium text-[var(--netz-text-secondary)]">Macro Indicators</h3>
					<div class="grid grid-cols-2 gap-3">
						<DataCard label="10Y Treasury" value={String(macro.treasury10y ?? "—")} trend="flat" />
						<DataCard label="BAA Spread" value={String(macro.baaSpread ?? "—")} trend="flat" />
						<DataCard label="Yield Curve" value={String(macro.yieldCurve ?? "—")} trend="flat" />
						<DataCard label="CPI YoY" value={String(macro.cpiYoy ?? "—")} trend="flat" />
					</div>
				</div>
			{:else}
				<EmptyState title="No Macro Data" description="FRED macro data will appear here once available." />
			{/if}
			<div class="rounded-lg border border-[var(--netz-border)] bg-white p-4">
				<h3 class="mb-3 text-sm font-medium text-[var(--netz-text-secondary)]">Recent Activity</h3>
				<EmptyState title="No Activity" description="Recent activity will appear here." />
			</div>
		</div>
	</section>
</div>
