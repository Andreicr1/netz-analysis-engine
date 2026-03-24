<!--
  DD Reports — lists all DD reports for the tenant with status, actions per status.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { PageHeader, StatusBadge, EmptyState, formatDateTime } from "@netz/ui";
	import type { PageData } from "./$types";
	import type { DDReportListItem } from "$lib/types/dd-report";
	import { anchorLabel, anchorColor, confidenceColor } from "$lib/types/dd-report";

	let { data }: { data: PageData } = $props();

	let reports = $derived((data.reports ?? []) as DDReportListItem[]);
	let statusFilter = $derived((data.statusFilter ?? null) as string | null);
	let search = $state("");

	let filtered = $derived.by(() => {
		let rows = reports;
		if (search) {
			const q = search.toLowerCase();
			rows = rows.filter(
				(r) =>
					r.instrument_name.toLowerCase().includes(q) ||
					r.instrument_ticker?.toLowerCase().includes(q)
			);
		}
		return rows;
	});

	const STATUS_FILTERS = [
		{ value: null, label: "All" },
		{ value: "generating", label: "Generating" },
		{ value: "pending_approval", label: "Pending Approval" },
		{ value: "approved", label: "Approved" },
		{ value: "draft", label: "Draft" },
		{ value: "failed", label: "Failed" },
	];

	function setStatusFilter(status: string | null) {
		const url = status ? `/dd-reports?status=${status}` : "/dd-reports";
		goto(url, { invalidateAll: true });
	}

	function statusActionLabel(status: string): string {
		switch (status) {
			case "draft":
			case "failed":
				return "Run DD Report";
			case "generating":
				return "View Progress";
			case "pending_approval":
				return "Review & Approve";
			case "approved":
				return "View Report";
			default:
				return "View";
		}
	}
</script>

<PageHeader title="Due Diligence Reports" />

