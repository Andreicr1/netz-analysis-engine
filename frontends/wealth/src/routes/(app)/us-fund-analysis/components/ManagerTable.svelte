<!-- Overview tab: paginated manager table — Figma layout -->
<script lang="ts">
	import { formatNumber, formatDate } from "@netz/ui/utils";
	import type { SecManagerSearchPage, SecManagerItem } from "$lib/types/sec-analysis";

	const TWELVE_MONTHS_MS = 365 * 24 * 60 * 60 * 1000;

	function filingStatus(mgr: SecManagerItem): "none" | "stale" | "ok" {
		if (!mgr.last_adv_filed_at) return "none";
		const filedDate = new Date(mgr.last_adv_filed_at);
		const cutoff = Date.now() - TWELVE_MONTHS_MS;
		return filedDate.getTime() < cutoff ? "stale" : "ok";
	}

	let {
		data,
		onSelect,
		onDetail,
		onPageChange,
	}: {
		data: SecManagerSearchPage;
		onSelect: (cik: string, name: string) => void;
		onDetail: (cik: string) => void;
		onPageChange: (page: number) => void;
	} = $props();

	let totalPages = $derived(Math.ceil(data.total_count / data.page_size) || 1);
</script>

{#if data.managers.length === 0}
	<div class="mt-empty">
		<p>No managers found. Try adjusting your filters.</p>
	</div>
{:else}
	<div class="mt-summary">
		<span>{formatNumber(data.total_count, 0)} managers</span>
		<span class="mt-summary__page">
			Page {data.page} of {totalPages}
		</span>
	</div>

	<div class="mt-table-wrap">
		<table class="mt-table">
			<thead>
				<tr>
					<th class="mt-th">Manager Name</th>
					<th class="mt-th">Entity Type</th>
					<th class="mt-th mt-th--right">AUM ($)</th>
					<th class="mt-th mt-th--right">Last Filing</th>
				</tr>
			</thead>
			<tbody>
				{#each data.managers as mgr (mgr.crd_number)}
					<tr
						class="mt-row"
						class:mt-row--no-cik={!mgr.cik}
						onclick={() => mgr.cik && onSelect(mgr.cik, mgr.firm_name)}
					>
						<td class="mt-td mt-td--name">
							<div class="mt-name-cell">
								<div class="mt-avatar">
									<svg width="16" height="16" viewBox="0 0 16 16" fill="none">
										<path d="M2 14V3h5v3h5v8H2zm1-1h3V4H3v9zm4 0h3V7H7v6z"
											fill="currentColor" opacity="0.5"/>
									</svg>
								</div>
								<button
									class="mt-name-btn"
									onclick={(e: MouseEvent) => { e.stopPropagation(); mgr.cik && onDetail(mgr.cik); }}
									title="View detail"
								>
									{mgr.firm_name}
								</button>
								{#if mgr.compliance_disclosures && mgr.compliance_disclosures > 0}
									<span class="mt-badge mt-badge--destructive" title="Has compliance disclosures">Flagged</span>
								{/if}
							</div>
						</td>
						<td class="mt-td mt-td--entity">
							{mgr.registration_status ?? "\u2014"}
						</td>
						<td class="mt-td mt-td--aum">
							{mgr.aum_total != null ? `$${formatNumber(mgr.aum_total, 0)}` : "\u2014"}
						</td>
						<td class="mt-td mt-td--date">
							{#if filingStatus(mgr) === "none"}
								<span class="mt-badge mt-badge--warning">No Filing</span>
							{:else if filingStatus(mgr) === "stale"}
								<span class="mt-badge mt-badge--destructive">Stale</span>
								<span class="mt-filing-date">{formatDate(mgr.last_adv_filed_at!, "short")}</span>
							{:else}
								{formatDate(mgr.last_adv_filed_at!, "medium")}
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	<!-- Pagination -->
	<div class="mt-pagination">
		<button
			class="mt-page-btn"
			disabled={data.page <= 1}
			onclick={() => onPageChange(data.page - 1)}
		>
			Prev
		</button>
		<span class="mt-page-info">
			{data.page} / {totalPages}
		</span>
		<button
			class="mt-page-btn"
			disabled={!data.has_next}
			onclick={() => onPageChange(data.page + 1)}
		>
			Next
		</button>
	</div>
{/if}

<style>
	.mt-empty {
		padding: 48px 24px;
		text-align: center;
		color: var(--netz-text-muted);
		font-size: 14px;
	}

	.mt-summary {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 24px;
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-muted);
	}

	.mt-table-wrap {
		overflow-x: auto;
	}

	.mt-table {
		width: 100%;
		border-collapse: collapse;
	}

	.mt-th {
		padding: 12px 24px;
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--netz-text-muted);
		text-align: left;
		background: color-mix(in srgb, var(--netz-surface-alt) 50%, transparent);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.mt-th--right {
		text-align: right;
	}

	.mt-row {
		cursor: pointer;
		border-bottom: 1px solid var(--netz-border-subtle);
		transition: background 100ms ease;
	}

	.mt-row:hover {
		background: color-mix(in srgb, var(--netz-surface-alt) 30%, transparent);
	}

	.mt-row:last-child {
		border-bottom: none;
	}

	.mt-row--no-cik {
		cursor: default;
		opacity: 0.5;
	}

	.mt-td {
		padding: 16px 24px;
		font-size: 14px;
		vertical-align: middle;
	}

	.mt-td--name {
		min-width: 280px;
	}

	.mt-name-cell {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.mt-avatar {
		width: 32px;
		height: 32px;
		border-radius: 10px;
		background: var(--netz-surface-alt);
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--netz-text-muted);
		flex-shrink: 0;
	}

	.mt-name-btn {
		background: none;
		border: none;
		padding: 0;
		font-size: 14px;
		font-weight: 700;
		color: var(--netz-text-primary);
		cursor: pointer;
		text-align: left;
	}

	.mt-name-btn:hover {
		text-decoration: underline;
	}

	.mt-td--entity {
		color: var(--netz-text-secondary);
	}

	.mt-td--aum {
		text-align: right;
		font-weight: 900;
		font-variant-numeric: tabular-nums;
		color: var(--netz-text-primary);
	}

	.mt-td--date {
		text-align: right;
		color: var(--netz-text-muted);
	}

	.mt-pagination {
		display: flex;
		justify-content: center;
		align-items: center;
		gap: 12px;
		padding: 12px 24px;
	}

	.mt-page-btn {
		padding: 4px 12px;
		font-size: 12px;
		border: 1px solid var(--netz-border-subtle);
		border-radius: 4px;
		background: var(--netz-surface-primary);
		color: var(--netz-text-primary);
		cursor: pointer;
	}

	.mt-page-btn:disabled {
		opacity: 0.4;
		cursor: default;
	}

	.mt-page-info {
		font-size: 12px;
		color: var(--netz-text-muted);
	}

	.mt-badge {
		display: inline-block;
		padding: 2px 8px;
		font-size: 11px;
		font-weight: 700;
		border-radius: 6px;
		line-height: 1.4;
	}

	.mt-badge--warning {
		background: color-mix(in srgb, var(--netz-status-warning, #f59e0b) 15%, transparent);
		color: var(--netz-status-warning, #f59e0b);
	}

	.mt-badge--destructive {
		background: color-mix(in srgb, var(--netz-status-error, #ef4444) 15%, transparent);
		color: var(--netz-status-error, #ef4444);
	}

	.mt-filing-date {
		margin-left: 6px;
		font-size: 12px;
		color: var(--netz-text-muted);
	}

	@media (max-width: 1024px) {
		.mt-th:last-child,
		.mt-td--date {
			display: none;
		}
	}
</style>
