<!--
  ReportVault — institutional table listing all generated reports
  with download actions and type filtering. Consumes the PortfolioReportsStore.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { formatDateTime, formatNumber } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import { createClientApiClient } from "$wealth/api/client";
	import type { ReportHistoryItem, ReportType } from "$wealth/types/model-portfolio";
	import { REPORT_TYPE_LABELS } from "$wealth/types/model-portfolio";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	interface Props {
		portfolioId: string;
		reports: ReportHistoryItem[];
		loading: boolean;
		error: string | null;
		onRefresh: () => void;
	}

	let { portfolioId, reports, loading, error, onRefresh }: Props = $props();

	// ── Filter ──────────────────────────────────────────────
	let filterType = $state<ReportType | "all">("all");

	let filteredReports = $derived(
		filterType === "all"
			? reports
			: reports.filter((r) => r.report_type === filterType),
	);

	// ── Download ────────────────────────────────────────────
	let downloadingId = $state<string | null>(null);
	let downloadError = $state<string | null>(null);

	function formatFileSize(bytes: number | null): string {
		if (bytes == null) return "—";
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${formatNumber(bytes / 1024, 1)} KB`;
		return `${formatNumber(bytes / (1024 * 1024), 1)} MB`;
	}

	function downloadEndpoint(report: ReportHistoryItem): string {
		switch (report.report_type) {
			case "fact_sheet":
				return `/fact-sheets/${encodeURIComponent(report.job_id)}/download`;
			case "monthly_report":
				return `/reporting/model-portfolios/${portfolioId}/monthly-report/download/${report.id}`;
			default:
				return "";
		}
	}

	async function downloadReport(report: ReportHistoryItem) {
		downloadingId = report.id;
		downloadError = null;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(downloadEndpoint(report));
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = report.display_filename;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			downloadError = e instanceof Error ? e.message : "Download failed";
		} finally {
			downloadingId = null;
		}
	}

	function reportTypeBadgeClass(type: string): string {
		switch (type) {
			case "fact_sheet": return "rv-badge--factsheet";
			case "monthly_report": return "rv-badge--monthly";
			default: return "";
		}
	}
</script>

<section class="mp-section mp-section--full">
	<h3 class="mp-section-title">
		Document Vault
		{#if reports.length > 0}
			<span class="mp-section-count">{reports.length} reports</span>
		{/if}
	</h3>

	{#if error || downloadError}
		<div class="rv-error">
			{error ?? downloadError}
			<button class="rv-error-dismiss" onclick={() => (downloadError = null)}>dismiss</button>
		</div>
	{/if}

	<div class="rv-toolbar">
		<select class="rv-filter" bind:value={filterType}>
			<option value="all">All Types</option>
			<option value="fact_sheet">Fact Sheets</option>
			<option value="monthly_report">Monthly Reports</option>
		</select>
		<Button size="sm" variant="outline" onclick={onRefresh} disabled={loading}>
			{loading ? "Loading…" : "Refresh"}
		</Button>
	</div>

	{#if filteredReports.length === 0}
		<div class="mp-empty">
			<p>No reports generated yet. Use the Report Generator to create your first report.</p>
		</div>
	{:else}
		<div class="rv-table-wrap">
			<table class="rv-table">
				<thead>
					<tr>
						<th class="rv-th-type">Type</th>
						<th class="rv-th-file">Filename</th>
						<th class="rv-th-date">Generated</th>
						<th class="rv-th-size">Size</th>
						<th class="rv-th-action"></th>
					</tr>
				</thead>
				<tbody>
					{#each filteredReports as report (report.id)}
						<tr class="rv-row">
							<td>
								<span class="rv-badge {reportTypeBadgeClass(report.report_type)}">
									{REPORT_TYPE_LABELS[report.report_type as ReportType] ?? report.report_type}
								</span>
							</td>
							<td class="rv-filename" title={report.display_filename}>
								{report.display_filename}
							</td>
							<td class="rv-date">{formatDateTime(report.generated_at)}</td>
							<td class="rv-size">{formatFileSize(report.size_bytes)}</td>
							<td class="rv-action">
								<Button
									size="sm"
									variant="outline"
									onclick={() => downloadReport(report)}
									disabled={downloadingId === report.id}
								>
									{downloadingId === report.id ? "…" : "Download PDF"}
								</Button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</section>

<style>
	.rv-error {
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

	.rv-error-dismiss {
		background: none;
		border: none;
		color: var(--ii-danger);
		cursor: pointer;
		font-size: var(--ii-text-label, 0.75rem);
		text-decoration: underline;
	}

	.rv-toolbar {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 10px);
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
	}

	.rv-filter {
		font-size: var(--ii-text-small, 0.8125rem);
		padding: 4px 8px;
		border-radius: var(--ii-radius-sm, 6px);
		border: 1px solid var(--ii-border);
		background: var(--ii-surface);
		color: var(--ii-text-primary);
	}

	.rv-table-wrap {
		overflow-x: auto;
		padding: 0 var(--ii-space-inline-md, 16px) var(--ii-space-stack-sm, 12px);
	}

	.rv-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.rv-table th {
		text-align: left;
		font-weight: 600;
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.03em;
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-sm, 10px);
		border-bottom: 1px solid var(--ii-border);
	}

	.rv-table td {
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-sm, 10px);
		border-bottom: 1px solid color-mix(in srgb, var(--ii-border) 40%, transparent);
		vertical-align: middle;
	}

	.rv-row:hover {
		background: var(--ii-surface-alt);
	}

	.rv-badge {
		display: inline-block;
		padding: 2px 8px;
		border-radius: var(--ii-radius-sm, 6px);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 500;
		white-space: nowrap;
	}

	.rv-badge--factsheet {
		color: var(--ii-info);
		background: color-mix(in srgb, var(--ii-info) 10%, transparent);
	}

	.rv-badge--monthly {
		color: var(--ii-warning);
		background: color-mix(in srgb, var(--ii-warning) 10%, transparent);
	}

	.rv-filename {
		font-weight: 500;
		color: var(--ii-text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 300px;
	}

	.rv-date {
		color: var(--ii-text-muted);
		white-space: nowrap;
	}

	.rv-size {
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}

	.rv-action {
		text-align: right;
	}

	.rv-th-type { width: 140px; }
	.rv-th-size { width: 80px; }
	.rv-th-date { width: 160px; }
	.rv-th-action { width: 120px; }
</style>