<div class="dd-page">
	<div class="dd-toolbar">
		<input
			type="text"
			class="dd-search"
			placeholder="Search by name or ticker…"
			bind:value={search}
		/>
		<div class="dd-status-chips">
			{#each STATUS_FILTERS as sf (sf.value)}
				<button
					class="dd-chip"
					class:dd-chip--active={statusFilter === sf.value}
					onclick={() => setStatusFilter(sf.value)}
				>
					{sf.label}
				</button>
			{/each}
		</div>
	</div>

	{#if filtered.length === 0}
		<EmptyState
			title={reports.length === 0 ? "No DD reports yet" : "No reports match your filters"}
			message={reports.length === 0 ? "Send instruments from the Screener to start the review process." : "Try adjusting your search or status filter."}
		/>
	{:else}
		<div class="dd-table-wrap">
			<table class="dd-table">
				<thead>
					<tr>
						<th>Instrument</th>
						<th>Version</th>
						<th>Status</th>
						<th>Confidence</th>
						<th>Recommendation</th>
						<th>Created</th>
						<th>Action</th>
					</tr>
				</thead>
				<tbody>
					{#each filtered as report (report.id)}
						<tr
							class="dd-row"
							onclick={() => goto(`/dd-reports/${report.instrument_id}/${report.id}`)}
						>
							<td class="dd-cell-name">
								<span class="dd-name">{report.instrument_name || "—"}</span>
								{#if report.instrument_ticker}
									<span class="dd-ticker">{report.instrument_ticker}</span>
								{/if}
							</td>
							<td class="dd-cell-version">v{report.version}</td>
							<td><StatusBadge status={report.status} /></td>
							<td class="dd-cell-num">
								{#if report.confidence_score !== null}
									<span style:color={confidenceColor(report.confidence_score)}>
										{report.confidence_score.toFixed?.(1) ?? report.confidence_score}%
									</span>
								{:else}
									<span class="dd-muted">—</span>
								{/if}
							</td>
							<td>
								{#if report.decision_anchor}
									<span class="dd-anchor" style:color={anchorColor(report.decision_anchor)}>
										{anchorLabel(report.decision_anchor)}
									</span>
								{:else}
									<span class="dd-muted">—</span>
								{/if}
							</td>
							<td class="dd-cell-date">{formatDateTime(report.created_at)}</td>
							<td>
								<button
									class="dd-action-btn"
									onclick={(e) => { e.stopPropagation(); goto(`/dd-reports/${report.instrument_id}/${report.id}`); }}
								>
									{statusActionLabel(report.status)}
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>

<style>
	.dd-page {
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
	}

	.dd-toolbar {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-md, 16px);
		margin-bottom: var(--netz-space-stack-md, 16px);
		flex-wrap: wrap;
	}

	.dd-search {
		width: 100%;
		max-width: 320px;
		height: var(--netz-space-control-height-md, 40px);
		padding: 0 var(--netz-space-inline-sm, 12px);
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 8px);
		background: var(--netz-surface-elevated);
		color: var(--netz-text-primary);
		font-size: var(--netz-text-body, 0.9375rem);
		font-family: var(--netz-font-sans);
	}

	.dd-search:focus {
		outline: none;
		border-color: var(--netz-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--netz-brand-secondary) 20%, transparent);
	}

	.dd-search::placeholder {
		color: var(--netz-text-muted);
	}

	.dd-status-chips {
		display: flex;
		gap: var(--netz-space-inline-xs, 6px);
		flex-wrap: wrap;
	}

	.dd-chip {
		padding: var(--netz-space-stack-2xs, 4px) var(--netz-space-inline-sm, 12px);
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-pill, 999px);
		background: transparent;
		color: var(--netz-text-secondary);
		font-size: var(--netz-text-label, 0.75rem);
		font-family: var(--netz-font-sans);
		font-weight: 500;
		cursor: pointer;
		transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
	}

	.dd-chip:hover {
		background: var(--netz-surface-alt);
	}

	.dd-chip--active {
		background: color-mix(in srgb, var(--netz-brand-primary) 12%, transparent);
		color: var(--netz-brand-primary);
		border-color: var(--netz-brand-primary);
		font-weight: 600;
	}

	/* ── Table ── */
	.dd-table-wrap {
		overflow-x: auto;
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
	}

	.dd-table {
		width: 100%;
		border-collapse: collapse;
		font-family: var(--netz-font-sans);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.dd-table th {
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-sm, 12px);
		background: var(--netz-surface-alt);
		color: var(--netz-text-muted);
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		text-align: left;
		white-space: nowrap;
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.dd-row {
		cursor: pointer;
		transition: background 80ms ease;
	}

	.dd-row:hover {
		background: var(--netz-surface-alt);
	}

	.dd-table td {
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-sm, 12px);
		border-bottom: 1px solid var(--netz-border-subtle);
		vertical-align: middle;
	}

	.dd-cell-name {
		display: flex;
		flex-direction: column;
		gap: 1px;
		min-width: 180px;
	}

	.dd-name {
		font-weight: 600;
		color: var(--netz-text-primary);
	}

	.dd-ticker {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.dd-cell-version {
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--netz-text-primary);
	}

	.dd-cell-num {
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.dd-cell-date {
		white-space: nowrap;
		color: var(--netz-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.dd-muted {
		color: var(--netz-text-muted);
	}

	.dd-anchor {
		font-weight: 600;
		padding: 2px 8px;
		border-radius: var(--netz-radius-pill, 999px);
		background: color-mix(in srgb, currentColor 10%, transparent);
	}

	.dd-action-btn {
		padding: var(--netz-space-stack-2xs, 4px) var(--netz-space-inline-sm, 12px);
		border: 1px solid var(--netz-border-accent);
		border-radius: var(--netz-radius-sm, 8px);
		background: transparent;
		color: var(--netz-brand-primary);
		font-size: var(--netz-text-label, 0.75rem);
		font-family: var(--netz-font-sans);
		font-weight: 600;
		cursor: pointer;
		white-space: nowrap;
		transition: background 120ms ease;
	}

	.dd-action-btn:hover {
		background: color-mix(in srgb, var(--netz-brand-primary) 8%, transparent);
	}

	@media (max-width: 768px) {
		.dd-toolbar {
			flex-direction: column;
			align-items: stretch;
		}

		.dd-search {
			max-width: none;
		}
	}
</style>
