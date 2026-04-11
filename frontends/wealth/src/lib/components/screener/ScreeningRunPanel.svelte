<!--
  ScreeningRunPanel — Batch screening: trigger, run history, current results.
  Fire-and-forget: POST /screener/run returns 202. No polling.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { goto } from "$app/navigation";
	import { formatDateTime, formatNumber, formatAUM } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type {
		ScreeningRun,
		ScreeningResult,
		ScreeningRunRequest,
		ScreeningRunResponse,
	} from "$lib/types/screening";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	let {
		runs = [],
		results = [],
	}: {
		runs: ScreeningRun[];
		results: ScreeningResult[];
	} = $props();

	// ── Run dialog state ──
	let dialogOpen = $state(false);
	let runInstrumentType = $state("");
	let runBlockId = $state("");
	let submitting = $state(false);
	let statusMsg = $state<{ type: "success" | "error"; text: string } | null>(null);

	// ── Results filter ──
	let statusFilter = $state<"" | "PASS" | "FAIL" | "WATCHLIST">("");
	let filteredResults = $derived(
		statusFilter ? results.filter((r) => r.overall_status === statusFilter) : results,
	);

	// ── Expanded result rows (layer detail) ──
	let expandedIds = $state<Set<string>>(new Set());
	function toggleExpand(id: string) {
		const next = new Set(expandedIds);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		expandedIds = next;
	}

	// ── Trigger screening ──
	async function triggerRun() {
		submitting = true;
		statusMsg = null;
		try {
			const body: ScreeningRunRequest = {};
			if (runInstrumentType) body.instrument_type = runInstrumentType;
			if (runBlockId) body.block_id = runBlockId;
			const resp = await api.post<ScreeningRunResponse>("/screener/run", body);
			statusMsg = {
				type: "success",
				text: `Screening completed: ${formatNumber(resp.instrument_count)} instruments evaluated (run ${resp.run_id.slice(0, 8)})`,
			};
			dialogOpen = false;
			runInstrumentType = "";
			runBlockId = "";
			// Reload to pick up new results
			goto("?tab=screening", { invalidateAll: true });
		} catch (e: any) {
			statusMsg = {
				type: "error",
				text: e?.message ?? "Failed to trigger screening run",
			};
		} finally {
			submitting = false;
		}
	}

	function layerLabel(n: number): string {
		if (n === 1) return "Eliminatory";
		if (n === 2) return "Mandate Fit";
		if (n === 3) return "Quant Scoring";
		return `Layer ${n}`;
	}
</script>

