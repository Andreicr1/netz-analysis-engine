<!--
  GeneratedReportsPanel — lists generated reports (monthly, long-form DD)
  with download via api.getBlob() and simple triggers for new generation.
  Fact sheets are rendered inline in the parent page; this panel handles
  the two report types that come from the WealthGeneratedReport registry.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { invalidateAll } from "$app/navigation";
	import { formatDateTime, formatNumber } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import { createClientApiClient } from "$wealth/api/client";
	import type { GeneratedReport } from "$wealth/types/model-portfolio";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	interface Props {
		portfolioId: string;
		portfolioName: string;
		monthlyReports: GeneratedReport[];
		longFormReports: GeneratedReport[];
		canGenerate: boolean;
	}

	let { portfolioId, portfolioName, monthlyReports, longFormReports, canGenerate }: Props = $props();

	// ── State ────────────────────────────────────────────────────────
	let generatingMonthly = $state(false);
	let generatingLongForm = $state(false);
	let downloadingId = $state<string | null>(null);
	let error = $state<string | null>(null);

	function formatFileSize(bytes: number | null): string {
		if (bytes == null) return "—";
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${formatNumber(bytes / 1024, 1)} KB`;
		return `${formatNumber(bytes / (1024 * 1024), 1)} MB`;
	}

	async function triggerMonthly() {
		generatingMonthly = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/reporting/model-portfolios/${portfolioId}/monthly-report`, {});
			await invalidateAll();
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to trigger monthly report";
		} finally {
			generatingMonthly = false;
		}
	}

	async function triggerLongForm() {
		generatingLongForm = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/reporting/model-portfolios/${portfolioId}/long-form-report`, {});
			await invalidateAll();
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to trigger long-form report";
		} finally {
			generatingLongForm = false;
		}
	}

	async function downloadReport(report: GeneratedReport, reportType: "monthly_report" | "long_form_dd") {
		downloadingId = report.id;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			const endpoint =
				reportType === "monthly_report"
					? `/reporting/model-portfolios/${portfolioId}/monthly-report/download/${report.id}`
					: `/reporting/model-portfolios/${portfolioId}/long-form-report/download/${report.id}`;

			const blob = await api.getBlob(endpoint);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = report.display_filename;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			error = e instanceof Error ? e.message : "Download failed";
		} finally {
			downloadingId = null;
		}
	}
</script>

{#if error}
	<div class="grp-error">
		{error}
		<button class="grp-error-dismiss" onclick={() => (error = null)}>dismiss</button>
	</div>
{/if}

<!-- Monthly Reports -->
<section class="mp-section mp-section--full">
	<h3 class="mp-section-title">
		Monthly Reports
		{#if monthlyReports.length > 0}
			<span class="mp-section-count">{monthlyReports.length} generated</span>
		{/if}
	</h3>
	<div class="grp-content">
		{#if canGenerate}
			<div class="grp-trigger">
				<Button size="sm" onclick={triggerMonthly} disabled={generatingMonthly}>
					{generatingMonthly ? "Generating…" : "Generate Monthly Report"}
				</Button>
			</div>
		{/if}

		{#if monthlyReports.length === 0}
			<div class="mp-empty">
				<p>No monthly reports generated yet.</p>
			</div>
		{:else}
			<div class="grp-list">
				{#each monthlyReports as report (report.id)}
					<div class="grp-row">
						<div class="grp-info">
							<span class="grp-filename" title={report.display_filename}>
								{report.display_filename}
							</span>
							{#if report.size_bytes != null}
								<span class="grp-size">{formatFileSize(report.size_bytes)}</span>
							{/if}
							<span class="grp-date">{formatDateTime(report.generated_at)}</span>
						</div>
						<Button
							size="sm"
							variant="outline"
							onclick={() => downloadReport(report, "monthly_report")}
							disabled={downloadingId === report.id}
						>
							{downloadingId === report.id ? "…" : "Download"}
						</Button>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</section>

<!-- Long-Form DD Reports -->
<section class="mp-section mp-section--full">
	<h3 class="mp-section-title">
		Long-Form DD Reports
		{#if longFormReports.length > 0}
			<span class="mp-section-count">{longFormReports.length} generated</span>
		{/if}
	</h3>
	<div class="grp-content">
		{#if canGenerate}
			<div class="grp-trigger">
				<Button size="sm" onclick={triggerLongForm} disabled={generatingLongForm}>
					{generatingLongForm ? "Generating…" : "Generate Long-Form DD Report"}
				</Button>
			</div>
		{/if}

		{#if longFormReports.length === 0}
			<div class="mp-empty">
				<p>No long-form DD reports generated yet.</p>
			</div>
		{:else}
			<div class="grp-list">
				{#each longFormReports as report (report.id)}
					<div class="grp-row">
						<div class="grp-info">
							<span class="grp-filename" title={report.display_filename}>
								{report.display_filename}
							</span>
							{#if report.size_bytes != null}
								<span class="grp-size">{formatFileSize(report.size_bytes)}</span>
							{/if}
							<span class="grp-date">{formatDateTime(report.generated_at)}</span>
						</div>
						<Button
							size="sm"
							variant="outline"
							onclick={() => downloadReport(report, "long_form_dd")}
							disabled={downloadingId === report.id}
						>
							{downloadingId === report.id ? "…" : "Download"}
						</Button>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</section>

<style>
	.grp-error {
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 16px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
		display: flex;
		align-items: center;
		justify-content: space-between;
		border-radius: var(--ii-radius-sm, 6px);
		margin-bottom: var(--ii-space-stack-sm, 12px);
	}

	.grp-error-dismiss {
		background: none;
		border: none;
		color: var(--ii-danger);
		cursor: pointer;
		font-size: var(--ii-text-label, 0.75rem);
		text-decoration: underline;
	}

	.grp-content {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
	}

	.grp-trigger {
		margin-bottom: var(--ii-space-stack-sm, 12px);
	}

	.grp-list {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-2xs, 6px);
	}

	.grp-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-sm, 10px);
		border-radius: var(--ii-radius-sm, 6px);
		transition: background 120ms ease;
	}

	.grp-row:hover {
		background: var(--ii-surface-alt);
	}

	.grp-info {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 10px);
		min-width: 0;
		flex: 1;
	}

	.grp-filename {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--ii-text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 300px;
	}

	.grp-size {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
	}

	.grp-date {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		flex-shrink: 0;
	}
</style>
