<!--
  WeightVectorTable — Phase 9 Block D drift analysis surface.

  Renders a semantic HTML table crossing target weights (from the
  portfolio's fund_selection_schema) against actual weights (from
  the backend GET /actual-holdings endpoint, passed in as props).

  Drift column = Actual - Target. Highlighted when |drift| > 2pp.

  The parent LiveWorkbenchShell owns the holdings state and passes
  it down. This component is pure presentation — no fetches, no
  stores, no side effects.

  Per CLAUDE.md: DL16 (formatters), DL17 (no @tanstack/svelte-table),
  DL15 (no localStorage).
-->
<script lang="ts">
	import { formatPercent } from "@investintell/ui";
	import { blockLabel } from "$lib/constants/blocks";
	import type { InstrumentWeight } from "$lib/types/model-portfolio";

	interface ActualHolding {
		instrument_id: string;
		fund_name: string;
		block_id: string;
		weight: number;
	}

	interface DriftRow {
		instrumentId: string;
		fundName: string;
		blockId: string;
		targetWeight: number;
		actualWeight: number;
		drift: number;
		absDrift: number;
	}

	interface Props {
		targetFunds: readonly InstrumentWeight[];
		actualHoldings: readonly ActualHolding[];
		loading?: boolean;
		/** When true, hides the Block column for tighter layout. */
		compact?: boolean;
	}

	let {
		targetFunds,
		actualHoldings,
		loading = false,
		compact = false,
	}: Props = $props();

	const rows = $derived.by<DriftRow[]>(() => {
		const actualMap = new Map(
			actualHoldings.map((h) => [h.instrument_id, h]),
		);
		return targetFunds
			.map((f) => {
				const actual = actualMap.get(f.instrument_id);
				const actualWeight = actual?.weight ?? f.weight;
				const drift = actualWeight - f.weight;
				return {
					instrumentId: f.instrument_id,
					fundName: f.fund_name,
					blockId: f.block_id,
					targetWeight: f.weight,
					actualWeight,
					drift,
					absDrift: Math.abs(drift),
				};
			})
			.sort((a, b) => b.absDrift - a.absDrift);
	});

	const totalTarget = $derived(
		rows.reduce((s, r) => s + r.targetWeight, 0),
	);
	const totalActual = $derived(
		rows.reduce((s, r) => s + r.actualWeight, 0),
	);
	const totalDrift = $derived(totalActual - totalTarget);

	function driftAccent(absDrift: number): "ok" | "warn" | "danger" {
		if (absDrift >= 0.03) return "danger";
		if (absDrift >= 0.02) return "warn";
		return "ok";
	}

	function driftSign(drift: number): string {
		return drift > 0 ? "+" : "";
	}
</script>

