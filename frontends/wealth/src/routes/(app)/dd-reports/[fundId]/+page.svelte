<!--
  DD Reports for fund — report version list with generate/regenerate actions.
-->
<script lang="ts">
	import { goto, invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import { PageHeader, Button, StatusBadge, EmptyState, ActionButton, formatDateTime } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { DDReportSummary } from "$lib/types/dd-report";
	import { anchorLabel, anchorColor, confidenceColor } from "$lib/types/dd-report";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let reports = $derived((data.reports ?? []) as DDReportSummary[]);
	let fund = $derived(data.fund as { id: string; name: string; ticker: string | null } | null);
	let fundId = $derived(data.fundId as string);

	let generating = $state(false);
	let error = $state<string | null>(null);

	async function generateReport() {
		generating = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			const result = await api.post<DDReportSummary>(`/dd-reports/funds/${fundId}`, {});
			await invalidateAll();
			if (result?.id) {
				goto(`/dd-reports/${fundId}/${result.id}`);
			}
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to generate report";
		} finally {
			generating = false;
		}
	}
</script>

<PageHeader
	title={fund?.name ?? "DD Reports"}
	breadcrumbs={[{ label: "DD Reports", href: "/dd-reports" }, { label: fund?.name ?? fundId }]}
>
	{#snippet actions()}
		<Button size="sm" onclick={generateReport} disabled={generating}>
			{generating ? "Generating…" : "Generate New Report"}
		</Button>
	{/snippet}
</PageHeader>

<div class="reports-page">
	{#if error}
		<div class="reports-error">{error}</div>
	{/if}

	{#if reports.length === 0}
		<EmptyState title="No DD reports" message="Generate one to start the due diligence process." />
	{:else}
		<div class="reports-list">
			{#each reports as report (report.id)}
				<button
					class="report-card"
					onclick={() => goto(`/dd-reports/${fundId}/${report.id}`)}
				>
					<div class="report-card-header">
						<span class="report-version">v{report.version}</span>
						<StatusBadge status={report.status} />
					</div>
					<div class="report-card-body">
						<div class="report-meta-row">
							<span class="report-meta-label">Created</span>
							<span class="report-meta-value">{formatDateTime(report.created_at)}</span>
						</div>
						{#if report.confidence_score !== null}
							<div class="report-meta-row">
								<span class="report-meta-label">Confidence</span>
								<span class="report-meta-value" style:color={confidenceColor(report.confidence_score)}>
									{report.confidence_score.toFixed(1)}%
								</span>
							</div>
						{/if}
						{#if report.decision_anchor}
							<div class="report-meta-row">
								<span class="report-meta-label">Recommendation</span>
								<span class="report-meta-value" style:color={anchorColor(report.decision_anchor)}>
									{anchorLabel(report.decision_anchor)}
								</span>
							</div>
						{/if}
						{#if report.approved_at}
							<div class="report-meta-row">
								<span class="report-meta-label">Approved</span>
								<span class="report-meta-value">{formatDateTime(report.approved_at)}</span>
							</div>
						{/if}
						{#if report.rejection_reason}
							<div class="report-meta-row">
								<span class="report-meta-label">Rejected</span>
								<span class="report-meta-value report-meta-danger">{report.rejection_reason}</span>
							</div>
						{/if}
					</div>
				</button>
			{/each}
		</div>
	{/if}
</div>

<style>
	.reports-page {
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
	}

	.reports-error {
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-md, 16px);
		margin-bottom: var(--netz-space-stack-md, 16px);
		border-radius: var(--netz-radius-sm, 8px);
		background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
		color: var(--netz-danger);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.reports-list {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: var(--netz-space-stack-sm, 12px);
	}

	.report-card {
		display: flex;
		flex-direction: column;
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
		background: var(--netz-surface-elevated);
		cursor: pointer;
		text-align: left;
		font-family: var(--netz-font-sans);
		transition: border-color 120ms ease, box-shadow 120ms ease;
		overflow: hidden;
	}

	.report-card:hover {
		border-color: var(--netz-border-accent);
		box-shadow: var(--netz-shadow-1);
	}

	.report-card-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-alt);
	}

	.report-version {
		font-size: var(--netz-text-body, 0.9375rem);
		font-weight: 700;
		color: var(--netz-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.report-card-body {
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px);
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-2xs, 4px);
	}

	.report-meta-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.report-meta-label {
		color: var(--netz-text-muted);
	}

	.report-meta-value {
		font-weight: 500;
		color: var(--netz-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.report-meta-danger {
		color: var(--netz-danger);
	}
</style>
