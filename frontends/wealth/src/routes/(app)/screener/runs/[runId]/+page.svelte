<!--
  Screening Run Detail — results for a single run.
-->
<script lang="ts">
	import { formatDateTime, formatNumber } from "@investintell/ui";
	import type { PageData } from "./$types";
	import type { ScreeningResult } from "$lib/types/screening";

	let { data }: { data: PageData } = $props();

	let run = $derived((data as any).run);
	let results = $derived(((data as any).results ?? []) as ScreeningResult[]);

	// ── Expanded detail rows ──
	let expandedIds = $state<Set<string>>(new Set());
	function toggleExpand(id: string) {
		const next = new Set(expandedIds);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		expandedIds = next;
	}

	function layerLabel(n: number): string {
		if (n === 1) return "Eliminatory";
		if (n === 2) return "Mandate Fit";
		if (n === 3) return "Quant Scoring";
		return `Layer ${n}`;
	}
</script>

<div class="rd-page">
	<div class="rd-header">
		<a href="/screener?tab=screening" class="rd-back">&larr; Back to Screening</a>
		{#if run}
			<h1 class="rd-title">Screening Run</h1>
			<div class="rd-meta">
				<span class="rd-meta-item">
					<strong>Date:</strong> {formatDateTime(run.started_at)}
				</span>
				<span class="rd-meta-item">
					<strong>Type:</strong> {run.run_type}
				</span>
				<span class="rd-meta-item">
					<strong>Instruments:</strong> {formatNumber(run.instrument_count)}
				</span>
				<span class="rd-badge rd-badge--{run.status}">{run.status}</span>
			</div>
		{:else}
			<h1 class="rd-title">Run not found</h1>
		{/if}
	</div>

	{#if results.length === 0}
		<p class="rd-empty">No results for this run.</p>
	{:else}
		<div class="rd-table-wrap">
			<table class="rd-table">
				<thead>
					<tr>
						<th>Fund</th>
						<th>Ticker</th>
						<th>Block</th>
						<th>Status</th>
						<th>Score</th>
						<th>Failed At</th>
					</tr>
				</thead>
				<tbody>
					{#each results as r (r.id)}
						<tr class="rd-row" onclick={() => toggleExpand(r.id)}>
							<td class="rd-cell-name">{r.name ?? "\u2014"}</td>
							<td class="rd-cell-mono">{r.ticker ?? "\u2014"}</td>
							<td>{r.block_id ?? "\u2014"}</td>
							<td>
								<span class="rd-status rd-status--{r.overall_status.toLowerCase()}">
									{r.overall_status}
								</span>
							</td>
							<td class="rd-cell-num">{r.score != null ? formatNumber(r.score, 1) : "\u2014"}</td>
							<td>{r.failed_at_layer != null ? layerLabel(r.failed_at_layer) : "\u2014"}</td>
						</tr>
						{#if expandedIds.has(r.id) && r.layer_results?.length}
							<tr class="rd-detail-row">
								<td colspan="6">
									<div class="rd-layer-detail">
										{#each r.layer_results as lr, i}
											<div class="rd-layer-item">
												<span class="rd-layer-badge" class:rd-layer-badge--pass={lr.passed} class:rd-layer-badge--fail={!lr.passed}>
													{lr.passed ? "PASS" : "FAIL"}
												</span>
												<span class="rd-layer-criterion">
													<strong>L{lr.layer ?? i + 1}:</strong> {lr.criterion}
												</span>
												<span class="rd-layer-values">
													expected {lr.expected}, actual {lr.actual}
												</span>
											</div>
										{/each}
									</div>
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>

<style>
	.rd-page {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding: 24px;
		height: calc(100vh - 48px);
		overflow-y: auto;
	}

	.rd-header {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.rd-back {
		font-size: 13px;
		color: var(--ii-brand-primary, #1447e6);
		text-decoration: none;
	}

	.rd-back:hover {
		text-decoration: underline;
	}

	.rd-title {
		font-size: 20px;
		font-weight: 800;
		color: var(--ii-text-primary);
		margin: 0;
	}

	.rd-meta {
		display: flex;
		align-items: center;
		gap: 16px;
		font-size: 13px;
		color: var(--ii-text-secondary);
	}

	.rd-meta-item strong {
		color: var(--ii-text-muted);
		font-weight: 600;
	}

	.rd-badge {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 4px;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
	}

	.rd-badge--completed {
		background: color-mix(in srgb, var(--ii-success, #22c55e) 12%, transparent);
		color: var(--ii-success, #22c55e);
	}

	.rd-badge--running {
		background: color-mix(in srgb, var(--ii-brand-primary, #1447e6) 12%, transparent);
		color: var(--ii-brand-primary, #1447e6);
	}

	.rd-empty {
		font-size: 13px;
		color: var(--ii-text-muted);
		padding: 24px 0;
	}

	/* ── Table ── */
	.rd-table-wrap {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 8px);
		overflow: hidden;
	}

	.rd-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}

	.rd-table th {
		background: var(--ii-surface-alt, #f7f8fa);
		font-weight: 600;
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ii-text-muted);
		padding: 8px 12px;
		text-align: left;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.rd-table td {
		padding: 8px 12px;
		border-bottom: 1px solid var(--ii-border-subtle);
		color: var(--ii-text-primary);
	}

	.rd-table tbody tr:last-child td {
		border-bottom: none;
	}

	.rd-row {
		cursor: pointer;
		transition: background 80ms ease;
	}

	.rd-row:hover {
		background: var(--ii-surface-alt, #f7f8fa);
	}

	.rd-cell-name {
		font-weight: 500;
		max-width: 280px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.rd-cell-mono {
		font-family: var(--ii-font-mono, monospace);
		font-size: 12px;
	}

	.rd-cell-num {
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	/* ── Status badges ── */
	.rd-status {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 4px;
		font-size: 11px;
		font-weight: 700;
	}

	.rd-status--pass {
		background: color-mix(in srgb, var(--ii-success, #22c55e) 12%, transparent);
		color: var(--ii-success, #22c55e);
	}

	.rd-status--fail {
		background: color-mix(in srgb, var(--ii-danger, #ef4444) 12%, transparent);
		color: var(--ii-danger, #ef4444);
	}

	.rd-status--watchlist {
		background: color-mix(in srgb, var(--ii-warning, #f59e0b) 12%, transparent);
		color: var(--ii-warning, #f59e0b);
	}

	/* ── Layer detail ── */
	.rd-detail-row td {
		padding: 0 12px 12px;
		background: var(--ii-surface-alt, #f7f8fa);
	}

	.rd-layer-detail {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 8px 0;
	}

	.rd-layer-item {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 12px;
	}

	.rd-layer-badge {
		display: inline-block;
		padding: 1px 6px;
		border-radius: 3px;
		font-size: 10px;
		font-weight: 700;
	}

	.rd-layer-badge--pass {
		background: color-mix(in srgb, var(--ii-success, #22c55e) 12%, transparent);
		color: var(--ii-success, #22c55e);
	}

	.rd-layer-badge--fail {
		background: color-mix(in srgb, var(--ii-danger, #ef4444) 12%, transparent);
		color: var(--ii-danger, #ef4444);
	}

	.rd-layer-criterion {
		color: var(--ii-text-primary);
	}

	.rd-layer-values {
		color: var(--ii-text-muted);
		font-size: 11px;
	}
</style>