<section class="wvt-root" aria-label="Weight drift analysis">
	{#if loading}
		<div class="wvt-loading">
			<div class="wvt-spinner"></div>
			<span>Loading holdings...</span>
		</div>
	{:else}
		<table class="wvt-table">
			<thead>
				<tr>
					<th class="wvt-th wvt-th--name">Fund</th>
					{#if !compact}
						<th class="wvt-th wvt-th--block">Block</th>
					{/if}
					<th class="wvt-th wvt-th--num">Target</th>
					<th class="wvt-th wvt-th--num">Actual</th>
					<th class="wvt-th wvt-th--num">Drift</th>
				</tr>
			</thead>
			<tbody>
				{#each rows as row (row.instrumentId)}
					{@const accent = driftAccent(row.absDrift)}
					<tr class="wvt-row" data-accent={accent}>
						<td class="wvt-td wvt-td--name" title={row.fundName}>
							{row.fundName}
						</td>
						{#if !compact}
							<td class="wvt-td wvt-td--block">
								{blockLabel(row.blockId)}
							</td>
						{/if}
						<td class="wvt-td wvt-td--num">
							{formatPercent(row.targetWeight, 2)}
						</td>
						<td class="wvt-td wvt-td--num">
							{formatPercent(row.actualWeight, 2)}
						</td>
						<td
							class="wvt-td wvt-td--num wvt-td--drift"
							data-accent={accent}
						>
							{driftSign(row.drift)}{formatPercent(row.drift, 2)}
						</td>
					</tr>
				{:else}
					<tr>
						<td colspan={compact ? 4 : 5} class="wvt-td wvt-empty">
							No funds in portfolio
						</td>
					</tr>
				{/each}
			</tbody>
			<tfoot>
				<tr class="wvt-footer">
					<td class="wvt-td wvt-td--name wvt-td--bold">Total</td>
					{#if !compact}
						<td class="wvt-td"></td>
					{/if}
					<td class="wvt-td wvt-td--num wvt-td--bold">
						{formatPercent(totalTarget, 2)}
					</td>
					<td class="wvt-td wvt-td--num wvt-td--bold">
						{formatPercent(totalActual, 2)}
					</td>
					<td
						class="wvt-td wvt-td--num wvt-td--drift wvt-td--bold"
						data-accent={driftAccent(Math.abs(totalDrift))}
					>
						{driftSign(totalDrift)}{formatPercent(totalDrift, 2)}
					</td>
				</tr>
			</tfoot>
		</table>
	{/if}
</section>

<style>
	.wvt-root {
		width: 100%;
		overflow-y: auto;
		min-height: 0;
	}
	.wvt-loading {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 10px;
		padding: 48px 16px;
		font-size: 12px;
		color: var(--ii-text-muted, #85a0bd);
	}
	.wvt-spinner {
		width: 16px;
		height: 16px;
		border: 2px solid rgba(133, 160, 189, 0.3);
		border-top-color: var(--ii-brand-accent, #2d7ef7);
		border-radius: 50%;
		animation: wvt-spin 0.6s linear infinite;
	}
	@keyframes wvt-spin {
		to {
			transform: rotate(360deg);
		}
	}
	.wvt-table {
		width: 100%;
		border-collapse: collapse;
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 12px;
	}
	.wvt-th {
		position: sticky;
		top: 0;
		z-index: 1;
		padding: 8px 10px;
		font-size: 9px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, #85a0bd);
		background: #131722;
		border-bottom: 1px solid rgba(255, 255, 255, 0.1);
		text-align: left;
		white-space: nowrap;
	}
	.wvt-th--num {
		text-align: right;
	}
	.wvt-td {
		padding: 7px 10px;
		color: var(--ii-text-primary, #ffffff);
		border-bottom: 1px solid rgba(255, 255, 255, 0.04);
		vertical-align: middle;
	}
	.wvt-td--name {
		max-width: 220px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.wvt-td--block {
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
	}
	.wvt-td--num {
		text-align: right;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.wvt-td--drift[data-accent="ok"] {
		color: var(--ii-text-primary, #ffffff);
	}
	.wvt-td--drift[data-accent="warn"] {
		color: var(--ii-warning, #f0a020);
		font-weight: 700;
	}
	.wvt-td--drift[data-accent="danger"] {
		color: var(--ii-danger, #fc1a1a);
		font-weight: 700;
	}
	.wvt-td--bold {
		font-weight: 700;
	}
	.wvt-row:hover {
		background: rgba(255, 255, 255, 0.03);
	}
	.wvt-row[data-accent="danger"] {
		background: rgba(252, 26, 26, 0.04);
	}
	.wvt-row[data-accent="warn"] {
		background: rgba(240, 160, 32, 0.03);
	}
	.wvt-footer {
		border-top: 1px solid rgba(255, 255, 255, 0.1);
	}
	.wvt-footer .wvt-td {
		padding-top: 10px;
		border-bottom: none;
	}
	.wvt-empty {
		text-align: center;
		padding: 32px 10px;
		color: var(--ii-text-muted, #85a0bd);
		font-style: italic;
	}
</style>
