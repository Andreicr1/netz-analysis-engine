<!--
  DD Reports for a fund — version history + trigger generation + SSE progress.
  Row click navigates to detail page. Download PDF. Regenerate.
-->
<script lang="ts">
	import { DataTable, StatusBadge, PageHeader, EmptyState, Button, Card, formatDate } from "@netz/ui";
	import { ActionButton, ConfirmDialog } from "@netz/ui";
	import type { PageData } from "./$types";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll, goto } from "$app/navigation";
	import { getContext } from "svelte";
	import { resolveWealthStatus } from "$lib/utils/status-maps";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	type FundDetail = { id: string; name: string };
	type DDReportSummary = {
		report_id: string;
		status: string;
		version: number;
		created_at: string;
	};

	let fund = $derived(data.fund as FundDetail | null);
	let reports = $derived((data.reports ?? []) as DDReportSummary[]);
	let generating = $state(false);
	let downloadingId = $state<string | null>(null);
	let showRegenConfirm = $state(false);
	let regenReportId = $state<string | null>(null);
	let regenerating = $state(false);
	let actionError = $state<string | null>(null);

	async function triggerGeneration() {
		generating = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			const res = await api.post<{ report_id: string }>(`/dd-reports/funds/${data.fundId}`, {});
			await invalidateAll();
			if (res.report_id) {
				goto(`/dd-reports/${data.fundId}/${res.report_id}`);
			}
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Generation failed";
		} finally {
			generating = false;
		}
	}

	function openRegenConfirm(reportId: string) {
		regenReportId = reportId;
		showRegenConfirm = true;
	}

	async function regenerateReport() {
		if (!regenReportId) return;
		regenerating = true;
		showRegenConfirm = false;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/dd-reports/${regenReportId}/regenerate`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Regeneration failed";
		} finally {
			regenerating = false;
			regenReportId = null;
		}
	}

	async function downloadReport(reportId: string) {
		downloadingId = reportId;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(`/fact-sheets/dd-reports/${reportId}/download`);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `dd-report-${fund?.name ?? reportId}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Download failed";
		} finally {
			downloadingId = null;
		}
	}
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	<PageHeader title={fund ? `DD Reports — ${fund.name}` : "DD Reports"}>
		{#snippet actions()}
			<ActionButton onclick={triggerGeneration} loading={generating} loadingText="Generating...">
				Generate New Report
			</ActionButton>
		{/snippet}
	</PageHeader>

	{#if actionError}
		<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
			{actionError}
			<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
		</div>
	{/if}

	{#if reports.length > 0}
		<div class="space-y-3">
			{#each reports as report (report.report_id)}
				<Card class="flex items-center justify-between p-4">
					<button
						class="flex-1 text-left"
						onclick={() => goto(`/dd-reports/${data.fundId}/${report.report_id}`)}
					>
						<div class="flex items-center gap-2">
							<p class="text-sm font-medium text-(--netz-text-primary)">
								Version {report.version}
							</p>
							<StatusBadge status={report.status} type="default" resolve={resolveWealthStatus} />
						</div>
						<p class="mt-1 text-xs text-(--netz-text-muted)">
							{formatDate(report.created_at)}
						</p>
					</button>
					<div class="ml-4 flex gap-2">
						<ActionButton
							size="sm"
							variant="outline"
							onclick={() => downloadReport(report.report_id)}
							loading={downloadingId === report.report_id}
							loadingText="..."
						>
							Download PDF
						</ActionButton>
						<ActionButton
							size="sm"
							variant="outline"
							onclick={() => openRegenConfirm(report.report_id)}
							loading={regenerating && regenReportId === report.report_id}
							loadingText="..."
						>
							Regenerate
						</ActionButton>
					</div>
				</Card>
			{/each}
		</div>
	{:else}
		<EmptyState
			title="No DD Reports"
			message="Generate a due diligence report for this fund."
		/>
	{/if}
</div>

<ConfirmDialog
	bind:open={showRegenConfirm}
	title="Regenerate DD Report"
	message="This will regenerate all chapters of this report. The previous version will be kept. Continue?"
	confirmLabel="Regenerate"
	confirmVariant="default"
	onConfirm={regenerateReport}
	onCancel={() => { showRegenConfirm = false; regenReportId = null; }}
/>
