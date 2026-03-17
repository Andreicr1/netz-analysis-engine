<!--
  Deal detail — tabs: Overview, IC Memo, Documents, Compliance.
  IC Memo tab uses SSE for streaming chapter content.
-->
<script lang="ts">
	import { PageTabs, Card, StatusBadge, Button, EmptyState } from "@netz/ui";
	import DealStageTimeline from "$lib/components/DealStageTimeline.svelte";
	import ICMemoViewer from "$lib/components/ICMemoViewer.svelte";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	let activeTab = $state("overview");
</script>

<div class="p-6">
	<div class="mb-4 flex items-center justify-between">
		<div>
			<h2 class="text-xl font-semibold text-[var(--netz-text-primary)]">
				{data.deal.name ?? "Deal"}
			</h2>
			<div class="mt-1 flex items-center gap-2">
				<StatusBadge status={String(data.deal.stage)} type="deal" />
				{#if data.deal.strategy_type}
					<span class="text-sm text-[var(--netz-text-muted)]">{data.deal.strategy_type}</span>
				{/if}
			</div>
		</div>
	</div>

	{#if data.stageTimeline}
		<div class="mb-6">
			<DealStageTimeline timeline={data.stageTimeline as import("$lib/types/api").StageTimelineEntry[]} />
		</div>
	{/if}

	<PageTabs
		tabs={[
			{ id: "overview", label: "Overview" },
			{ id: "ic-memo", label: "IC Memo" },
			{ id: "documents", label: "Documents" },
			{ id: "compliance", label: "Compliance" },
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
						<p class="text-xs text-[var(--netz-text-muted)]">Borrower</p>
						<p class="text-sm font-medium">{data.deal.borrower_name ?? "—"}</p>
					</div>
					<div>
						<p class="text-xs text-[var(--netz-text-muted)]">Amount</p>
						<p class="text-sm font-medium">{data.deal.amount ?? "—"}</p>
					</div>
					<div>
						<p class="text-xs text-[var(--netz-text-muted)]">Strategy</p>
						<p class="text-sm font-medium">{data.deal.strategy_type ?? "—"}</p>
					</div>
					<div>
						<p class="text-xs text-[var(--netz-text-muted)]">Created</p>
						<p class="text-sm font-medium">{data.deal.created_at ?? "—"}</p>
					</div>
				</div>
			</Card>

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

		{:else if activeTab === "compliance"}
			<EmptyState
				title="Compliance"
				description="Regulatory compliance checks and deadlines."
			/>
		{/if}
	</div>
</div>
