<!-- Overview tab: paginated manager table — Figma layout -->
<script lang="ts">
	import { formatNumber, formatDate } from "@netz/ui/utils";
	import type { SecManagerSearchPage } from "$lib/types/sec-analysis";

	let {
		data,
		onSelect,
		onDetail,
		onPageChange,
		compareCiks = new Set<string>(),
		onToggleCompare,
	}: {
		data: SecManagerSearchPage;
		onSelect: (cik: string, name: string) => void;
		onDetail: (cik: string) => void;
		onPageChange: (page: number) => void;
		compareCiks?: Set<string>;
		onToggleCompare?: (cik: string) => void;
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
					<th class="mt-th mt-th--check" style="width: 48px;"></th>
					<th class="mt-th">Manager Name</th>
					<th class="mt-th">Entity Type</th>
					<th class="mt-th">State</th>
					<th class="mt-th mt-th--right">AUM ($)</th>
					<th class="mt-th mt-th--center">Funds</th>
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
						<td class="mt-td mt-td--check">
						{#if mgr.cik && onToggleCompare}
							<input
								type="checkbox"
								checked={compareCiks.has(mgr.cik)}
								onchange={() => onToggleCompare?.(mgr.cik!)}
								onclick={(e) => e.stopPropagation()}
								title="Select for comparison"
								class="mt-checkbox"
							/>
						{/if}
					</td>
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
							</div>
						</td>
						<td class="mt-td mt-td--entity">
							{mgr.registration_status ?? "\u2014"}
						</td>
						<td class="mt-td mt-td--state">
							{mgr.state ?? "\u2014"}
						</td>
						<td class="mt-td mt-td--aum">
							{mgr.aum_total != null ? `$${formatNumber(mgr.aum_total, 0)}` : "\u2014"}
						</td>
						<td class="mt-td mt-td--funds">
							{#if mgr.private_fund_count && mgr.private_fund_count > 0}
								<span class="mt-fund-tags">
									{#if mgr.hedge_fund_count}<span class="mt-fund-tag mt-fund-tag--hedge">HF {mgr.hedge_fund_count}</span>{/if}
									{#if mgr.pe_fund_count}<span class="mt-fund-tag mt-fund-tag--pe">PE {mgr.pe_fund_count}</span>{/if}
									{#if mgr.vc_fund_count}<span class="mt-fund-tag mt-fund-tag--vc">VC {mgr.vc_fund_count}</span>{/if}
								</span>
							{:else if mgr.has_13f_filings}
								<span class="mt-badge mt-badge--success">13F</span>
							{:else}
								<span class="mt-text-muted">{"\u2014"}</span>
							{/if}
						</td>
						<td class="mt-td mt-td--date">
							{#if mgr.last_filing_date}
								{formatDate(mgr.last_filing_date, "short")}
							{:else if mgr.last_adv_filed_at}
								{formatDate(mgr.last_adv_filed_at, "short")}
							{:else}
								{"\u2014"}
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
		color: #62748e;
		font-size: 14px;
	}

	.mt-summary {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 24px;
		font-size: 13px;
		color: #62748e;
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
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 1.1px;
		color: #62748e;
		text-align: left;
		background: rgba(248, 250, 252, 0.5);
		border-bottom: 1px solid #f1f5f9;
	}

	.mt-th--right {
		text-align: right;
	}

	.mt-th--center {
		text-align: center;
	}

	.mt-row {
		cursor: pointer;
		border-bottom: 1px solid #f1f5f9;
		transition: background 100ms ease;
		height: 64px;
	}

	.mt-row:hover {
		background: rgba(248, 250, 252, 0.5);
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
		background: #f1f5f9;
		display: flex;
		align-items: center;
		justify-content: center;
		color: #62748e;
		flex-shrink: 0;
	}

	.mt-name-btn {
		background: none;
		border: none;
		padding: 0;
		font-size: 14px;
		font-weight: 700;
		color: #1d293d;
		cursor: pointer;
		text-align: left;
	}

	.mt-name-btn:hover {
		text-decoration: underline;
	}

	.mt-td--entity {
		color: #62748e;
		font-weight: 500;
	}

	.mt-td--state {
		color: #62748e;
		font-weight: 500;
	}

	.mt-td--funds {
		text-align: center;
	}

	.mt-fund-tags {
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
		justify-content: center;
	}

	.mt-fund-tag {
		display: inline-block;
		padding: 2px 6px;
		font-size: 10px;
		font-weight: 700;
		border-radius: 4px;
		line-height: 1.2;
		letter-spacing: 0.3px;
	}

	.mt-fund-tag--hedge { background: #eff6ff; color: #1447e6; }
	.mt-fund-tag--pe { background: #f5f3ff; color: #7c3aed; }
	.mt-fund-tag--vc { background: #ecfdf5; color: #059669; }

	.mt-text-muted {
		color: #90a1b9;
	}

	.mt-td--aum {
		text-align: right;
		font-weight: 900;
		font-variant-numeric: tabular-nums;
		color: #314158;
	}

	.mt-td--date {
		text-align: right;
		color: #90a1b9;
		font-weight: 500;
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
		border: 1px solid #e2e8f0;
		border-radius: 4px;
		background: #ffffff;
		color: #1d293d;
		cursor: pointer;
	}

	.mt-page-btn:disabled {
		opacity: 0.4;
		cursor: default;
	}

	.mt-page-info {
		font-size: 12px;
		color: #62748e;
	}

	.mt-badge {
		display: inline-block;
		padding: 4px 8px;
		font-size: 11px;
		font-weight: 700;
		border-radius: 4px;
		line-height: 1;
		text-transform: uppercase;
		letter-spacing: 0.55px;
	}

	.mt-badge--success {
		background: #ecfdf5;
		color: #009966;
	}

	.mt-th--check,
	.mt-td--check {
		width: 48px;
		text-align: center;
		padding: 0 12px;
	}

	.mt-checkbox {
		width: 16px;
		height: 16px;
		border-radius: 4px;
		cursor: pointer;
		accent-color: #155dfc;
	}

	@media (max-width: 1024px) {
		.mt-th:last-child,
		.mt-td--date {
			display: none;
		}
	}
</style>