<div class="sp-root">
	<!-- ── Status message ── -->
	{#if statusMsg}
		<div class="sp-toast sp-toast--{statusMsg.type}">
			{statusMsg.text}
			<button class="sp-toast-close" onclick={() => (statusMsg = null)}>&times;</button>
		</div>
	{/if}

	<!-- ══════════ TRIGGER SECTION ══════════ -->
	<div class="sp-section">
		<div class="sp-section-header">
			<h3 class="sp-section-title">Run Screening</h3>
			<button class="sp-btn sp-btn--primary" onclick={() => (dialogOpen = true)}>
				Run Screening Now
			</button>
		</div>
		<p class="sp-section-desc">
			Evaluate approved instruments against the 3-layer screening pipeline (eliminatory, mandate fit, quant scoring).
		</p>
	</div>

	<!-- ══════════ RUN HISTORY ══════════ -->
	<div class="sp-section">
		<h3 class="sp-section-title">Run History</h3>
		{#if runs.length === 0}
			<p class="sp-empty">No screening runs yet.</p>
		{:else}
			<div class="sp-table-wrap">
				<table class="sp-table">
					<thead>
						<tr>
							<th>Date</th>
							<th>Type</th>
							<th>Instruments</th>
							<th>Status</th>
						</tr>
					</thead>
					<tbody>
						{#each runs as run (run.run_id)}
							<tr class="sp-row--click" onclick={() => goto(`/screener/runs/${run.run_id}`)}>
								<td>{formatDateTime(run.started_at)}</td>
								<td class="sp-cell-type">{run.run_type}</td>
								<td>{formatNumber(run.instrument_count)}</td>
								<td>
									<span class="sp-badge sp-badge--{run.status}">
										{run.status}
									</span>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>

	<!-- ══════════ CURRENT RESULTS ══════════ -->
	<div class="sp-section">
		<div class="sp-section-header">
			<h3 class="sp-section-title">Current Results</h3>
			<div class="sp-filter-row">
				<select class="sp-dropdown" bind:value={statusFilter}>
					<option value="">All Statuses</option>
					<option value="PASS">PASS</option>
					<option value="FAIL">FAIL</option>
					<option value="WATCHLIST">WATCHLIST</option>
				</select>
				<span class="sp-count">{formatNumber(filteredResults.length)} results</span>
			</div>
		</div>

		{#if filteredResults.length === 0}
			<p class="sp-empty">No screening results. Run a screening to evaluate your universe.</p>
		{:else}
			<div class="sp-table-wrap sp-table-wrap--scroll">
				<table class="sp-table">
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
						{#each filteredResults as r (r.id)}
							<tr
								class="sp-row--click"
								class:sp-row--expanded={expandedIds.has(r.id)}
								onclick={() => toggleExpand(r.id)}
							>
								<td class="sp-cell-name">{r.name ?? "\u2014"}</td>
								<td class="sp-cell-mono">{r.ticker ?? "\u2014"}</td>
								<td>{r.block_id ?? "\u2014"}</td>
								<td>
									<span class="sp-status sp-status--{r.overall_status.toLowerCase()}">
										{r.overall_status}
									</span>
								</td>
								<td class="sp-cell-num">{r.score != null ? formatNumber(r.score, 1) : "\u2014"}</td>
								<td>{r.failed_at_layer != null ? layerLabel(r.failed_at_layer) : "\u2014"}</td>
							</tr>
							{#if expandedIds.has(r.id) && r.layer_results?.length}
								<tr class="sp-detail-row">
									<td colspan="6">
										<div class="sp-layer-detail">
											{#each r.layer_results as lr, i}
												<div class="sp-layer-item">
													<span class="sp-layer-badge" class:sp-layer-badge--pass={lr.passed} class:sp-layer-badge--fail={!lr.passed}>
														{lr.passed ? "PASS" : "FAIL"}
													</span>
													<span class="sp-layer-criterion">
														<strong>L{lr.layer ?? i + 1}:</strong> {lr.criterion}
													</span>
													<span class="sp-layer-values">
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
</div>

<!-- ══════════ RUN DIALOG ══════════ -->
{#if dialogOpen}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="sp-overlay" onclick={() => { if (!submitting) dialogOpen = false; }} onkeydown={() => {}}>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="sp-dialog" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
			<h3 class="sp-dialog-title">Run Batch Screening</h3>
			<p class="sp-dialog-desc">
				Leave fields blank to screen all approved instruments.
			</p>

			<label class="sp-field">
				<span class="sp-field-label">Instrument Type (optional)</span>
				<select class="sp-dropdown" bind:value={runInstrumentType}>
					<option value="">All types</option>
					<option value="fund">Fund</option>
					<option value="etf">ETF</option>
					<option value="equity">Equity</option>
					<option value="bond">Bond</option>
				</select>
			</label>

			<label class="sp-field">
				<span class="sp-field-label">Block ID (optional)</span>
				<input
					class="sp-input"
					type="text"
					placeholder="e.g. equities_us"
					bind:value={runBlockId}
				/>
			</label>

			<div class="sp-dialog-actions">
				<button class="sp-btn sp-btn--ghost" onclick={() => (dialogOpen = false)} disabled={submitting}>
					Cancel
				</button>
				<button class="sp-btn sp-btn--primary" onclick={triggerRun} disabled={submitting}>
					{submitting ? "Running..." : "Run Screening"}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.sp-root {
		display: flex;
		flex-direction: column;
		gap: 24px;
		padding: 0 24px 24px;
		overflow-y: auto;
	}

	/* ── Sections ── */
	.sp-section {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.sp-section-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}

	.sp-section-title {
		font-size: 14px;
		font-weight: 700;
		color: var(--ii-text-primary);
		margin: 0;
	}

	.sp-section-desc {
		font-size: 13px;
		color: var(--ii-text-muted);
		margin: 0;
	}

	.sp-empty {
		font-size: 13px;
		color: var(--ii-text-muted);
		padding: 16px 0;
	}

	/* ── Filter row ── */
	.sp-filter-row {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.sp-count {
		font-size: 12px;
		color: var(--ii-text-muted);
		white-space: nowrap;
	}

	/* ── Tables ── */
	.sp-table-wrap {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 8px);
		overflow: hidden;
	}

	.sp-table-wrap--scroll {
		max-height: 480px;
		overflow-y: auto;
	}

	.sp-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}

	.sp-table thead {
		position: sticky;
		top: 0;
		z-index: 1;
	}

	.sp-table th {
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

	.sp-table td {
		padding: 8px 12px;
		border-bottom: 1px solid var(--ii-border-subtle);
		color: var(--ii-text-primary);
	}

	.sp-table tbody tr:last-child td {
		border-bottom: none;
	}

	.sp-row--click {
		cursor: pointer;
		transition: background 80ms ease;
	}

	.sp-row--click:hover {
		background: var(--ii-surface-alt, #f7f8fa);
	}

	.sp-row--expanded {
		background: var(--ii-surface-alt, #f7f8fa);
	}

	.sp-cell-name {
		font-weight: 500;
		max-width: 240px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.sp-cell-mono {
		font-family: var(--ii-font-mono, monospace);
		font-size: 12px;
	}

	.sp-cell-num {
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	.sp-cell-type {
		text-transform: capitalize;
	}

	/* ── Badges ── */
	.sp-badge {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 4px;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
	}

	.sp-badge--completed {
		background: color-mix(in srgb, var(--ii-success, #22c55e) 12%, transparent);
		color: var(--ii-success, #22c55e);
	}

	.sp-badge--running {
		background: color-mix(in srgb, var(--ii-brand-primary, #1447e6) 12%, transparent);
		color: var(--ii-brand-primary, #1447e6);
	}

	.sp-status {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 4px;
		font-size: 11px;
		font-weight: 700;
	}

	.sp-status--pass {
		background: color-mix(in srgb, var(--ii-success, #22c55e) 12%, transparent);
		color: var(--ii-success, #22c55e);
	}

	.sp-status--fail {
		background: color-mix(in srgb, var(--ii-danger, #ef4444) 12%, transparent);
		color: var(--ii-danger, #ef4444);
	}

	.sp-status--watchlist {
		background: color-mix(in srgb, var(--ii-warning, #f59e0b) 12%, transparent);
		color: var(--ii-warning, #f59e0b);
	}

	/* ── Layer detail (expanded row) ── */
	.sp-detail-row td {
		padding: 0 12px 12px;
		background: var(--ii-surface-alt, #f7f8fa);
	}

	.sp-layer-detail {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 8px 0;
	}

	.sp-layer-item {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 12px;
	}

	.sp-layer-badge {
		display: inline-block;
		padding: 1px 6px;
		border-radius: 3px;
		font-size: 10px;
		font-weight: 700;
	}

	.sp-layer-badge--pass {
		background: color-mix(in srgb, var(--ii-success, #22c55e) 12%, transparent);
		color: var(--ii-success, #22c55e);
	}

	.sp-layer-badge--fail {
		background: color-mix(in srgb, var(--ii-danger, #ef4444) 12%, transparent);
		color: var(--ii-danger, #ef4444);
	}

	.sp-layer-criterion {
		color: var(--ii-text-primary);
	}

	.sp-layer-values {
		color: var(--ii-text-muted);
		font-size: 11px;
	}

	/* ── Buttons ── */
	.sp-btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 8px 16px;
		border-radius: 8px;
		font-size: 13px;
		font-weight: 600;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		transition: all 120ms ease;
		border: none;
	}

	.sp-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.sp-btn--primary {
		background: var(--ii-brand-primary, #1447e6);
		color: #fff;
	}

	.sp-btn--primary:hover:not(:disabled) {
		filter: brightness(1.1);
	}

	.sp-btn--ghost {
		background: transparent;
		color: var(--ii-text-secondary);
		border: 1px solid var(--ii-border);
	}

	.sp-btn--ghost:hover:not(:disabled) {
		background: var(--ii-surface-alt);
	}

	/* ── Dropdown / Input ── */
	.sp-dropdown {
		height: 34px;
		padding: 0 28px 0 10px;
		border: 1px solid var(--ii-border);
		border-radius: 8px;
		background: var(--ii-surface-elevated);
		color: var(--ii-text-primary);
		font-size: 13px;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		appearance: none;
		background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 24 24' fill='none' stroke='%2362748e' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
		background-repeat: no-repeat;
		background-position: right 8px center;
	}

	.sp-input {
		height: 34px;
		padding: 0 10px;
		border: 1px solid var(--ii-border);
		border-radius: 8px;
		background: var(--ii-surface-elevated);
		font-size: 13px;
		color: var(--ii-text-primary);
		font-family: var(--ii-font-sans);
		width: 100%;
	}

	.sp-input:focus,
	.sp-dropdown:focus {
		outline: none;
		border-color: var(--ii-border-focus);
	}

	/* ── Dialog overlay ── */
	.sp-overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.4);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
	}

	.sp-dialog {
		background: var(--ii-surface, #fff);
		border-radius: 12px;
		padding: 24px;
		width: 400px;
		max-width: 90vw;
		display: flex;
		flex-direction: column;
		gap: 16px;
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
	}

	.sp-dialog-title {
		font-size: 16px;
		font-weight: 700;
		color: var(--ii-text-primary);
		margin: 0;
	}

	.sp-dialog-desc {
		font-size: 13px;
		color: var(--ii-text-muted);
		margin: 0;
	}

	.sp-field {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.sp-field-label {
		font-size: 12px;
		font-weight: 600;
		color: var(--ii-text-secondary);
	}

	.sp-dialog-actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 4px;
	}

	/* ── Toast ── */
	.sp-toast {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 16px;
		border-radius: 8px;
		font-size: 13px;
		font-weight: 500;
	}

	.sp-toast--success {
		background: color-mix(in srgb, var(--ii-success, #22c55e) 10%, transparent);
		border: 1px solid var(--ii-success, #22c55e);
		color: var(--ii-text-primary);
	}

	.sp-toast--error {
		background: color-mix(in srgb, var(--ii-danger, #ef4444) 10%, transparent);
		border: 1px solid var(--ii-danger, #ef4444);
		color: var(--ii-text-primary);
	}

	.sp-toast-close {
		background: none;
		border: none;
		font-size: 16px;
		cursor: pointer;
		color: var(--ii-text-muted);
		padding: 0 4px;
	}
</style>
