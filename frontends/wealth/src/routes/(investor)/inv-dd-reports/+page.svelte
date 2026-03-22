<!--
  Investor — Approved DD reports with PDF download.
  Only shows reports with status "approved" or "published".
-->
<script lang="ts">
	import { PageHeader, EmptyState, Card, formatDate } from "@netz/ui";
	import { ActionButton } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	type DDReport = {
		id: string;
		fund_name: string;
		fund_id: string;
		status: string;
		created_at: string;
	};

	let reports = $derived((data.reports ?? []) as DDReport[]);
	let downloadingId = $state<string | null>(null);
	let actionError = $state<string | null>(null);

	async function downloadReport(reportId: string, fundName: string) {
		downloadingId = reportId;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(`/fact-sheets/dd-reports/${reportId}/download`);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `dd-report-${fundName.toLowerCase().replace(/\s+/g, "-")}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Download failed";
		} finally {
			downloadingId = null;
		}
	}
</script>

<div class="mx-auto max-w-5xl space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	<PageHeader title="Due Diligence Reports" />

	{#if actionError}
		<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
			{actionError}
			<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
		</div>
	{/if}

	{#if reports.length === 0}
		<EmptyState
			title="No Reports Available"
			message="Approved due diligence reports will appear here when available."
		/>
	{:else}
		<div class="space-y-3">
			{#each reports as report (report.id)}
				<Card class="flex items-center justify-between p-5">
					<div>
						<p class="font-medium text-(--netz-text-primary)">
							{report.fund_name}
						</p>
						<p class="text-sm text-(--netz-text-muted)">
							{formatDate(report.created_at)}
						</p>
					</div>
					<ActionButton
						size="sm"
						variant="outline"
						onclick={() => downloadReport(report.id, report.fund_name)}
						loading={downloadingId === report.id}
						loadingText="..."
					>
						Download PDF
					</ActionButton>
				</Card>
			{/each}
		</div>
	{/if}
</div>
